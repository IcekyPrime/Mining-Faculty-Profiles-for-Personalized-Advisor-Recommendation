"use strict";

const state = {
  query: "",
  college: "",
  sort: "score",
  page: 1,
  size: 20,
  total: 0,
  items: [],
};

const els = {
  searchInput: document.getElementById("search-input"),
  searchBtn: document.getElementById("search-btn"),
  collegeSelect: document.getElementById("college-select"),
  sortGroup: document.getElementById("sort-group"),
  stats: document.getElementById("stats"),
  resultsCount: document.getElementById("results-count"),
  resultsList: document.getElementById("results-list"),
  loadMore: document.getElementById("load-more"),
  pagination: document.getElementById("pagination"),
  empty: document.getElementById("empty"),
  viewSearch: document.getElementById("view-search"),
  viewDetail: document.getElementById("view-detail"),
  detailRoot: document.getElementById("detail-root"),
};

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("请求失败 " + res.status);
  return res.json();
}

function fmt(v, suffix) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  if (suffix && n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toLocaleString();
}

function fmtRating(avg, count) {
  if (avg == null) return "暂无评分";
  return avg.toFixed(1) + " 分 · " + count + " 人评价";
}

/* ---------------------------------------------------------------- 统计 */
async function loadStats() {
  try {
    const s = await fetchJSON("/api/stats");
    const cards = [
      { value: s.total_teachers, label: "导师总数" },
      { value: s.colleges.length, label: "覆盖学院" },
      { value: fmt(s.total_papers, true), label: "收录论文" },
      { value: fmt(s.total_courses, true), label: "课程评价" },
    ];
    els.stats.innerHTML = cards.map(c =>
      `<div class="stat-card"><div class="stat-value">${c.value}</div><div class="stat-label">${c.label}</div></div>`
    ).join("");
  } catch (e) {
    els.stats.innerHTML = "";
  }
}

async function loadColleges() {
  try {
    const cols = await fetchJSON("/api/colleges");
    els.collegeSelect.innerHTML = '<option value="">全部学院</option>' +
      cols.map(c => `<option value="${esc(c.name)}">${esc(c.name)} (${c.count})</option>`).join("");
  } catch (e) { /* 忽略 */ }
}

/* ---------------------------------------------------------------- 检索 */
async function search(reset) {
  if (reset) {
    state.page = 1;
    state.items = [];
  }
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.college) params.set("college", state.college);
  params.set("sort", state.sort);
  params.set("page", state.page);
  params.set("size", state.size);

  try {
    const data = await fetchJSON("/api/search?" + params.toString());
    state.total = data.total;
    state.items = state.items.concat(data.items);
    renderResults();
  } catch (e) {
    els.resultsCount.textContent = "加载失败，请重试";
  }
}

function metricChips(t) {
  const chips = [];
  if (t.h_index != null) chips.push(`<span class="metric">H指数 <b>${fmt(t.h_index)}</b></span>`);
  if (t.citation_count != null) chips.push(`<span class="metric">引用 <b>${fmt(t.citation_count, true)}</b></span>`);
  if (t.paper_count != null) chips.push(`<span class="metric">论文 <b>${fmt(t.paper_count)}</b></span>`);
  if (t.rating && t.rating.avg != null) {
    chips.push(`<span class="metric star">评分 <b>${t.rating.avg.toFixed(1)}</b><span style="color:#9ca3af">(${t.rating.count})</span></span>`);
  } else {
    chips.push(`<span class="metric" style="color:#9ca3af">无教学评分</span>`);
  }
  if (t.score != null) chips.push(`<span class="metric">综合 <b>${t.score.toFixed(1)}</b></span>`);
  return chips.join("");
}

function cardHtml(t) {
  const keywords = (t.keywords || []).slice(0, 4)
    .map(k => `<span class="tag" data-kw="${esc(k)}">${esc(k)}</span>`).join("");
  const honors = (t.honors || []).slice(0, 3)
    .map(h => `<span class="badge">${esc(h)}</span>`).join("");
  const adv = t.is_phd_advisor ? '<span class="badge" style="color:#0369a1;background:#f0f9ff;border-color:#bae6fd">博导</span>' : "";
  const dir = t.research_directions ? esc(t.research_directions) : "";
  return `
    <div class="teacher-card" data-id="${t.id}">
      <div class="tc-top">
        <div class="tc-avatar">${esc((t.name || "?").charAt(0))}</div>
        <div class="tc-main">
          <div class="tc-name-row">
            <span class="tc-name">${esc(t.name)}</span>
            <span class="tc-title">${esc(t.title)}</span>
            ${adv}
          </div>
          <div class="tc-meta">${esc(t.college)}${t.institute ? " · " + esc(t.institute) : ""}</div>
          ${dir ? `<div class="tc-dir">${dir}</div>` : ""}
          <div class="tc-tags">${honors}${keywords}</div>
          <div class="tc-metrics">${metricChips(t)}</div>
        </div>
      </div>
    </div>`;
}

