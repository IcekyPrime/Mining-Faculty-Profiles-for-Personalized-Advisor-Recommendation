/* 应用外壳：设置抽屉、主题选择、常用检索 chips、检索后自动进入名录。
 * 只新增行为，不修改 app.js 的检索逻辑。
 */
(function () {
  "use strict";

  const drawer = document.getElementById("settings-drawer");
  const backdrop = document.getElementById("settings-backdrop");
  const openBtn = document.getElementById("settings-btn");
  const closeBtn = document.getElementById("settings-close");
  const themeChoices = Array.from(document.querySelectorAll("[data-theme-choice]"));
  let lastFocus = null;

  function currentTheme() {
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  }

  function syncTheme() {
    const theme = currentTheme();
    themeChoices.forEach(function (btn) {
      const active = btn.dataset.themeChoice === theme;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function openSettings() {
    if (!drawer || !backdrop) return;
    lastFocus = document.activeElement;
    drawer.classList.remove("hidden");
    backdrop.classList.remove("hidden");
    document.body.classList.add("settings-open");
    syncTheme();
    if (closeBtn) closeBtn.focus();
  }

  function closeSettings() {
    if (!drawer || !backdrop) return;
    drawer.classList.add("hidden");
    backdrop.classList.add("hidden");
    document.body.classList.remove("settings-open");
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  if (openBtn) openBtn.addEventListener("click", openSettings);
  if (closeBtn) closeBtn.addEventListener("click", closeSettings);
  if (backdrop) backdrop.addEventListener("click", closeSettings);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && drawer && !drawer.classList.contains("hidden")) {
      closeSettings();
    }
  });

  themeChoices.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const want = btn.dataset.themeChoice;
      if (want && want !== currentTheme()) {
        const toggle = document.getElementById("theme-toggle");
        if (toggle) toggle.click();
      }
      syncTheme();
    });
  });

  // 顶栏的快捷切换按钮也会改主题，打开抽屉前保持联动
  const topToggle = document.getElementById("theme-toggle");
  if (topToggle) {
    topToggle.addEventListener("click", function () {
      window.setTimeout(syncTheme, 0);
    });
  }

  // 常用检索：填入输入框并提交
  document.querySelectorAll(".query-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      const input = document.getElementById("search-input");
      const form = document.getElementById("search-form");
      if (!input || !form) return;
      input.value = chip.dataset.q || "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
  });

  // 提交检索后切到名录页，进度条与结果都在那一页
  document.addEventListener("submit", function (event) {
    if (event.target && event.target.id === "search-form" && window.MentorTabs) {
      window.MentorTabs.activate("directory");
    }
  }, true);

  // 切学院等价于一次新检索，自动进入名录页；排序则留在当前页，
  // 由查询页 / 名录页各自的排序控件处理，避免点一下排序就“跳页”。
  document.addEventListener("click", function (event) {
    const target = event.target && event.target.closest ? event.target.closest("#college-pills") : null;
    if (target && window.MentorTabs) window.MentorTabs.activate("directory");
  }, true);

  const editQuery = document.getElementById("edit-query");
  if (editQuery) {
    editQuery.addEventListener("click", function () {
      if (window.MentorTabs) window.MentorTabs.activate("search");
      const input = document.getElementById("search-input");
      if (input) input.focus();
    });
  }

  window.MentorSettings = { open: openSettings, close: closeSettings };

  // ?view=settings 或旧链接 ?view=about 直接打开设置
  const view = new URLSearchParams(window.location.search).get("view");
  if (view === "settings" || view === "about") openSettings();
})();
