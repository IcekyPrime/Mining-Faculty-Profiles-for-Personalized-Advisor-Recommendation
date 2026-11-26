/* 名录页独立排序条：和 AI 查询页的排序控件各自保存状态。
 * 点击这里只改变名录排序，不触发查询页排序，也不会切页。
 */
(function () {
  "use strict";

  const dirGroup = document.getElementById("results-sort");
  if (!dirGroup) return;

  function sync() {
    const current = window.MentorApp
      ? window.MentorApp.state.sorts.directory
      : (dirGroup.querySelector(".sort-btn.active") || {}).dataset?.sort || "score";
    dirGroup.querySelectorAll(".sort-btn").forEach(function (btn) {
      const on = btn.dataset.sort === current;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  dirGroup.addEventListener("click", function (event) {
    const button = event.target.closest(".sort-btn");
    if (!button) return;
    event.preventDefault();
    if (window.MentorApp) {
      window.MentorApp.setSort(button.dataset.sort, "directory");
    }
    sync();
  });

  sync();
  window.MentorDirectorySort = { sync: sync };
})();
