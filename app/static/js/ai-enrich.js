/* 档案页联网补全：预览 → 勾选 → 写入 → 后台重跑处理层。 */
(function () {
  "use strict";

  const modal = document.getElementById("ai-enrich-modal");
  const backdrop = document.getElementById("ai-enrich-backdrop");
  const body = document.getElementById("ai-enrich-body");
  const note = document.getElementById("ai-enrich-note");
  const applyBtn = document.getElementById("ai-enrich-apply");
  const cancelBtn = document.getElementById("ai-enrich-cancel");
  const closeBtn = document.getElementById("ai-enrich-close");
  const status = document.getElementById("ai-enrich-status");
  if (!modal || !body) return;

  let current = null;
  let token = null;
  let pollTimer = null;
  let lastFocus = null;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char]));
  }

  function setStatus(message, type) {
    if (!status) return;
    status.textContent = message || "";
    status.classList.toggle("is-error", type === "error");
    status.classList.toggle("is-ok", type === "ok");
  }

  function setOpen(open) {
    if (open) {
      lastFocus = document.activeElement;
      modal.classList.remove("hidden");
      backdrop.classList.remove("hidden");
      document.body.classList.add("settings-open");
      if (closeBtn) closeBtn.focus();
    } else {
      modal.classList.add("hidden");
      backdrop.classList.add("hidden");
      document.body.classList.remove("settings-open");
      stopPolling();
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  async function readJSON(url, options) {
    const response = await fetch(url, options);
    let payload = null;
    try { payload = await response.json(); } catch (err) { payload = null; }
    if (!response.ok) {
      const error = payload && payload.error ? payload.error : {};
      const wrapped = new Error(error.message || `请求失败（${response.status}）`);
      wrapped.code = error.code || "";
      throw wrapped;
    }
    return payload;
  }

  function openSettings(message) {
    setStatus(message, "error");
    if (window.MentorSettings) window.MentorSettings.open();
  }

  function renderPreview(data) {
    const diff = data.diff || [];
    const sources = data.sources || [];
    if (!diff.length) {
      body.innerHTML = `
        <div class="ai-enrich-intro">
          <span class="ai-mark">AI</span>
          <span>${esc(data.notes || "没有发现可补全的新字段。")}</span>
        </div>
        ${sourceHtml(sources)}`;
      if (applyBtn) applyBtn.disabled = true;
      setStatus("没有可写入的新字段。", "ok");
      return;
    }
    body.innerHTML = `
      <div class="ai-enrich-intro">
        <span class="ai-mark">AI</span>
        <span>找到 <b>${diff.length}</b> 个可更新字段；整体置信度 ${esc(data.confidence || 0)}%</span>
        <span class="ai-enrich-query">检索：${esc(data.query || "")}</span>
      </div>
      <div class="ai-diff-list">
        ${diff.map((item, index) => diffRow(item, index)).join("")}
      </div>
      ${data.notes ? `<p class="ai-summary-note">${esc(data.notes)}</p>` : ""}
      ${sourceHtml(sources)}`;
    body.querySelectorAll(".ai-diff-check").forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        const row = checkbox.closest(".ai-diff-row");
        if (row) row.classList.toggle("is-selected", checkbox.checked);
        if (applyBtn) applyBtn.disabled = !body.querySelectorAll(".ai-diff-check:checked").length;
      });
    });
    if (applyBtn) applyBtn.disabled = !body.querySelectorAll(".ai-diff-check:checked").length;
    setStatus("请勾选要写入的字段；默认只勾选原来为空的字段。", "");
  }

  function diffRow(item, index) {
    const id = `ai-diff-${index}`;
    const selected = item.selected_default ? "checked" : "";
    return `
      <div class="ai-diff-row ${selected ? "is-selected" : ""}">
        <input class="ai-diff-check" id="${id}" type="checkbox" data-field="${esc(item.field)}" ${selected}>
        <label class="ai-diff-label" for="${id}">
          <strong>${esc(item.label)}</strong>
          <span class="ai-diff-conf">置信度 ${esc(item.confidence || 0)}%</span>
        </label>
        <div class="ai-diff-values">
          <div class="ai-diff-value is-old"><span>当前</span><span>${esc(item.current || "（空）")}</span></div>
          <div class="ai-diff-value is-new"><span>建议</span><span>${esc(item.proposed)}</span></div>
          ${item.current ? '<div class="ai-diff-source">已有值，勾选后才会覆盖</div>' : ""}
          ${item.source ? `<div class="ai-diff-source">来源：<a href="${esc(item.source)}" target="_blank" rel="noopener">${esc(item.source)}</a></div>` : ""}
        </div>
      </div>`;
  }

  function sourceHtml(sources) {
    if (!sources || !sources.length) return "";
    const links = sources.slice(0, 6).map((item) => {
      const url = String(item.url || "");
      if (!/^https?:\/\//i.test(url)) return "";
      return `<li><a href="${esc(url)}" target="_blank" rel="noopener">${esc(item.title || url)}</a></li>`;
    }).filter(Boolean).join("");
    return links ? `<div class="ai-pipeline"><div class="ai-pipeline-title">本次参考的公开网页</div><ul class="ai-source-list">${links}</ul></div>` : "";
  }

  async function openPreview() {
    if (!current) return;
    setOpen(true);
    body.innerHTML = '<div class="skeleton-card" style="height:170px"></div>';
    if (applyBtn) applyBtn.disabled = true;
    setStatus("正在联网搜索并抽取公开信息…");
    try {
      const data = await readJSON("/api/ai/enrich/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ teacher_id: current.id }),
      });
      token = data.token || null;
      renderPreview(data);
    } catch (err) {
      if (err.code === "ai_not_configured" || err.code === "search_not_configured") {
        openSettings(err.message);
      } else {
        body.innerHTML = `<div class="ai-enrich-intro"><span class="ai-mark">AI</span><span>${esc(err.message || "联网补全失败")}</span></div>`;
        setStatus(err.message || "联网补全失败", "error");
      }
    }
  }

  async function apply() {
    if (!token || !applyBtn) return;
    const fields = Array.from(body.querySelectorAll(".ai-diff-check:checked"))
      .map((checkbox) => checkbox.dataset.field);
    if (!fields.length) {
      setStatus("请至少勾选一个字段。", "error");
      return;
    }
    applyBtn.disabled = true;
    setStatus("正在备份数据库并写入选中字段…", "busy");
    try {
      const result = await readJSON("/api/ai/enrich/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token, fields: fields }),
      });
      setStatus(`已写入 ${fields.length} 个字段，处理层开始重跑…`, "ok");
      if (note) note.textContent = `数据库已备份为 ${result.backup || "backup"}；正在重跑关键词、相似、聚类与评分。`;
      pollJob(token);
    } catch (err) {
      applyBtn.disabled = false;
      setStatus(err.message || "写入失败", "error");
    }
  }

  async function pollJob(jobToken) {
    stopPolling();
    try {
      const job = await readJSON(`/api/ai/jobs/${encodeURIComponent(jobToken)}`);
      renderPipeline(job);
      if (job.status === "done") {
        setStatus("处理层刷新完成，正在刷新档案…", "ok");
        window.setTimeout(() => {
          setOpen(false);
          if (window.MentorApp && current) window.MentorApp.openDetail(current.id);
        }, 900);
        return;
      }
      if (job.status === "failed") {
        setStatus(job.error || "处理层刷新失败；字段已写入，可重跑 processing/refresh.py。", "error");
        return;
      }
      pollTimer = window.setTimeout(() => pollJob(jobToken), 1400);
    } catch (err) {
      setStatus(err.message || "读取任务状态失败", "error");
      pollTimer = window.setTimeout(() => pollJob(jobToken), 2000);
    }
  }

  function renderPipeline(job) {
    const steps = job.pipeline_steps || [];
    if (!steps.length) {
      if (note) note.textContent = "字段已写入，等待后台处理任务启动…";
      return;
    }
    if (note) note.textContent = "处理层按依赖顺序重跑；完成后会自动刷新档案。";
    const list = steps.map((step) => `
      <div class="ai-pipeline-step is-${esc(step.status || "pending")}">
        <span class="dot"></span><span>${esc(step.label || step.name)}</span>
        <span>${step.status === "done" ? "完成" : step.status === "running" ? "运行中" : step.status === "failed" ? "失败" : "等待"}</span>
      </div>`).join("");
    const node = body.querySelector("#ai-pipeline-status") || document.createElement("div");
    node.id = "ai-pipeline-status";
    node.className = "ai-pipeline";
    node.innerHTML = `<div class="ai-pipeline-title">处理层刷新 · ${esc(job.pipeline_status || "running")}</div><div class="ai-pipeline-steps">${list}</div>`;
    body.appendChild(node);
  }

  function mount(teacher, button) {
    current = teacher;
    if (!button) return;
    button.addEventListener("click", openPreview);
  }

  if (backdrop) backdrop.addEventListener("click", () => setOpen(false));
  if (cancelBtn) cancelBtn.addEventListener("click", () => setOpen(false));
  if (closeBtn) closeBtn.addEventListener("click", () => setOpen(false));
  if (applyBtn) applyBtn.addEventListener("click", apply);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.classList.contains("hidden")) setOpen(false);
  });

  window.MentorAIEnrich = { mount: mount };
})();
