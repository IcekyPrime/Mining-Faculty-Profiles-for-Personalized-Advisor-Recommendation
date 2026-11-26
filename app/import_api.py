# -*- coding: utf-8 -*-
"""数据工坊接口：上传 → 预览 → AI 复核 → 应用 → 处理层刷新。

所有写库动作都必须经过预览任务 token，不能直接上传即入库；应用前自动备份。
"""
import csv
import io
import os
import re
import threading

from flask import Blueprint, Response, current_app, jsonify, request

from . import import_ai, import_engine, import_store
from .ai_client import AIError
from .ai_config import load_config
from .ai_enrich import PIPELINE_STEPS, _run_step
from .api import ApiError

bp = Blueprint("import_api", __name__, url_prefix="/api/import")
TOKEN_RE = re.compile(r"^[a-f0-9]{16}$")
MODES = {"auto", "teacher", "paper", "course"}
CONFLICTS = {"skip", "update_empty", "update_all"}
TEMPLATE_HEADERS = {
    "teacher": ["姓名", "姓名拼音", "学院", "职称", "邮箱", "学科", "研究方向",
                "个人简介", "教师主页", "是否博导", "荣誉"],
    "paper": ["教师姓名", "论文标题", "年份", "期刊/会议", "DOI", "引用数", "作者"],
    "course": ["教师姓名", "课程名称", "课程代码", "评分", "评价人数", "最近学期", "课程链接"],
}


def _db_path():
    return current_app.config["DB_PATH"]


def _import_dir():
    return current_app.config["IMPORT_DIR"]


def _config():
    return load_config(
        current_app.config["BASE_DIR"],
        current_app.config.get("AI_CONFIG_PATH"),
    )


def _json_body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("请求体必须是 JSON 对象。", code="invalid_json")
    return payload


def _token(value):
    token = str(value or "").strip()
    if not TOKEN_RE.match(token):
        raise ApiError("导入任务 token 无效。", code="invalid_param")
    return token


def _mode(value):
    mode = str(value or "auto").strip().lower()
    if mode not in MODES:
        raise ApiError("mode 只能是 auto、teacher、paper、course。", code="invalid_param")
    return mode


def _conflict(value):
    conflict = str(value or "skip").strip().lower()
    if conflict not in CONFLICTS:
        raise ApiError("conflict 只能是 skip、update_empty、update_all。", code="invalid_param")
    return conflict


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _page(value, default, maximum=200):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(maximum, number))


def _job_or_404(token, include_rows=False):
    job = import_store.get_job(
        _db_path(), token, include_rows=include_rows, import_dir=_import_dir()
    )
    if job is None:
        raise ApiError("导入任务不存在。", status=404, code="not_found")
    return job


