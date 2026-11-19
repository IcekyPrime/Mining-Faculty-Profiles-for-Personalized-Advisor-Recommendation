/* 名录页独立排序条：和 AI 查询页的排序控件各自成组。
 * 点击这里不会切页，只把同一套排序状态同步给列表并重新拉取结果。
 */
(function () {
  "use strict";

  const queryGroup = document.getElementById("sort-group");
  const dirGroup = document.getElementById("results-sort");
  if (!queryGroup || !dirGroup) return;

  const buttons = Array.from(dirGroup.querySelectorAll(".sort-btn"));

  function sync() {
    const active = queryGroup.querySelector(".sort-btn.active");
    const sort = active ? active.dataset.sort : "score";
    buttons.forEach(function (btn) {
      const on = btn.dataset.sort === sort;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  dirGroup.addEventListener("click", function (event) {
    const button = event.target.closest(".sort-btn");
    if (!button) return;
    const twin = queryGroup.querySelector('.sort-btn[data-sort="' + button.dataset.sort + '"]');
    if (twin) twin.click();
    sync();
  });

  // 查询页的排序被点击后，名录页的排序条跟着显示同一选择
  queryGroup.addEventListener("click", function () {
    window.setTimeout(sync, 0);
  });

  sync();
  window.MentorDirectorySort = { sync: sync };
})();
