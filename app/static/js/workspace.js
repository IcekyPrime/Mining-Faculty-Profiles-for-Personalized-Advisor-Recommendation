"use strict";

/* 数据工坊前端：上传 → 预览 → 可选 AI 复核 → 入库 → 处理层进度。
   只通过新增的 /api/import/* 接口工作，不触碰原有检索与档案逻辑。 */
const W = {
  file: null,
  token: null,
  job: null,
  summary: null,
  rows: [],
  rowTotal: 0,
  filterStatus: "all",
  query: "",
  status: null,
  pollTimer: null,
};

function t(key, vars) {
  return window.MentorI18n ? window.MentorI18n.t(key, vars) : key;
}

function el(id) {
  return document.getElementById(id);
}

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function setInline(message, kind) {
  const node = el("preview-status");
  node.textContent = message || "";
  node.className = "ws-inline-status" + (kind ? " " + kind : "");
}

async function api(url, options) {
  const response = await fetch(url, options || {});
  let data = null;
  try {
    data = await response.json();
  } catch (err) {
    data = null;
  }
  if (!response.ok) {
    const message = (data && data.error && data.error.message) || ("HTTP " + response.status);
    throw new Error(message);
  }
  return data || {};
}

function initTheme() {
  const forced = new URLSearchParams(window.location.search).get("theme");
  let theme = "";
  if (forced === "light" || forced === "dark") {
    theme = forced;
  } else {
    try {
      theme = localStorage.getItem("mentor-theme") || "";
    } catch (err) {
      theme = "";
    }
  }
  if (!theme) {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }
  applyTheme(theme);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const button = el("theme-toggle");
  button.textContent = theme === "dark" ? t("nav.theme.light") : t("nav.theme.dark");
  button.setAttribute("aria-label", theme === "dark" ? "切换到浅色模式" : "切换到深色模式");
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try {
    localStorage.setItem("mentor-theme", next);
  } catch (err) {
    /* 本地存储不可用时忽略 */
  }
}

function chooseFile(file) {
  if (!file) return;
  W.file = file;
  el("drop-title").textContent = file.name;
  el("file-meta").textContent = formatBytes(file.size) + " · " + (file.type || "未知类型");
  el("preview-btn").disabled = false;
  setInline("", "");
}

async function loadStatus() {
  try {
    const data = await api("/api/import/status");
    W.status = data;
    const ai = data.ai || {};
    if (ai.available) {
      el("ai-status").textContent = t("workspace.aiReady", { model: ai.model || "AI" })
        + (ai.local_endpoint ? " · " + t("workspace.aiLocal", { base: ai.api_base }) : "");
      el("ai-toggle").disabled = false;
    } else {
      el("ai-status").textContent = t("workspace.aiUnavailable");
      el("ai-toggle").disabled = true;
      el("ai-toggle").checked = false;
    }
  } catch (err) {
    el("ai-status").textContent = t("workspace.aiUnavailable");
  }
}

function jobFrom(data) {
  return data.job || data;
}

function syncJobUrl(token) {
  try {
    const url = new URL(window.location.href);
    if (token) url.searchParams.set("job", token);
    else url.searchParams.delete("job");
    window.history.replaceState({}, "", url.toString());
  } catch (err) {
    /* 老浏览器不支持 URL 时忽略 */
  }
}

function initialJobToken() {
  try {
    const token = new URLSearchParams(window.location.search).get("job") || "";
    return /^[a-f0-9]{16}$/.test(token) ? token : "";
  } catch (err) {
    return "";
  }
}

function showReport(job) {
  el("report-card").classList.remove("hidden");
  el("report-file").textContent = (job.filename || "") + " · " + formatBytes(job.file_size || 0);
  el("export-link").href = "/api/import/jobs/" + job.token + "/export";
  const statusNode = el("report-status");
  if (statusNode) {
    statusNode.textContent = statusLabel(job.status || "preview");
    statusNode.className = "ws-report-status " + (job.status || "preview");
  }
  renderSummary(job.summary || W.summary || {});
  renderPipeline(job);
  const locked = ["applied", "applying"].includes(job.status);
  el("apply-btn").disabled = locked;
  el("ai-review-btn").disabled = locked || !(W.status && W.status.ai && W.status.ai.available);
  el("preview-btn").disabled = false;
}

function metricHtml(label, value, note, cls) {
  return `<div class="ws-metric ${cls || ""}"><span>${esc(label)}</span>` +
    `<strong>${esc(value)}</strong><em>${esc(note || "")}</em></div>`;
}

