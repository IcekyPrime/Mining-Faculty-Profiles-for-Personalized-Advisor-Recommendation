/* 查询页 AI 卡：调用 /api/ai/search，把结果交给 app.js 的统一卡片渲染。 */
(function () {
  "use strict";

  const input = document.getElementById("ai-query-input");
  const button = document.getElementById("ai-query-btn");
  const status = document.getElementById("ai-query-status");
  const hint = document.getElementById("ai-query-hint");
  if (!input || !button) return;

  function tr(key, vars) {
    return window.MentorI18n ? window.MentorI18n.t(key, vars) : key;
  }

  function setStatus(message, type) {
    if (!status) return;
    status.textContent = message || "";
    status.classList.toggle("is-error", type === "error");
    status.classList.toggle("is-ok", type === "ok");
    status.classList.toggle("is-busy", type === "busy");
  }

  async function readJSON(url, options) {
    const response = await fetch(url, options);
    let payload = null;
    try { payload = await response.json(); } catch (err) { payload = null; }
    if (!response.ok) {
      const error = payload && payload.error ? payload.error : {};
      const message = error.message || `请求失败（${response.status}）`;
      const wrapped = new Error(message);
      wrapped.code = error.code || "";
      throw wrapped;
    }
    return payload;
  }

  function openSettings(message) {
    setStatus(message, "error");
    if (window.MentorSettings) window.MentorSettings.open();
    const base = document.getElementById("ai-api-base");
    if (base) base.focus();
  }

  async function refreshHint() {
    try {
      const config = await readJSON("/api/ai/config");
      if (!hint) return;
      if (config.configured && config.enabled) {
        hint.textContent = tr("ai.hintConfigured", { model: config.model, count: 773 });
      } else if (config.configured) {
        hint.textContent = tr("ai.hintDisabled");
      } else {
        hint.textContent = tr("ai.hintNoConfig");
      }
    } catch (err) {
      if (hint) hint.textContent = tr("ai.hintLoadFailed");
    }
  }

  async function run() {
    const query = input.value.trim();
    if (!query) {
      setStatus(tr("ai.empty"), "error");
      input.focus();
      return;
    }
    button.disabled = true;
    setStatus(tr("ai.busy"), "busy");
    try {
      const config = await readJSON("/api/ai/config");
      if (!config.configured || !config.enabled) {
        openSettings(tr("ai.configRequired"));
        return;
      }
      const activeSort = document.querySelector("#sort-group .sort-btn.active");
      const payload = {
        q: query,
        sort: activeSort ? activeSort.dataset.sort : "score",
        page: 1,
        size: 20,
      };
      const data = await readJSON("/api/ai/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!window.MentorAIResults) throw new Error(tr("ai.resultsMissing"));
      window.MentorAIResults.render(data);
      if (window.MentorTabs) window.MentorTabs.activate("directory");
      const keywords = data.ai && data.ai.keywords ? data.ai.keywords.join(" / ") : query;
      setStatus(tr("ai.done", { keywords }), "ok");
      const results = document.getElementById("results");
      if (results) results.scrollIntoView({ behavior: "smooth", block: "start" });
      refreshHint();
    } catch (err) {
      if (err.code === "ai_not_configured" || err.code === "search_not_configured") {
        openSettings(err.message);
      } else {
        setStatus(err.message || tr("ai.failed"), "error");
      }
    } finally {
      button.disabled = false;
    }
  }

  button.addEventListener("click", run);
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      run();
    }
  });
  input.addEventListener("input", function () {
    if (status && status.classList.contains("is-error")) setStatus("");
  });

  window.MentorAISearch = { run: run, refreshHint: refreshHint };
  refreshHint();
})();
