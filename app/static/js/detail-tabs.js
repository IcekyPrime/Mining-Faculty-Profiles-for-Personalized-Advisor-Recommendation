/* 档案页二级分区：概览 / 学术 / 教学 / 人脉
 * 不修改 app.js 的渲染模板，只在渲染完成后给已有 panel 打上分类标记，
 * 并插入一条子导航；切换时只做显示/隐藏，不重建内容。
 */
(function () {
  "use strict";

  const root = document.getElementById("detail-root");
  if (!root) return;

  const CATEGORY = {
    "评分构成（改进版 v2）": "overview",
    "评分构成": "overview",
    "研究方向": "overview",
    "能力画像": "overview",
    "联系方式": "overview",
    "个人简介": "academic",
    "代表论文": "academic",
    "讲授课程": "teaching",
    "合作网络": "network",
    "相似导师": "network",
  };

  const PANES = [
    { key: "overview", label: "概览" },
    { key: "academic", label: "学术" },
    { key: "teaching", label: "教学" },
    { key: "network", label: "人脉" },
  ];

  function categoryOf(panel) {
    const title = panel.querySelector(".section-title");
    const text = title ? title.textContent.trim() : "";
    if (CATEGORY[text]) return CATEGORY[text];
    // 标题可能带后缀，比如「评分构成（改进版 v2）」
    const hit = Object.keys(CATEGORY).find(function (key) {
      return text.indexOf(key) === 0;
    });
    return hit ? CATEGORY[hit] : "overview";
  }

  function resizeCharts() {
    root.querySelectorAll(".chart-box").forEach(function (node) {
      try {
        const instance = window.echarts && window.echarts.getInstanceByDom(node);
        if (instance) instance.resize();
      } catch (err) { /* 忽略 */ }
    });
  }

  function apply(key) {
    root.dataset.pane = key;
    root.querySelectorAll(".detail-subtab").forEach(function (button) {
      const active = button.dataset.sub === key;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    // 某一列在当前分区没有内容时收起该列，避免留下空栏
    const grid = root.querySelector(".detail-grid");
    if (grid) {
      let empty = 0;
      root.querySelectorAll(".detail-col").forEach(function (col) {
        const visible = Array.from(col.querySelectorAll(".panel")).filter(function (panel) {
          return panel.offsetParent !== null;
        });
        const isHiddenCol = col.offsetParent === null;
        col.classList.toggle("is-empty", !isHiddenCol && visible.length === 0);
        if (!isHiddenCol && visible.length === 0) empty += 1;
      });
      grid.classList.toggle("single-col", empty >= 1);
    }
    requestAnimationFrame(resizeCharts);
  }

  function build() {
    if (!root.querySelector(".profile-card") || root.querySelector("#detail-tabs")) return;
    root.querySelectorAll(".panel").forEach(function (panel) {
      if (panel.dataset.pane) return;
      panel.dataset.pane = categoryOf(panel);
    });

    const bar = document.createElement("nav");
    bar.id = "detail-tabs";
    bar.className = "detail-tabs";
    bar.setAttribute("role", "tablist");
    bar.setAttribute("aria-label", "档案分区");
    bar.innerHTML = PANES.map(function (pane) {
      return '<button class="detail-subtab" type="button" role="tab" data-sub="' +
        pane.key + '" aria-selected="false">' + pane.label + "</button>";
    }).join("");

    bar.addEventListener("click", function (event) {
      const button = event.target.closest(".detail-subtab");
      if (button) apply(button.dataset.sub);
    });

    const backBar = root.querySelector(".back-bar");
    if (backBar && backBar.parentNode) backBar.parentNode.insertBefore(bar, backBar.nextSibling);
    else root.insertBefore(bar, root.firstChild);

    const wanted = new URLSearchParams(window.location.search).get("sub");
    apply(PANES.some(function (pane) { return pane.key === wanted; }) ? wanted : "overview");
  }

  const observer = new MutationObserver(function () {
    if (root.querySelector(".profile-card")) build();
  });
  observer.observe(root, { childList: true, subtree: true });
})();