function renderSummary(summary) {
  const counts = summary.entity_counts || {};
  const ready = Number(summary.ready_rows || 0);
  const warnings = Number(summary.warning_rows || 0);
  const metrics = [
    [t("workspace.total"), summary.total_rows || 0,
      t("workspace.metricEntities", { t: counts.teacher || 0, p: counts.paper || 0 }), "accent"],
    [t("workspace.ready"), ready + warnings,
      t("workspace.metricReadyNote", { ready, warning: warnings }), ""],
    [t("workspace.warning"), warnings, t("workspace.metricWarningNote"), "warn"],
    [t("workspace.error"), summary.error_rows || 0, t("workspace.metricErrorNote"), "danger"],
    [t("workspace.duplicate"), summary.duplicate_rows || 0,
      t("workspace.metricDuplicateNote"), ""],
    [t("workspace.quality"), summary.quality_score || 0, "0–100", "accent"],
  ];
  el("metrics").innerHTML = metrics.map(item => metricHtml(...item)).join("");

  const entityRows = [
    ["teacher", t("workspace.mode.teacher"), counts.teacher || 0],
    ["paper", t("workspace.mode.paper"), counts.paper || 0],
    ["course", t("workspace.mode.course"), counts.course || 0],
    ["unknown", "待识别", counts.unknown || 0],
  ];
  const total = Math.max(1, summary.total_rows || 0);
  el("entity-bars").innerHTML = entityRows.map(([key, label, value]) => {
    const pct = Math.round(value / total * 100);
    return `<div class="ws-bar-row"><label title="${esc(label)}">${esc(label)}</label>` +
      `<div class="ws-bar-track"><i class="ws-bar-fill" style="width:${pct}%"></i></div>` +
      `<b>${value}</b></div>`;
  }).join("");

  const missing = (summary.missing_top || []).slice(0, 6);
  el("missing-bars").innerHTML = missing.length ? missing.map(item =>
    `<div class="ws-bar-row"><label title="${esc(item.field)}">${esc(item.field)}</label>` +
    `<div class="ws-bar-track"><i class="ws-bar-fill" style="width:${Math.min(100, item.missing_rate)}%;` +
    `background:var(--gold)"></i></div><b>${item.missing_rate}%</b></div>`
  ).join("") : `<p class="ws-muted">—</p>`;

  const issues = Object.entries(summary.issue_counts || {}).slice(0, 7);
  el("issue-list").innerHTML = issues.length ? issues.map(([message, count]) =>
    `<li><span>${esc(message)}</span><b>${count}</b></li>`
  ).join("") : `<li><span class="ws-muted">没有明显质量问题。</span></li>`;
}

function statusLabel(status) {
  return t("workspace.status." + status) !== "workspace.status." + status
    ? t("workspace.status." + status) : status;
}

function rowStatusLabel(status) {
  const map = {
    ready: "workspace.filterReady",
    warning: "workspace.filterWarning",
    error: "workspace.filterError",
    duplicate: "workspace.filterDuplicate",
  };
  return t(map[status] || "workspace.filterAll");
}

function entityLabel(entity) {
  const map = {
    teacher: "workspace.mode.teacher",
    paper: "workspace.mode.paper",
    course: "workspace.mode.course",
    unknown: null,
  };
  return map[entity] ? t(map[entity]) : "?";
}

function rowMain(row) {
  const clean = row.clean || {};
  if (row.entity_type === "teacher") {
    return {
      title: clean.name || t("workspace.unnamedTeacher"),
      sub: [clean.college, clean.title, clean.research_directions].filter(Boolean).join(" · "),
    };
  }
  if (row.entity_type === "paper") {
    return {
      title: clean.paper_title || t("workspace.unnamedPaper"),
      sub: [clean.teacher_name, clean.venue, clean.year].filter(Boolean).join(" · "),
    };
  }
  if (row.entity_type === "course") {
    return {
      title: clean.course_name || t("workspace.unnamedCourse"),
      sub: [clean.teacher_name, clean.course_code, clean.last_semester].filter(Boolean).join(" · "),
    };
  }
  return { title: t("workspace.unknownRow"), sub: Object.values(row.raw || {}).slice(0, 3).join(" · ") };
}

function issueSummary(row) {
  const issues = row.issues || [];
  const important = issues.find(item => item.level === "error") || issues.find(item => item.level === "warning");
  return important ? important.message : "";
}

