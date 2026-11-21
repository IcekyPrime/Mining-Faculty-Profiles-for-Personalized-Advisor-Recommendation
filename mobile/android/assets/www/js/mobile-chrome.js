/* 移动端外壳：同步状态栏 / 导航栏颜色，并提供系统返回键处理。 */
(function () {
  "use strict";

  function syncChrome() {
    var dark = document.documentElement.dataset.theme === "dark";
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark ? "#101613" : "#f6f2e9");
    if (window.AndroidChrome && window.AndroidChrome.setTheme) {
      window.AndroidChrome.setTheme(dark ? "dark" : "light");
    }
  }

  /* 若 WebView 的 localStorage 不可用，用原生保存的主题兜底。 */
  if (window.AndroidChrome && window.AndroidChrome.getTheme && typeof applyTheme === "function") {
    var nativeTheme = window.AndroidChrome.getTheme();
    if ((nativeTheme === "dark" || nativeTheme === "light")
        && document.documentElement.dataset.theme !== nativeTheme) {
      applyTheme(nativeTheme);
    }
  }

  new MutationObserver(syncChrome).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"]
  });
  document.addEventListener("DOMContentLoaded", syncChrome);
  syncChrome();

  /* Android 返回键：AI 抽屉 -> 收起；详情 -> 列表；设置 -> 关闭；概况/名录 -> 查询。 */
  window.mobileBack = function () {
    if (window.MobileAI && MobileAI.isOpen && MobileAI.isOpen()) {
      MobileAI.close();
      return true;
    }
    var detail = document.getElementById("view-detail");
    if (detail && !detail.classList.contains("hidden")) {
      backToList();
      return true;
    }
    var drawer = document.getElementById("settings-drawer");
    if (drawer && !drawer.classList.contains("hidden")) {
      var close = document.getElementById("settings-close");
      if (close) close.click();
      return true;
    }
    if (state && state.view !== "search") {
      setView("search");
      return true;
    }
    return false;
  };
})();
