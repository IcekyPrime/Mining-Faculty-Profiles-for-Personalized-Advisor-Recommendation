/* 检索进度条：拦截 /api/search 请求，在搜索面板下方显示分阶段进度。
 * 不修改 app.js，仅通过包装 window.fetch 观察请求的开始与结束。
 */
(function () {
  "use strict";

  const box = document.getElementById("search-progress");
  if (!box || typeof window.fetch !== "function") return;

  const label = document.getElementById("sp-label");
  const pctNode = document.getElementById("sp-pct");
  const bar = document.getElementById("sp-bar");
  const steps = Array.from(box.querySelectorAll(".sp-steps li"));

  const STAGES = [
    { at: 0, text: "解析检索条件" },
    { at: 26, text: "匹配姓名与关键词" },
    { at: 58, text: "按评分与相关度排序" },
    { at: 82, text: "生成结果列表" },
  ];

  const state = { active: false, progress: 0, timer: null, startedAt: 0, finished: false, gen: 0 };
  let userTriggered = false;

  // 只有用户主动搜索 / 切筛选时才显示，避免首屏自动加载就闪一条进度条
  document.addEventListener("submit", function (event) {
    if (event.target && event.target.id === "search-form") userTriggered = true;
  }, true);
  document.addEventListener("input", function (event) {
    // 打字时 app.js 的自动检索不弹进度条，真正提交时再显示
    if (event.target && event.target.id === "search-input") userTriggered = false;
  }, true);
  document.addEventListener("click", function (event) {
    const node = event.target && event.target.closest ? event.target.closest("#college-pills, #sort-group") : null;
    if (node) userTriggered = true;
  }, true);

  function paint(value) {
    state.progress = Math.max(0, Math.min(100, value));
    if (bar) bar.style.width = state.progress + "%";
    if (pctNode) pctNode.textContent = Math.round(state.progress) + "%";
    if (label) {
      let text = STAGES[0].text;
      STAGES.forEach(function (stage) {
        if (state.progress >= stage.at) text = stage.text;
      });
      label.textContent = state.finished ? "检索完成" : text;
    }
    steps.forEach(function (node, index) {
      const stage = STAGES[index];
      const next = STAGES[index + 1];
      node.classList.toggle("on", !state.finished && state.progress >= stage.at &&
        (!next || state.progress < next.at));
      node.classList.toggle("done", state.finished || (next && state.progress >= next.at));
    });
  }

  function start() {
    window.clearInterval(state.timer);
    state.gen += 1;
    const gen = state.gen;
    state.active = true;
    state.finished = false;
    state.startedAt = Date.now();
    box.classList.remove("hidden");
    paint(4);
    // 响应通常几十毫秒返回，进度先走到 88%，结束时再补满
    state.timer = window.setInterval(function () {
      if (state.gen !== gen) return;
      if (state.progress >= 88) return;
      paint(state.progress + Math.max(1, (88 - state.progress) * 0.08));
    }, 110);
    return gen;
  }

  function finish(gen) {
    if (!state.active || state.gen !== gen) return;
    window.clearInterval(state.timer);
    state.finished = true;
    paint(100);
    const elapsed = Date.now() - state.startedAt;
    const wait = Math.max(220, 900 - elapsed);
    window.setTimeout(function () {
      if (state.gen !== gen) return;
      state.active = false;
      box.classList.add("hidden");
      paint(0);
    }, wait);
  }

  function abort(gen) {
    if (state.gen !== gen) return;
    window.clearInterval(state.timer);
    state.active = false;
    box.classList.add("hidden");
  }

  const realFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const isSearch = url.indexOf("/api/search") !== -1
      && url.indexOf("mode=suggest") === -1
      && url.indexOf("mode=command") === -1;
    let page = null;
    try { page = new URL(url, window.location.href).searchParams.get("page"); } catch (err) { /* 忽略 */ }
    const isFirstPage = isSearch && (page === null || page === "1");
    if (!isFirstPage || !userTriggered) return realFetch.apply(this, arguments);
    const gen = start();
    return realFetch.apply(this, arguments).then(function (response) {
      finish(gen);
      return response;
    }, function (error) {
      abort(gen);
      throw error;
    });
  };
})();