function renderRows() {
  const body = el("rows-body");
  const rows = W.rows || [];
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="ws-muted">${esc(t("workspace.noRows"))}</td></tr>`;
  } else {
    body.innerHTML = rows.map(row => {
      const main = rowMain(row);
      const quality = Number(row.quality || 0);
      return `<tr data-row="${row.row_number}">` +
        `<td class="ws-row-num">${row.row_number}</td>` +
        `<td><span class="ws-type ${esc(row.entity_type)}">${esc(entityLabel(row.entity_type))}</span></td>` +
        `<td><span class="ws-status ${esc(row.status)}">${esc(rowStatusLabel(row.status))}</span></td>` +
        `<td><div class="ws-main">${esc(main.title)}</div><div class="ws-sub">${esc(main.sub)}</div></td>` +
        `<td class="ws-quality-cell"><span>${quality}</span><div class="ws-mini-track">` +
        `<i style="width:${Math.max(0, Math.min(100, quality))}%"></i></div></td>` +
        `<td class="ws-issue-text">${esc(issueSummary(row))}</td></tr>`;
    }).join("");
  }
  const count = el("table-count");
  count.textContent = rows.length
    ? `${rows.length} / ${W.rowTotal || rows.length}`
    : "";
  body.querySelectorAll("tr[data-row]").forEach(tr => {
    tr.addEventListener("click", () => {
      const number = Number(tr.dataset.row);
      const row = (W.rows || []).find(item => Number(item.row_number) === number);
      if (row) openDrawer(row);
    });
  });
}

async function fetchRows() {
  if (!W.token) return;
  const params = new URLSearchParams({
    limit: "300",
    offset: "0",
    status: W.filterStatus,
    entity: "all",
    q: W.query,
  });
  const data = await api("/api/import/jobs/" + W.token + "?" + params.toString());
  W.job = jobFrom(data);
  W.rows = data.rows || [];
  W.rowTotal = data.total || W.rows.length;
  if (W.job.summary) W.summary = W.job.summary;
  renderRows();
  showReport(W.job);
}

async function preview() {
  if (!W.file) {
    setInline("请先选择文件。", "error");
    return;
  }
  const button = el("preview-btn");
  button.disabled = true;
  button.textContent = t("workspace.previewing");
  setInline(t("workspace.previewing"), "");
  const form = new FormData();
  form.append("file", W.file);
  form.append("mode", el("mode-select").value);
  form.append("conflict", el("conflict-select").value);
  form.append("ai", el("ai-toggle").checked ? "1" : "0");
  try {
    const data = await api("/api/import/preview", { method: "POST", body: form });
    W.token = data.token;
    W.job = jobFrom(data);
    W.summary = data.summary || W.job.summary || {};
    W.rows = data.rows || [];
    W.rowTotal = W.summary.total_rows || W.rows.length;
    syncJobUrl(W.token);
    showReport(W.job);
    renderRows();
    if (data.ai_warning) {
      setInline(data.ai_warning, "error");
    } else {
      setInline(t("workspace.previewReady"), "ok");
    }
    await fetchRows();
    await loadHistory();
  } catch (err) {
    setInline(t("workspace.loadFailed", { msg: err.message }), "error");
  } finally {
    button.disabled = false;
    button.textContent = t("workspace.preview");
  }
}

async function aiReview() {
  if (!W.token) return;
  const button = el("ai-review-btn");
  button.disabled = true;
  button.textContent = "AI 复核中…";
  try {
    const data = await api("/api/import/ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: W.token, mode: el("mode-select").value }),
    });
    W.job = jobFrom(data);
    W.summary = data.summary || W.job.summary || {};
    W.rows = data.rows || [];
    setInline(t("workspace.aiDone", { n: data.processed || 0 }), "ok");
    showReport(W.job);
    await fetchRows();
  } catch (err) {
    setInline(t("workspace.aiFailed", { msg: err.message }), "error");
  } finally {
    button.disabled = false;
    button.textContent = t("workspace.aiReview");
    showReport(W.job || {});
  }
}

async function applyRows() {
  if (!W.token || !W.job) return;
  const conflict = el("conflict-select").value;
  if (conflict !== "skip" && !window.confirm(t("workspace.confirmUpdate"))) return;
  if (!window.confirm(t("workspace.confirmApply"))) return;
  const button = el("apply-btn");
  button.disabled = true;
  button.textContent = t("workspace.writing");
  setInline(t("workspace.backingUp"), "");
  try {
    const data = await api("/api/import/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: W.token,
        conflict,
        start_pipeline: el("refresh-toggle").checked,
      }),
    });
    const totals = data.totals || {};
    setInline(t("workspace.applyDone", {
      t: (totals.teachers_inserted || 0) + (totals.teachers_updated || 0),
      p: (totals.papers_inserted || 0) + (totals.papers_updated || 0),
      c: (totals.courses_inserted || 0) + (totals.courses_updated || 0),
    }), "ok");
    if (data.failures && data.failures.length) {
      setInline((data.failures[0].message || "") + " · 其它失败行见接口返回。", "error");
    }
    W.job = Object.assign({}, W.job, {
      status: "applied",
      applied_counts: totals,
      pipeline_status: data.pipeline_status || "idle",
    });
    showReport(W.job);
    startPolling();
    await loadHistory();
  } catch (err) {
    setInline(t("workspace.applyFailed", { msg: err.message }), "error");
  } finally {
    button.disabled = false;
    button.textContent = t("workspace.apply");
  }
}

function renderPipeline(job) {
  const box = el("pipeline-box");
  const status = job.pipeline_status || "idle";
  if (status === "idle" && !(job.pipeline_steps || []).length) {
    box.className = "ws-pipeline hidden";
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  const steps = job.pipeline_steps || [];
  const headline = status === "done" ? t("workspace.pipelineDone")
    : status === "failed" ? t("workspace.pipelineFailed")
    : status === "running" ? "处理层刷新中…" : "等待后台刷新…";
  box.innerHTML = `<div class="ws-muted">${esc(t("workspace.pipeline"))} · ${esc(headline)}</div>` +
    (job.error ? `<p class="ws-inline-status error">${esc(job.error)}</p>` : "") +
    steps.map(step => `<div class="ws-pipeline-step ${esc(step.status)}">` +
      `<span>${esc(step.label || step.name)}</span></div>`).join("");
}

function startPolling() {
  stopPolling();
  let ticks = 0;
  W.pollTimer = window.setInterval(async () => {
    ticks += 1;
    if (ticks > 120) {
      stopPolling();
      return;
    }
    try {
      const data = await api("/api/import/jobs/" + W.token + "?limit=1&status=all");
      W.job = jobFrom(data);
      renderPipeline(W.job);
      if (["done", "failed"].includes(W.job.pipeline_status)) {
        stopPolling();
        await loadHistory();
      }
    } catch (err) {
      /* 轮询失败不打扰用户，下一轮再试 */
    }
  }, 3000);
}

function stopPolling() {
  if (W.pollTimer) {
    window.clearInterval(W.pollTimer);
    W.pollTimer = null;
  }
}

function historyStatus(status) {
  const key = "workspace.status." + status;
  return t(key) !== key ? t(key) : status;
}

async function loadHistory() {
  try {
    const data = await api("/api/import/jobs?limit=12");
    const items = data.items || [];
    const box = el("history-list");
    if (!items.length) {
      box.innerHTML = `<p class="ws-muted">${esc(t("workspace.historyEmpty"))}</p>`;
      return;
    }
    box.innerHTML = items.map(item => {
      const totals = item.applied_counts || {};
      const inserted = (totals.teachers_inserted || 0) + (totals.papers_inserted || 0) +
        (totals.courses_inserted || 0);
      return `<div class="ws-history-row" data-token="${esc(item.token)}">` +
        `<div><div class="ws-history-file">${esc(item.filename)}</div>` +
        `<small>${esc(item.mode)} · ${esc(item.ai_enabled ? "AI" : t("workspace.ruleShort"))}</small></div>` +
        `<div><small>${esc(t("workspace.historyStatus"))}</small><br>${esc(historyStatus(item.status))}</div>` +
        `<div><small>${esc(t("workspace.historyRows"))}</small><br>${item.total_rows || 0}</div>` +
        `<div class="history-result"><small>${esc(t("workspace.historyResult"))}</small><br>` +
        `${inserted ? "+" + inserted : (totals.failed ? "失败 " + totals.failed : "—")}</div>` +
        `<div class="history-time"><small>${esc(t("workspace.historyTime"))}</small><br>` +
        `${esc(item.created_at || "")}</div></div>`;
    }).join("");
    box.querySelectorAll(".ws-history-row").forEach(row => {
      row.addEventListener("click", () => openJob(row.dataset.token));
    });
  } catch (err) {
    /* 历史加载失败不影响当前导入 */
  }
}

async function openJob(token) {
  try {
    const data = await api("/api/import/jobs/" + token + "?limit=300&status=all");
    W.token = token;
    W.job = jobFrom(data);
    W.summary = W.job.summary || {};
    W.rows = data.rows || [];
    W.rowTotal = data.total || W.rows.length;
    syncJobUrl(token);
    el("mode-select").value = W.job.mode || "auto";
    el("conflict-select").value = W.job.conflict || "skip";
    showReport(W.job);
    renderRows();
    if (W.job.pipeline_status === "running" || W.job.pipeline_status === "queued") {
      startPolling();
    }
    window.scrollTo({ top: el("report-card").offsetTop - 80, behavior: "smooth" });
  } catch (err) {
    syncJobUrl("");
    setInline(t("workspace.loadFailed", { msg: err.message }), "error");
  }
}

function kvTable(data, entity) {
  const entries = Object.entries(data || {}).filter(([key]) => !String(key).startsWith("_"));
  if (!entries.length) return `<p class="ws-muted">—</p>`;
  return `<div class="ws-kv">` + entries.map(([key, value]) => {
    const shown = value === null || value === undefined || value === "" ? "—" : String(value);
    return `<div class="k">${esc(key)}</div><div class="v ${shown === "—" ? "is-empty" : ""}">${esc(shown)}</div>`;
  }).join("") + `</div>`;
}

function openDrawer(row) {
  const main = rowMain(row);
  const issues = row.issues || [];
  const changes = row.changes || [];
  const duplicate = row.duplicate;
  el("drawer-title").textContent = t("workspace.detailTitle") + " · " + row.row_number;
  el("drawer-content").innerHTML =
    `<div class="ws-drawer-section"><h3>${esc(t("workspace.content"))}</h3>` +
    `<p class="ws-main">${esc(main.title)}</p><p class="ws-sub">${esc(main.sub)}</p>` +
    `<div class="ws-issue-pill ${esc(row.status)}">${esc(rowStatusLabel(row.status))} · ${esc(row.quality || 0)}</div>` +
    (duplicate ? `<div class="ws-issue-pill warning">重复：${esc(duplicate.message || ("ID " + duplicate.id))}</div>` : "") +
    `</div>` +
    `<div class="ws-drawer-section"><h3>${esc(t("workspace.rowIssues"))}</h3>` +
    (issues.length ? issues.map(item =>
      `<div class="ws-issue-pill ${esc(item.level)}">${esc(item.field)} · ${esc(item.message)}</div>`
    ).join("") : `<p class="ws-muted">—</p>`) + `</div>` +
    `<div class="ws-drawer-section"><h3>${esc(t("workspace.clean"))}</h3>` +
    kvTable(row.clean || {}, row.entity_type) + `</div>` +
    `<div class="ws-drawer-section"><h3>${esc(t("workspace.raw"))}</h3>` +
    kvTable(row.raw || {}, row.entity_type) + `</div>` +
    `<div class="ws-drawer-section"><h3>${esc(t("workspace.changes"))}</h3>` +
    (changes.length ? changes.map(change =>
      `<div class="ws-change"><b>${esc(change.field)}</b><span class="before">${esc(change.before)}</span>` +
      `<span class="after">${esc(change.after)}</span></div>`
    ).join("") : `<p class="ws-muted">${esc(t("workspace.noChanges"))}</p>`) + `</div>`;
  el("row-drawer").classList.remove("hidden");
}

function closeDrawer() {
  el("row-drawer").classList.add("hidden");
}

function bind() {
  const input = el("file-input");
  const drop = el("drop-zone");
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => chooseFile(input.files[0]));
  ["dragenter", "dragover"].forEach(name => {
    drop.addEventListener(name, event => {
      event.preventDefault();
      drop.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(name => {
    drop.addEventListener(name, event => {
      event.preventDefault();
      drop.classList.remove("dragover");
    });
  });
  drop.addEventListener("drop", event => {
    const file = event.dataTransfer.files && event.dataTransfer.files[0];
    chooseFile(file);
  });

  el("preview-btn").addEventListener("click", preview);
  el("ai-review-btn").addEventListener("click", aiReview);
  el("apply-btn").addEventListener("click", applyRows);
  el("theme-toggle").addEventListener("click", toggleTheme);
  el("row-filter").addEventListener("click", event => {
    const button = event.target.closest("[data-status]");
    if (!button) return;
    el("row-filter").querySelectorAll("button").forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    W.filterStatus = button.dataset.status;
    fetchRows();
  });
  let searchTimer = null;
  el("row-search").addEventListener("input", event => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      W.query = event.target.value.trim();
      fetchRows();
    }, 260);
  });
  el("row-drawer").addEventListener("click", event => {
    if (event.target.closest("[data-close-drawer]")) closeDrawer();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeDrawer();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  bind();
  loadStatus();
  loadHistory();
  const token = initialJobToken();
  if (token) openJob(token);
});