function renderResults() {
  els.resultsCount.textContent = `共 ${state.total} 位教师`;
  if (state.items.length === 0) {
    els.resultsList.innerHTML = "";
    els.empty.classList.remove("hidden");
    els.pagination.classList.add("hidden");
    return;
  }
  els.empty.classList.add("hidden");
  els.resultsList.innerHTML = state.items.map(cardHtml).join("");
  const hasMore = state.page * state.size < state.total;
  els.pagination.classList.toggle("hidden", !hasMore);
}

/* ---------------------------------------------------------------- 详情 */
async function openDetail(id) {
  els.viewSearch.classList.add("hidden");
  els.viewDetail.classList.remove("hidden");
  els.detailRoot.innerHTML = '<div class="empty"><p class="empty-title">加载中</p></div>';
  window.scrollTo(0, 0);
  try {
    const d = await fetchJSON("/api/teacher/" + id);
    renderDetail(d);
  } catch (e) {
    els.detailRoot.innerHTML = '<div class="empty"><p class="empty-title">加载失败</p></div>';
  }
}

function renderDetail(d) {
  const honors = (d.honors || []).map(h => `<span class="badge">${esc(h)}</span>`).join("");
  const adv = d.is_phd_advisor ? '<span class="badge" style="color:#0369a1;background:#f0f9ff;border-color:#bae6fd">博导</span>' : "";
  const keywords = (d.keywords || []).map(k => `<span class="tag" data-kw="${esc(k)}">${esc(k)}</span>`).join("");
  const rating = d.rating && d.rating.avg != null ? d.rating.avg.toFixed(1) : "无评分";

  const metrics = [
    { label: "H 指数", value: fmt(d.h_index), accent: false },
    { label: "总引用", value: fmt(d.citation_count, true), accent: false },
    { label: "论文数", value: fmt(d.paper_count), accent: false },
    { label: "教学评分", value: rating, accent: false },
    { label: "综合评分", value: d.score != null ? d.score.toFixed(1) : "—", accent: true },
  ].map(m =>
    `<div class="dm"><div class="dm-value${m.accent ? " accent" : ""}">${m.value}</div><div class="dm-label">${m.label}</div></div>`
  ).join("");

  const courses = (d.courses || []).map(c => {
    const r = c.rating != null ? `<span class="course-rating">★ ${c.rating.toFixed(1)}<span class="cnt">(${c.count || 0})</span></span>` : '<span class="muted-note">暂无评分</span>';
    return `<div class="course-item"><div><span class="course-name">${esc(c.name)}</span><span class="course-code">${esc(c.code || "")}</span></div>${r}</div>`;
  }).join("") || '<p class="muted-note">暂无课程记录</p>';

  const papers = (d.papers || []).map(p =>
    `<div class="paper-item"><div class="paper-title">${esc(p.title)}</div><div class="paper-meta">${esc(p.venue || "")} · ${esc(p.year || "")}${p.citations != null ? " · 被引 " + p.citations : ""}</div></div>`
  ).join("") || '<p class="muted-note">暂无论文记录</p>';

  const similar = (d.similar || []).map(s =>
    `<span class="similar-pill" data-id="${s.id}">${esc(s.name)}<span class="sub">${esc(s.college || "")}</span></span>`
  ).join("");

  const collabNote = (d.collaborators || []).length > 0
    ? "" : '<p class="muted-note">暂无合作网络数据</p>';

  els.detailRoot.innerHTML = `
    <div class="back-bar"><button class="back-btn" id="back-btn">← 返回列表</button></div>
    <div class="detail-card">
      <div class="detail-head">
        <div class="detail-avatar">${esc((d.name || "?").charAt(0))}</div>
        <div>
          <div class="detail-name">${esc(d.name)}</div>
          <div class="detail-title">${esc(d.title)}</div>
          <div class="detail-meta">${esc(d.college)}${d.institute ? " · " + esc(d.institute) : ""}</div>
          <div class="detail-badges">${adv}${honors}</div>
        </div>
      </div>
      <div class="detail-metrics">${metrics}</div>
    </div>

    <div class="detail-grid">
      <div class="detail-col">
        <div class="detail-card">
          <div class="section-title">研究方向</div>
          <p class="dir-text">${d.research_directions ? esc(d.research_directions) : "暂无"}</p>
          ${keywords ? `<div class="tc-tags" style="margin-top:12px">${keywords}</div>` : ""}
        </div>
        ${d.bio ? `<div class="detail-card"><div class="section-title">简介</div><p class="bio-text">${esc(d.bio)}</p></div>` : ""}
        <div class="detail-card">
          <div class="section-title">联系方式</div>
          <div class="kv">
            ${d.email ? `<div class="kv-item"><b>邮箱</b>${esc(d.email)}</div>` : ""}
            ${d.personal_homepage ? `<div class="kv-item"><b>主页</b><a href="${esc(d.personal_homepage)}" target="_blank" rel="noopener">${esc(d.personal_homepage)}</a></div>` : ""}
            ${d.homepage_url ? `<div class="kv-item"><b>教师主页</b><a href="${esc(d.homepage_url)}" target="_blank" rel="noopener">查看</a></div>` : ""}
          </div>
        </div>
        <div class="detail-card">
          <div class="section-title">讲授课程</div>
          <div class="course-list">${courses}</div>
        </div>
      </div>

      <div class="detail-col">
        <div class="detail-card">
          <div class="section-title">能力画像</div>
          <div class="chart-box" id="radar-chart"></div>
        </div>
        <div class="detail-card">
          <div class="section-title">合作网络</div>
          ${collabNote}
          <div class="chart-box" id="network-chart" style="${(d.collaborators || []).length ? "" : "display:none"}"></div>
        </div>
        ${similar ? `<div class="detail-card"><div class="section-title">相似导师</div><div class="similar-list">${similar}</div></div>` : ""}
        <div class="detail-card">
          <div class="section-title">代表论文</div>
          <div class="paper-list">${papers}</div>
        </div>
      </div>
    </div>`;

  document.getElementById("back-btn").addEventListener("click", backToList);
  els.detailRoot.querySelectorAll("[data-kw]").forEach(el =>
    el.addEventListener("click", () => searchByKeyword(el.dataset.kw)));
  els.detailRoot.querySelectorAll("[data-id]").forEach(el =>
    el.addEventListener("click", () => openDetail(el.dataset.id)));

  renderRadar(d.radar);
  if ((d.collaborators || []).length) renderNetwork(d);
}