def _selected_rows(value, rows):
    """校验可选的写入行号；None 表示全部可入库行。

    [] 表示用户一行都没选，返回空集合，绝不能退化成“写入全部”。
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ApiError("selected_rows 必须是数组。", code="invalid_param")
    known = {int(row.get("row_number") or 0) for row in rows}
    selected = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ApiError("selected_rows 只能包含行号整数。", code="invalid_param")
        number = item
        if number not in known:
            raise ApiError(f"selected_rows 包含不存在的行号：{number}。", code="invalid_param")
        if number not in selected:
            selected.append(number)
    if not selected:
        raise ApiError("没有选择任何可写入的行。", code="no_row_selected")
    return selected


def _save_summary(token, rows, columns, ai_enabled, ai_model):
    summary = import_engine.rebuild_summary(
        rows, columns, ai_enabled=ai_enabled, ai_model=ai_model
    )
    counts, entities = import_engine.count_status(rows)
    import_store.update_job(
        _db_path(), token,
        total_rows=len(rows),
        ready_rows=counts.get("ready", 0),
        warning_rows=counts.get("warning", 0),
        error_rows=counts.get("error", 0),
        duplicate_rows=counts.get("duplicate", 0),
        entity_counts=entities,
        summary=summary,
        ai_enabled=ai_enabled,
    )
    return summary


def _public_job(job):
    exclude = {"rows_file", "backup_path"}
    return {key: value for key, value in job.items() if key not in exclude}


def _rows_response(job, rows):
    limit = _page(request.args.get("limit", 120), 120)
    offset = _page(request.args.get("offset", 0), 0, maximum=200000)
    status = str(request.args.get("status") or "all").strip().lower()
    entity = str(request.args.get("entity") or "all").strip().lower()
    keyword = str(request.args.get("q") or "").strip().lower()
    filtered = []
    for row in rows:
        if status not in {"all", ""} and row.get("status") != status:
            continue
        if entity not in {"all", ""} and row.get("entity_type") != entity:
            continue
        if keyword:
            haystack = " ".join(str(value) for value in (row.get("clean") or {}).values()).lower()
            haystack += " " + " ".join(str(value) for value in (row.get("raw") or {}).values()).lower()
            if keyword not in haystack:
                continue
        filtered.append(row)
    total = len(filtered)
    page = filtered[offset:offset + limit]
    return {
        "job": _public_job(job),
        "total": total,
        "offset": offset,
        "limit": limit,
        "rows": page,
    }


@bp.get("/status")
def status():
    config = _config()
    return jsonify({
        "ok": True,
        "ai": import_ai.status(config),
        "limits": {
            "max_file_mb": import_engine.MAX_FILE_BYTES // (1024 * 1024),
            "max_rows": import_engine.MAX_ROWS,
            "max_ai_rows": import_ai.MAX_AI_ROWS,
        },
        "modes": sorted(MODES),
        "conflicts": sorted(CONFLICTS),
    })


@bp.post("/preview")
def preview():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError("请选择要上传的 CSV、JSON 或 XLSX 文件。", code="missing_file")
    filename = os.path.basename(upload.filename)
    mode = _mode(request.form.get("mode"))
    conflict = _conflict(request.form.get("conflict"))
    want_ai = _bool(request.form.get("ai"))
    limit = int(current_app.config.get("MAX_UPLOAD_BYTES", import_engine.MAX_FILE_BYTES))
    content = upload.read(limit + 1)
    if len(content) > limit:
        raise ApiError(
            f"文件超过 {import_engine.format_file_size(limit)} 限制，请拆分后导入。",
            code="file_too_large", status=413,
        )
    try:
        raw_rows, columns, notes = import_engine.parse_upload(
            filename, content, max_bytes=limit
        )
    except ValueError as exc:
        raise ApiError(str(exc), code="parse_error") from exc
    rows, summary = import_engine.analyse(
        _db_path(), raw_rows, mode=mode, filename=filename,
        ai_enabled=False, ai_model="",
        column_names=columns,
    )
    summary["notes"] = list(notes) + list(summary.get("notes") or [])
    ai_warning = ""
    ai_model = ""
    if want_ai:
        config = _config()
        ai_model = config.get("model") or ""
        try:
            result = import_ai.assist(rows, config)
            rows = import_engine.apply_ai_suggestions(
                _db_path(), rows, result.get("suggestions") or [], mode=mode
            )
            summary = import_engine.summarise(rows, columns, ai_enabled=True, ai_model=ai_model)
            summary["notes"] = list(notes) + list(summary.get("notes") or []) + list(result.get("notes") or [])
            if result.get("notes"):
                summary["ai_notes"] = result["notes"]
        except AIError as exc:
            ai_warning = exc.message
            summary["notes"] = list(notes) + list(summary.get("notes") or []) + [f"AI 辅助未启用：{exc.message}"]
    counts, entities = import_engine.count_status(rows)
    token, _file_path = import_store.create_job(
        _db_path(), _import_dir(),
        {
            "filename": filename,
            "file_size": len(content),
            "mode": mode,
            "conflict": conflict,
            "ai_enabled": bool(want_ai and not ai_warning),
            "ai_model": ai_model if want_ai and not ai_warning else "",
            "status": "preview",
            "total_rows": len(rows),
            "ready_rows": counts.get("ready", 0),
            "warning_rows": counts.get("warning", 0),
            "error_rows": counts.get("error", 0),
            "duplicate_rows": counts.get("duplicate", 0),
            "entity_counts": entities,
            "summary": summary,
            "columns": columns,
        },
        rows,
    )
    job = _job_or_404(token)
    return jsonify({
        "ok": True,
        "token": token,
        "job": _public_job(job),
        "summary": summary,
        "rows": rows[:120],
        "ai_warning": ai_warning,
    })


@bp.post("/ai")
def ai_review():
    payload = _json_body()
    token = _token(payload.get("token"))
    job = _job_or_404(token, include_rows=True)
    if job.get("status") not in {"preview", "reviewed"}:
        raise ApiError("该任务已经应用或正在刷新，不能再做 AI 复核。", status=409, code="already_applied")
    config = _config()
    mode = _mode(payload.get("mode") or job.get("mode") or "auto")
    try:
        result = import_ai.assist(job.get("rows") or [], config)
    except AIError as exc:
        raise ApiError(exc.message, status=exc.status, code=exc.code) from exc
    rows = import_engine.apply_ai_suggestions(
        _db_path(), job.get("rows") or [], result.get("suggestions") or [], mode=mode
    )
    import_store.save_rows(_import_dir(), token, rows)
    summary = _save_summary(token, rows, job.get("columns") or [],
                            True, config.get("model") or "")
    if result.get("notes"):
        summary["ai_notes"] = result["notes"]
        import_store.update_job(_db_path(), token, summary=summary)
    counts, entities = import_engine.count_status(rows)
    import_store.update_job(
        _db_path(), token,
        status="reviewed",
        ready_rows=counts.get("ready", 0),
        warning_rows=counts.get("warning", 0),
        error_rows=counts.get("error", 0),
        duplicate_rows=counts.get("duplicate", 0),
        entity_counts=entities,
        ai_model=config.get("model") or "",
    )
    job = _job_or_404(token)
    return jsonify({
        "ok": True,
        "job": _public_job(job),
        "summary": summary,
        "rows": rows[:120],
        "processed": result.get("processed", 0),
        "notes": result.get("notes") or [],
    })


def _start_pipeline(db_path, token, timeout=None):
    thread = threading.Thread(
        target=run_pipeline_job,
        args=(db_path, token, timeout),
        name=f"import-refresh-{token[:8]}",
        daemon=True,
    )
    thread.start()


def run_pipeline_job(db_path, token, timeout=None):
    steps = [{"name": name, "label": label, "status": "pending", "output": ""}
             for name, label in PIPELINE_STEPS]
    import_store.update_job(db_path, token, pipeline_status="running", pipeline_steps=steps)
    try:
        for index, (name, _label) in enumerate(PIPELINE_STEPS):
            steps[index]["status"] = "running"
            import_store.update_job(db_path, token, pipeline_steps=steps)
            output = _run_step(f"{name}.py", db_path, timeout=timeout)
            steps[index].update(status="done", output=output[-500:])
            import_store.update_job(db_path, token, pipeline_steps=steps)
        import_store.update_job(db_path, token, pipeline_status="done", pipeline_steps=steps)
    except Exception as exc:  # 后台刷新失败不应影响已入库的数据
        for step in steps:
            if step["status"] == "running":
                step["status"] = "failed"
                step["output"] = str(exc)[-500:]
        import_store.update_job(
            db_path, token, pipeline_status="failed", pipeline_steps=steps,
            error=str(exc)[:800],
        )


@bp.post("/apply")
def apply():
    payload = _json_body()
    token = _token(payload.get("token"))
    job = _job_or_404(token, include_rows=True)
    if job.get("status") in {"applied", "applying"}:
        raise ApiError("该导入任务已经应用，请勿重复提交。", status=409, code="already_applied")
    conflict = _conflict(payload.get("conflict") or job.get("conflict") or "skip")
    rows = job.get("rows") or []
    if not rows:
        raise ApiError("预览数据已丢失，请重新上传。", status=409, code="preview_missing")
    selected_rows = _selected_rows(payload.get("selected_rows"), rows)
    if not import_store.claim_apply(_db_path(), token):
        raise ApiError("该导入任务已经应用，请勿重复提交。", status=409, code="already_applied")
    try:
        backup = import_engine.backup_database(
            _db_path(), current_app.config["IMPORT_BACKUP_DIR"]
        )
    except Exception as exc:
        import_store.update_job(
            _db_path(), token, status="preview",
            error=f"备份失败：{str(exc)[:500]}",
        )
        raise ApiError("数据库备份失败，未写入任何数据。", status=500, code="backup_failed") from exc
    try:
        result = import_engine.apply_rows(
            _db_path(), rows, conflict=conflict, selected_rows=selected_rows,
        )
    except Exception as exc:
        import_store.update_job(
            _db_path(), token, status="preview",
            error=f"应用失败：{str(exc)[:500]}",
        )
        raise ApiError("应用失败，数据库已回滚。", status=500, code="apply_failed") from exc
    totals = result.get("totals") or {}
    changed = any(
        totals.get(f"{entity}_{action}")
        for entity in ("teachers", "papers", "courses")
        for action in ("inserted", "updated")
    )
    refresh = bool(_bool(payload.get("start_pipeline", True)) and changed)
    import_store.update_job(
        _db_path(), token,
        status="applied",
        applied_counts=totals,
        backup_path=backup,
        conflict=conflict,
        error="",
        pipeline_status="queued" if refresh else "idle",
    )
    if refresh:
        _start_pipeline(_db_path(), token, current_app.config.get("PIPELINE_TIMEOUT"))
    return jsonify({
        "ok": True,
        "token": token,
        "conflict": conflict,
        "totals": totals,
        "counts": result.get("counts") or {},
        "failures": result.get("failures") or [],
        "backup": os.path.basename(backup),
        "pipeline_status": "queued" if refresh else "idle",
    })


@bp.get("/jobs")
def jobs():
    limit = _page(request.args.get("limit", 20), 20, maximum=100) or 20
    return jsonify({"items": import_store.list_jobs(_db_path(), limit=limit)})


@bp.get("/jobs/<token>")
def job_detail(token):
    job = _job_or_404(_token(token), include_rows=True)
    return jsonify(_rows_response(job, job.get("rows") or []))


@bp.get("/jobs/<token>/export")
def export_job(token):
    job = _job_or_404(_token(token), include_rows=True)
    rows = job.get("rows") or []
    if not rows:
        raise ApiError("预览数据已丢失，无法导出。", status=404, code="preview_missing")
    columns = []
    for row in rows:
        for key in (row.get("clean") or {}):
            if not str(key).startswith("_") and key not in columns:
                columns.append(key)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["row_number", "entity_type", "status", "quality"] + columns + ["issues"])
    for row in rows:
        clean = row.get("clean") or {}
        issues = "；".join(
            f"{item.get('field', '')}: {item.get('message', '')}"
            for item in (row.get("issues") or [])
        )
        writer.writerow(
            [row.get("row_number"), row.get("entity_type"), row.get("status"),
             row.get("quality")] +
            [clean.get(column, "") for column in columns] + [issues]
        )
    body = "\ufeff" + output.getvalue()
    filename = f"import_{job.get('token')}_{job.get('mode')}.csv"
    return Response(
        body, mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.get("/template")
def template():
    entity = request.args.get("type", "teacher").strip().lower()
    if entity not in TEMPLATE_HEADERS:
        raise ApiError("模板类型只能是 teacher、paper、course。", code="invalid_param")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(TEMPLATE_HEADERS[entity])
    body = "\ufeff" + output.getvalue()
    return Response(
        body, mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="import_template_{entity}.csv"'
        },
    )
