/* 页面分区切换：AI 查询 / 导师名录 / 数据概况
 * 只控制已有区块的显示与隐藏，不改动 app.js 的检索与档案逻辑。
 * 项目说明不再占一级分区，移到「设置」抽屉里（由 app-shell.js 负责）。
 */
(function () {
  "use strict";

  const tabs = Array.from(document.querySelectorAll(".view-tab"));
  if (!tabs.length) return;

  const panes = {
    search: function () { return Array.from(document.querySelectorAll('[data-pane="search"]')); },
    directory: function () { return Array.from(document.querySelectorAll('[data-pane="directory"]')); },
    insights: function () { return [document.getElementById("pane-insights")]; },
  };

  const state = { current: "search" };

  function nodesFor(name) {
    const factory = panes[name];
    if (!factory) return [];
    return factory().filter(Boolean);
  }

  function setHidden(name, hidden) {
    nodesFor(name).forEach(function (node) {
      node.classList.toggle("hidden", hidden);
    });
  }

  function syncUrl(name) {
    // 用 ?view= 记录分区，便于刷新后停留在同一页；不占用档案页使用的 hash
    try {
      const url = new URL(window.location.href);
      if (name === "search") url.searchParams.delete("view");
      else url.searchParams.set("view", name);
      const next = url.pathname + (url.search || "");
      if (next !== window.location.pathname + window.location.search) {
        history.replaceState(history.state, "", next);
      }
    } catch (err) { /* 忽略 */ }
  }

  function exitDetail() {
    const detail = document.getElementById("view-detail");
    if (!detail || detail.classList.contains("hidden")) return;
    const back = document.getElementById("back-btn");
    if (back) back.click();
    else detail.classList.add("hidden");
    // 从 ?teacher=401 进来时，退出详情要把 teacher 参数清掉，否则刷新又回到档案页
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.has("teacher")) {
        url.searchParams.delete("teacher");
        history.replaceState({}, "", url.pathname + (url.search || ""));
      }
    } catch (err) { /* 忽略 */ }
  }

  function activate(name, options) {
    if (!panes[name]) return;
    if (!(options && options.fromInit)) exitDetail();
    state.current = name;
    tabs.forEach(function (tab) {
      const active = tab.dataset.view === name;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    Object.keys(panes).forEach(function (key) {
      setHidden(key, key !== name);
    });
    if (window.MentorApp && window.MentorApp.syncSortForView) {
      window.MentorApp.syncSortForView(name);
    }
    if (!(options && options.fromInit)) syncUrl(name);
    if (name === "insights" && window.MentorInsights) {
      window.MentorInsights.render();
    }
    if (!options || !options.keepScroll) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      activate(tab.dataset.view);
    });
  });

  // 键盘左右切换，符合 tablist 的可访问性约定
  document.getElementById("view-tabs").addEventListener("keydown", function (event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const index = tabs.findIndex(function (tab) { return tab.dataset.view === state.current; });
    const next = (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].focus();
    activate(tabs[next].dataset.view);
    event.preventDefault();
  });

  const initial = new URLSearchParams(window.location.search).get("view");
  activate(panes[initial] ? initial : "search", { keepScroll: true, fromInit: true });

  // 顶栏「导师名录」锚点改为切到名录分区
  document.querySelectorAll('.topnav a[href="#results"]').forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      activate("directory");
    });
  });

  window.MentorTabs = {
    activate: activate,
    current: function () { return state.current; },
  };
})();