function renderRadar(radar) {
  const el = document.getElementById("radar-chart");
  if (!el || !radar) return;
  const chart = echarts.init(el);
  const keys = Object.keys(radar);
  chart.setOption({
    tooltip: { trigger: "item" },
    radar: {
      indicator: keys.map(k => ({ name: k, max: 100 })),
      radius: "62%",
      splitNumber: 4,
      axisName: { color: "#6b7280", fontSize: 12 },
      splitLine: { lineStyle: { color: "#e5e7eb" } },
      splitArea: { areaStyle: { color: ["#fafafa", "#f5f6f8"] } },
      axisLine: { lineStyle: { color: "#e5e7eb" } },
    },
    series: [{
      type: "radar",
      data: [{
        value: keys.map(k => radar[k]),
        name: "能力画像",
        symbolSize: 4,
        itemStyle: { color: "#2563eb" },
        lineStyle: { color: "#2563eb", width: 2 },
        areaStyle: { color: "rgba(37, 99, 235, 0.18)" },
      }],
    }],
  });
}

function renderNetwork(d) {
  const el = document.getElementById("network-chart");
  if (!el) return;
  const chart = echarts.init(el);
  const nodes = [{
    id: String(d.id),
    name: d.name,
    symbolSize: 46,
    itemStyle: { color: "#2563eb" },
    label: { show: true, color: "#1f2328", fontSize: 12 },
  }];
  const links = [];
  (d.collaborators || []).forEach(c => {
    nodes.push({
      id: String(c.id),
      name: c.name,
      symbolSize: Math.max(16, Math.min(34, 14 + c.weight / 4)),
      itemStyle: { color: "#93c5fd" },
      label: { show: true, color: "#6b7280", fontSize: 10 },
    });
    links.push({ source: String(d.id), target: String(c.id), lineStyle: { color: "#dbeafe", width: 1.5 } });
  });
  chart.setOption({
    tooltip: { trigger: "item", formatter: p => p.dataType === "node" ? p.name : "" },
    series: [{
      type: "graph",
      layout: "force",
      roam: true,
      draggable: true,
      data: nodes,
      links: links,
      force: { repulsion: 180, edgeLength: 90, gravity: 0.08 },
      emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
    }],
  });
}

function backToList() {
  els.viewDetail.classList.add("hidden");
  els.viewSearch.classList.remove("hidden");
  window.scrollTo(0, 0);
}

function searchByKeyword(kw) {
  state.query = kw;
  els.searchInput.value = kw;
  backToList();
  search(true);
}

/* ---------------------------------------------------------------- 事件 */
els.searchBtn.addEventListener("click", () => {
  state.query = els.searchInput.value.trim();
  search(true);
});
els.searchInput.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    state.query = els.searchInput.value.trim();
    search(true);
  }
});
els.collegeSelect.addEventListener("change", () => {
  state.college = els.collegeSelect.value;
  search(true);
});
els.sortGroup.addEventListener("click", e => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  els.sortGroup.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
  btn.classList.add("active");
  state.sort = btn.dataset.sort;
  search(true);
});
els.loadMore.addEventListener("click", () => {
  state.page += 1;
  search(false);
});
els.resultsList.addEventListener("click", e => {
  const card = e.target.closest(".teacher-card");
  if (card) { openDetail(card.dataset.id); return; }
  const tag = e.target.closest(".tag[data-kw]");
  if (tag) { searchByKeyword(tag.dataset.kw); }
});

/* ---------------------------------------------------------------- 初始化 */
(async function init() {
  await Promise.all([loadStats(), loadColleges()]);
  search(true);
})();
