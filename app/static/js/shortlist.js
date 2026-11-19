/* 我的收藏：localStorage 收藏、2–4 人并排对比、CSV 导出。全部为前端增量功能。 */
(function () {
  "use strict";

  const FAV_KEY = "mentor-favorites";
  const MAX_COMPARE = 4;
  const cache = new Map();
  const selected = new Set();

  const btn = document.getElementById("shortlist-btn");
  const countBadge = document.getElementById("shortlist-count");
  const backdrop = document.getElementById("shortlist-backdrop");
  const drawer = document.getElementById("shortlist-drawer");
  const closeBtn = document.getElementById("shortlist-close");
  const listEl = document.getElementById("shortlist-list");
  const summaryEl = document.getElementById("shortlist-summary");
  const exportBtn = document.getElementById("shortlist-export");
  const compareBtn = document.getElementById("shortlist-compare");
  const compareBackdrop = document.getElementById("compare-backdrop");
  const compareModal = document.getElementById("compare-modal");
  const compareClose = document.getElementById("compare-close");
  const compareBody = document.getElementById("compare-body");
  if (!btn || !backdrop || !drawer || !listEl) return;

  const escapeMap = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => escapeMap[ch]);

  function loadIds() {
    try {
      const raw = JSON.parse(localStorage.getItem(FAV_KEY) || "[]");
      return Array.isArray(raw) ? raw.map(String).filter(Boolean) : [];
    } catch (err) {
      return [];
    }
  }

  function persistIds(ids) {
    const unique = Array.from(new Set(ids.map(String).filter(Boolean)));
    try { localStorage.setItem(FAV_KEY, JSON.stringify(unique)); } catch (err) { /* 忽略 */ }
    updateCount();
    document.dispatchEvent(new CustomEvent("mentor:favorites-changed", { detail: { ids: unique } }));
    return unique;
  }

  function isFav(id) {
    return loadIds().includes(String(id));
  }

  function updateCount() {
    const total = loadIds().length;
    if (countBadge) {
      countBadge.textContent = String(total);
      countBadge.classList.toggle("hidden", total === 0);
    }
    if (btn) btn.setAttribute("aria-label", `打开我的收藏（${total} 人）`);
  }

  function labelFor(id) {
    return isFav(id) ? "★ 已收藏" : "☆ 收藏";
  }

  function updateButtons(id) {
    const key = String(id);
    document.querySelectorAll(".tc-fav, .detail-fav").forEach((button) => {
      if (String(button.dataset.id) !== key) return;
      const fav = isFav(key);
      button.textContent = fav ? "★ 已收藏" : "☆ 收藏";
      button.classList.toggle("is-fav", fav);
      button.setAttribute("aria-pressed", fav ? "true" : "false");
    });
  }

  function toggle(id) {
    const key = String(id);
    let ids = loadIds();
    if (ids.includes(key)) {
      ids = ids.filter((item) => item !== key);
      selected.delete(key);
    } else {
      ids.push(key);
    }
    ids = persistIds(ids);
    updateButtons(key);
    if (!selected.has(key)) selected.delete(key);
    if (!drawer.classList.contains("hidden")) renderList(ids);
    return ids.includes(key);
  }

  function currentTeacherId() {
    const hashMatch = location.hash.match(/#\/teacher\/(\d+)/);
    if (hashMatch) return hashMatch[1];
    return new URLSearchParams(location.search).get("teacher");
  }

  function decorateCards() {
    document.querySelectorAll("#results-list .teacher-card").forEach((card) => {
      const id = card.dataset.id;
      if (!id) return;
      const side = card.querySelector(".tc-side");
      if (!side || side.querySelector(".tc-fav")) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tc-fav";
      button.dataset.id = String(id);
      button.setAttribute("aria-pressed", isFav(id) ? "true" : "false");
      button.textContent = labelFor(id);
      if (isFav(id)) button.classList.add("is-fav");
      side.appendChild(button);
    });
  }

  function decorateDetail() {
    const root = document.getElementById("detail-root");
    if (!root || root.classList.contains("hidden")) return;
    const id = currentTeacherId();
    if (!id) return;
    const bar = root.querySelector(".back-bar");
    if (!bar || bar.querySelector(".detail-fav")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "detail-fav";
    button.dataset.id = String(id);
    button.setAttribute("aria-pressed", isFav(id) ? "true" : "false");
    button.textContent = labelFor(id);
    if (isFav(id)) button.classList.add("is-fav");
    bar.appendChild(button);
  }

  /* ---------------------------------------------------------------- 详情缓存 */
  async function fetchDetail(id) {
    const key = String(id);
    if (cache.has(key)) return cache.get(key);
    const response = await fetch("/api/teacher/" + encodeURIComponent(key));
    if (!response.ok) throw new Error("teacher " + key + " failed");
    const data = await response.json();
    data.id = String(data.id == null ? key : data.id);
    cache.set(key, data);
    return data;
  }

  async function fetchMissing(ids) {
    const missing = ids.filter((id) => !cache.has(String(id)));
    for (let index = 0; index < missing.length; index += 6) {
      const batch = missing.slice(index, index + 6);
      await Promise.allSettled(batch.map((id) => fetchDetail(id)));
    }
  }

  /* ---------------------------------------------------------------- 列表渲染 */
  function renderEmpty() {
    listEl.innerHTML = '<div class="shortlist-empty"><b>还没有收藏导师</b><br>在名录卡片或档案页点击“☆ 收藏”，就能在这里横向对比。</div>';
  }

  function renderList(ids) {
    const safeIds = ids || loadIds();
    summaryEl.textContent = `已收藏 ${safeIds.length} 人 · 已选 ${selected.size} 人`;
    exportBtn.disabled = safeIds.length === 0;
    compareBtn.disabled = selected.size < 2;
    compareBtn.textContent = `对比选中 ${selected.size}`;
    if (!safeIds.length) {
      renderEmpty();
      return;
    }

    listEl.innerHTML = "";
    safeIds.forEach((id) => {
      const data = cache.get(String(id));
      const item = document.createElement("article");
      item.className = "sl-item";
      item.dataset.id = String(id);
      if (selected.has(String(id))) item.classList.add("is-selected");

      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "sl-check";
      check.checked = selected.has(String(id));
      check.disabled = !data || (!check.checked && selected.size >= MAX_COMPARE);
      check.setAttribute("aria-label", `选择 ${data ? data.name : id} 加入对比`);
      check.addEventListener("change", () => {
        const key = String(id);
        if (check.checked && selected.size < MAX_COMPARE) selected.add(key);
        else selected.delete(key);
        renderList(safeIds);
      });

      const main = document.createElement("div");
      main.className = "sl-main";
      const nameRow = document.createElement("div");
      nameRow.className = "sl-name";
      const name = document.createElement("span");
      name.textContent = data ? data.name : "加载中…";
      const sub = document.createElement("small");
      sub.textContent = data ? (data.title || "职称未收录") : "";
      nameRow.append(name, sub);

      const meta = document.createElement("span");
      meta.className = "sl-meta";
      meta.textContent = data
        ? [data.college, data.institute].filter(Boolean).join(" · ")
        : "正在读取档案…";

      const metrics = document.createElement("div");
      metrics.className = "sl-metrics";
      if (data) {
        const values = [
          ["综合", data.score],
          ["v2", data.score_v2],
          ["H", data.h_index],
          ["教学", data.rating && data.rating.avg != null ? Number(data.rating.avg).toFixed(1) : null],
        ];
        values.forEach(([label, value]) => {
          if (value == null) return;
          const chip = document.createElement("span");
          chip.className = "sl-metric";
          chip.innerHTML = `${esc(label)} <b>${esc(Number(value).toFixed(1))}</b>`;
          metrics.appendChild(chip);
        });
      }
      main.append(nameRow, meta, metrics);

      const tools = document.createElement("div");
      tools.className = "sl-tools";
      const open = document.createElement("button");
      open.type = "button";
      open.className = "sl-open";
      open.textContent = "打开档案 →";
      open.addEventListener("click", () => {
        closeDrawer();
        location.href = "/?teacher=" + encodeURIComponent(String(id));
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "sl-remove";
      remove.textContent = "移除";
      remove.addEventListener("click", () => {
        selected.delete(String(id));
        const next = loadIds().filter((item) => item !== String(id));
        persistIds(next);
        updateButtons(id);
        renderList(next);
      });
      tools.append(open, remove);

      item.append(check, main, tools);
      listEl.appendChild(item);
    });
  }

  async function refreshDrawer() {
    const ids = loadIds();
    renderList(ids);
    if (!ids.length) return;
    try {
      await fetchMissing(ids);
      renderList(ids);
      const missing = ids.filter((id) => !cache.has(String(id))).length;
      if (missing) {
        summaryEl.textContent = `已收藏 ${ids.length} 人 · ${missing} 份档案加载失败，请检查服务后重试`;
      }
    } catch (err) {
      summaryEl.textContent = "档案加载失败，请确认本地服务已启动后重试";
    }
  }

  /* ---------------------------------------------------------------- 抽屉开关 */
  function openDrawer() {
    if (window.MentorSettings && typeof window.MentorSettings.close === "function") {
      window.MentorSettings.close();
    }
    backdrop.classList.remove("hidden");
    drawer.classList.remove("hidden");
    document.body.classList.add("overlay-open");
    btn.setAttribute("aria-expanded", "true");
    refreshDrawer();
  }

  function closeDrawer() {
    backdrop.classList.add("hidden");
    drawer.classList.add("hidden");
    btn.setAttribute("aria-expanded", "false");
    if (document.getElementById("settings-drawer") && !document.getElementById("settings-drawer").classList.contains("hidden")) {
      document.body.classList.add("settings-open");
    } else if (compareModal && !compareModal.classList.contains("hidden")) {
      document.body.classList.add("overlay-open");
    } else {
      document.body.classList.remove("overlay-open");
    }
  }

  btn.addEventListener("click", (event) => {
    event.preventDefault();
    if (drawer.classList.contains("hidden")) openDrawer();
    else closeDrawer();
  });
  closeBtn.addEventListener("click", closeDrawer);
  backdrop.addEventListener("click", closeDrawer);

  const settingsBtn = document.getElementById("settings-btn");
  if (settingsBtn) settingsBtn.addEventListener("click", closeDrawer);

  /* ---------------------------------------------------------------- 对比 */
  function metricCell(value) {
    return value == null || value === "" ? "—" : esc(value);
  }

  function openCompare() {
    const ids = Array.from(selected);
    const rows = ids.map((id) => cache.get(String(id))).filter(Boolean);
    if (rows.length < 2) return;

    const definitions = [
      ["学院", (d) => metricCell(d.college)],
      ["职称", (d) => metricCell(d.title)],
      ["综合评分 v1", (d) => d.score != null ? `<b class="compare-score">${Number(d.score).toFixed(1)}</b>` : "—"],
      ["改进评分 v2", (d) => d.score_v2 != null ? Number(d.score_v2).toFixed(1) : "—"],
      ["H 指数", (d) => metricCell(d.h_index)],
      ["总引用", (d) => d.citation_count != null ? Number(d.citation_count).toLocaleString() : "—"],
      ["论文数", (d) => metricCell(d.paper_count)],
      ["教学评分", (d) => d.rating && d.rating.avg != null
        ? `${Number(d.rating.avg).toFixed(1)} (${d.rating.count || 0})`
        : "—"],
      ["数据完整度", (d) => d.score_coverage != null ? Math.round(Number(d.score_coverage) * 100) + "%" : "—"],
      ["研究方向", (d) => `<span class="compare-dir">${esc(d.research_directions || "暂未收录")}</span>`],
      ["档案", (d) => `<a href="/?teacher=${encodeURIComponent(d.id)}">打开档案 →</a>`],
    ];

    let html = '<table class="compare-table"><thead><tr><th>维度</th>';
    rows.forEach((d) => {
      html += `<th><span class="compare-name">${esc(d.name)}</span>`
        + `<span class="compare-sub">${esc(d.college || "")}</span></th>`;
    });
    html += "</tr></thead><tbody>";
    definitions.forEach(([label, getter]) => {
      html += `<tr><td>${esc(label)}</td>`;
      rows.forEach((d) => { html += `<td>${getter(d)}</td>`; });
      html += "</tr>";
    });
    html += "</tbody></table>";
    compareBody.innerHTML = html;

    compareBackdrop.classList.remove("hidden");
    compareModal.classList.remove("hidden");
    document.body.classList.add("overlay-open");
  }

  function closeCompare() {
    compareBackdrop.classList.add("hidden");
    compareModal.classList.add("hidden");
    if (drawer.classList.contains("hidden")) document.body.classList.remove("overlay-open");
  }

  compareBtn.addEventListener("click", openCompare);
  compareClose.addEventListener("click", closeCompare);
  compareBackdrop.addEventListener("click", closeCompare);

  /* ---------------------------------------------------------------- 导出 */
  function csvCell(value) {
    return '"' + String(value == null ? "" : value).replace(/"/g, '""') + '"';
  }

  async function exportCsv() {
    const ids = loadIds();
    if (!ids.length) return;
    exportBtn.disabled = true;
    const oldLabel = exportBtn.textContent;
    exportBtn.textContent = "正在导出…";
    try {
      await fetchMissing(ids);
      const header = ["姓名", "学院", "职称", "综合评分", "改进评分v2", "H指数", "总引用",
        "论文数", "教学评分", "数据完整度", "研究方向", "邮箱", "个人主页"];
      const lines = [header.map(csvCell).join(",")];
      ids.forEach((id) => {
        const d = cache.get(String(id));
        if (!d) return;
        lines.push([
          d.name, d.college, d.title, d.score, d.score_v2, d.h_index, d.citation_count,
          d.paper_count, d.rating && d.rating.avg != null ? d.rating.avg : "",
          d.score_coverage != null ? Math.round(Number(d.score_coverage) * 100) + "%" : "",
          d.research_directions, d.email, d.personal_homepage || d.homepage_url,
        ].map(csvCell).join(","));
      });
      const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const date = new Date().toLocaleDateString("sv-SE").replace(/-/g, "");
      link.href = url;
      link.download = `导师收藏_${date}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally {
      exportBtn.disabled = false;
      exportBtn.textContent = oldLabel;
    }
  }

  exportBtn.addEventListener("click", exportCsv);

  /* ---------------------------------------------------------------- 状态同步 */
  document.addEventListener("click", (event) => {
    const favButton = event.target.closest(".tc-fav, .detail-fav");
    if (!favButton) return;
    event.preventDefault();
    event.stopPropagation();
    toggle(favButton.dataset.id);
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!compareModal.classList.contains("hidden")) {
      event.preventDefault();
      closeCompare();
    } else if (!drawer.classList.contains("hidden")) {
      event.preventDefault();
      closeDrawer();
    }
  });

  window.addEventListener("storage", () => {
    updateCount();
    decorateCards();
    decorateDetail();
    if (!drawer.classList.contains("hidden")) refreshDrawer();
  });

  window.addEventListener("hashchange", decorateDetail);

  const observer = new MutationObserver(() => {
    decorateCards();
    decorateDetail();
  });
  const resultsList = document.getElementById("results-list");
  const detailRoot = document.getElementById("detail-root");
  if (resultsList) observer.observe(resultsList, { childList: true, subtree: true });
  if (detailRoot) observer.observe(detailRoot, { childList: true, subtree: true });

  updateCount();
  decorateCards();
  decorateDetail();

  window.MentorShortlist = {
    open: openDrawer,
    close: closeDrawer,
    toggle,
    ids: loadIds,
    refresh: refreshDrawer,
  };
})();
