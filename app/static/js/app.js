"use strict";

/* ================================================================
   交大导师 · 改进版前端
   重点：取消过期请求、骨架屏、图表实例复用/销毁、键盘可达性、
   深浅色切换、学院色系与更清晰的学术档案信息层级。
   ================================================================ */

const COLLEGE_META = {
  "计算机学院": { slug: "cs", short: "计算机" },
  "集成电路学院": { slug: "ic", short: "集成电路" },
  "自动化与感知学院": { slug: "sais", short: "自动化" },
  "电气工程学院": { slug: "see", short: "电气" },
  "人工智能学院": { slug: "sai", short: "人工智能" },
};

const DIM_LABELS = {
  papers: "论文产出",
  citations: "引用影响",
  h_index: "学术声誉",
  honors: "荣誉头衔",
  teaching: "教学口碑",
};

const state = {
  query: "",
  college: "",
  sort: "score",
  page: 1,
  size: 20,
  total: 0,
  items: [],
  stats: null,
  detail: null,
  controller: null,
  requestId: 0,
};

const SORTS = ["score", "score2", "academic", "teaching", "relevance"];

/* 把当前检索条件写回 URL，刷新/分享后仍能恢复。只改 q/college/sort/page，
   保留 view、teacher、theme 与 #/teacher/<id> 等既有参数。 */
function syncSearchUrl() {
  const url = new URL(window.location.href);
  const query = state.query.trim();
  // 进入检索态后就不再是某个教师的档案链接，避免刷新后又被带回档案页。
  url.searchParams.delete("teacher");
  url.searchParams.delete("sub");
  if (query) url.searchParams.set("q", query);
  else url.searchParams.delete("q");
  if (state.college) url.searchParams.set("college", state.college);
  else url.searchParams.delete("college");
  if (state.sort && state.sort !== "score") url.searchParams.set("sort", state.sort);
  else url.searchParams.delete("sort");
  if (state.page > 1) url.searchParams.set("page", String(state.page));
  else url.searchParams.delete("page");
  if (url.href !== window.location.href) {
    history.replaceState(history.state || {}, "", url.href);
  }
}

function readInitialSearch() {
  const params = new URLSearchParams(window.location.search);
  const query = params.get("q") || "";
  if (query) {
    state.query = query;
    els.searchInput.value = query;
    els.clearBtn.hidden = false;
  }
  const college = params.get("college") || "";
  if (college) state.college = college;
  const sort = params.get("sort") || "";
  if (SORTS.includes(sort)) state.sort = sort;
  const page = Number.parseInt(params.get("page") || "1", 10);
  return Number.isFinite(page) && page > 1 ? Math.min(page, 30) : 1;
}

function markInitialFilters() {
  els.sortGroup.querySelectorAll(".sort-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.sort === state.sort);
  });
  const pills = Array.from(els.collegePills.querySelectorAll(".pill"));
  const target = pills.find((pill) => (pill.dataset.college || "") === state.college);
  if (target) {
    pills.forEach((pill) => pill.classList.remove("active"));
    target.classList.add("active");
  }
}

const els = {
  searchForm: document.getElementById("search-form"),
  searchInput: document.getElementById("search-input"),
  clearBtn: document.getElementById("clear-btn"),
  collegePills: document.getElementById("college-pills"),
  sortGroup: document.getElementById("sort-group"),
  stats: document.getElementById("stats"),
  resultsCount: document.getElementById("results-count"),
  resultsList: document.getElementById("results-list"),
  pagination: document.getElementById("pagination"),
  loadMore: document.getElementById("load-more"),
  empty: document.getElementById("empty"),
  viewSearch: document.getElementById("view-search"),
  viewDetail: document.getElementById("view-detail"),
  detailRoot: document.getElementById("detail-root"),
  themeToggle: document.getElementById("theme-toggle"),
};

let activeCharts = [];

/* ---------------------------------------------------------------- 基础工具 */
function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeUrl(value) {
  const text = String(value || "").trim();
  return /^https?:\/\//i.test(text) ? text : "";
}

function collegeMeta(name) {
  const meta = COLLEGE_META[name];
  return meta ? { ...meta, name } : { slug: "other", short: name || "其他", name };
}

function collegeClass(name) {
  return "college-" + collegeMeta(name).slug;
}

function fmt(value, compact) {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  if (compact && Math.abs(number) >= 1000) {
    return (number / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  }
  return number.toLocaleString("zh-CN");
}

function fmtScore(value) {
  return value == null ? "—" : Number(value).toFixed(1);
}

function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error("请求失败 " + response.status);
  return response.json();
}

/* ---------------------------------------------------------------- 主题 */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  els.themeToggle.textContent = theme === "dark" ? "浅色" : "深色";
  els.themeToggle.setAttribute("aria-label", theme === "dark" ? "切换到浅色模式" : "切换到深色模式");
}

function initTheme() {
  const forced = new URLSearchParams(window.location.search).get("theme");
  if (forced === "light" || forced === "dark") {
    applyTheme(forced);
    return;
  }
  let saved = "";
  try {
    saved = localStorage.getItem("mentor-theme") || "";
  } catch (err) { /* 本地存储不可用时忽略 */ }
  if (!saved) {
    saved = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }
  applyTheme(saved);
}

els.themeToggle.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("mentor-theme", next); } catch (err) { /* 忽略 */ }
  if (state.detail && !els.viewDetail.classList.contains("hidden")) {
    renderDetail(state.detail);
  }
});

/* ---------------------------------------------------------------- 统计 */
async function loadStats() {
  try {
    const data = await fetchJSON("/api/stats");
    state.stats = data;
    const cards = [
      { value: fmt(data.total_teachers), label: "导师总数", note: "五个学院" },
      { value: fmt(data.colleges.length), label: "覆盖学院", note: "跨院检索" },
      { value: fmt(data.total_papers, true), label: "收录论文", note: "公开主页" },
      { value: fmt(data.total_courses, true), label: "课程记录", note: "选课社区" },
    ];
    els.stats.innerHTML = cards.map((card, index) => `
      <div class="stat-card">
        <span class="stat-index">0${index + 1}</span>
        <div class="stat-value">${esc(card.value)}</div>
        <div class="stat-label">${esc(card.label)}</div>
        <div class="stat-note">${esc(card.note)}</div>
      </div>`).join("");
  } catch (err) {
    els.stats.innerHTML = "";
  }
}

/* ---------------------------------------------------------------- 学院筛选 */
async function loadColleges() {
  try {
    const colleges = await fetchJSON("/api/colleges");
    const total = colleges.reduce((sum, item) => sum + Number(item.count || 0), 0);
    const all = `<button class="pill active" data-college="" type="button">全部<span>${total}</span></button>`;
    const rest = colleges.map((item) => {
      const meta = collegeMeta(item.name);
      return `<button class="pill" data-college="${esc(item.name)}" type="button">${esc(meta.short)}<span>${esc(item.count)}</span></button>`;
    }).join("");
    els.collegePills.innerHTML = all + rest;
  } catch (err) {
    els.collegePills.innerHTML = "";
  }
}

els.collegePills.addEventListener("click", (event) => {
  const button = event.target.closest(".pill");
  if (!button) return;
  els.collegePills.querySelectorAll(".pill").forEach((pill) => pill.classList.remove("active"));
  button.classList.add("active");
  state.college = button.dataset.college || "";
  search(true);
});

/* ---------------------------------------------------------------- 检索 */
function skeleton() {
  return Array.from({ length: 3 }, () => '<div class="skeleton-card"></div>').join("");
}

function renderSkeleton() {
  els.resultsList.innerHTML = skeleton();
  els.resultsCount.textContent = "正在检索…";
  els.empty.classList.add("hidden");
  els.pagination.classList.add("hidden");
}

function cardHtml(teacher) {
  const meta = collegeMeta(teacher.college);
  const honors = (teacher.honors || []).slice(0, 3)
    .map((honor) => `<span class="badge">${esc(honor)}</span>`).join("");
  const keywords = (teacher.keywords || []).slice(0, 5)
    .map((keyword) => `<span class="tag" data-kw="${esc(keyword)}">${esc(keyword)}</span>`).join("");
  const phd = teacher.is_phd_advisor ? '<span class="badge badge-phd">博导</span>' : "";
  const rating = teacher.rating && teacher.rating.avg != null
    ? `<span class="metric star">评分 <b>${Number(teacher.rating.avg).toFixed(1)}</b><span>(${teacher.rating.count || 0})</span></span>`
    : '<span class="metric">暂无评分</span>';
  const metrics = [
    teacher.h_index != null ? `<span class="metric">H 指数 <b>${fmt(teacher.h_index)}</b></span>` : "",
    rating,
    teacher.score != null ? `<span class="metric">综合 <b>${fmtScore(teacher.score)}</b></span>` : "",
  ].join("");
  const direction = teacher.research_directions ? esc(teacher.research_directions) : "研究方向暂未收录";
  const institute = teacher.institute ? ` · ${esc(teacher.institute)}` : "";

  return `
    <article class="teacher-card ${collegeClass(teacher.college)}"
             data-id="${teacher.id}" tabindex="0" role="button"
             aria-label="查看 ${esc(teacher.name)} 的导师档案">
      <div class="tc-avatar" aria-hidden="true">${esc((teacher.name || "?").charAt(0))}</div>
      <div class="tc-main">
        <div class="tc-name-row">
          <h3 class="tc-name">${esc(teacher.name)}</h3>
          <span class="tc-title">${esc(teacher.title || "职称未收录")}</span>
          ${phd}
        </div>
        <div class="tc-meta">
          <span class="college-tag">${esc(meta.short)}</span>
          <span>${esc(teacher.college || "学院未收录")}${institute}</span>
        </div>
        <p class="tc-dir" title="${direction}">${direction}</p>
        <div class="tc-tags">${honors}${keywords}</div>
      </div>
      <div class="tc-side">
        <div class="tc-score"><span>综合评分</span><b>${fmtScore(teacher.score)}</b></div>
        ${teacher.score_v2 != null ? `<div class="tc-score-v2">改进 v2 <b>${fmtScore(teacher.score_v2)}</b></div>` : ""}
        <div class="tc-metrics">${metrics}</div>
        <span class="tc-arrow">查看档案 →</span>
      </div>
    </article>`;
}

function renderResults() {
  if (state.items.length === 0) {
    els.resultsList.innerHTML = "";
    els.resultsCount.textContent = "没有匹配结果";
    els.empty.classList.remove("hidden");
    els.pagination.classList.add("hidden");
    return;
  }
  els.empty.classList.add("hidden");
  els.resultsCount.textContent = `共 ${state.total} 位教师 · 第 ${state.page} 页`;
  els.resultsList.innerHTML = state.items.map(cardHtml).join("");
  const hasMore = state.page * state.size < state.total;
  els.pagination.classList.toggle("hidden", !hasMore);
}

async function search(reset) {
  if (state.controller) state.controller.abort();
  state.controller = new AbortController();
  const requestId = ++state.requestId;

  if (reset) {
    state.page = 1;
    state.items = [];
    renderSkeleton();
  }

  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.college) params.set("college", state.college);
  params.set("sort", state.sort);
  params.set("page", state.page);
  params.set("size", state.size);
  syncSearchUrl();

  els.resultsList.setAttribute("aria-busy", "true");

  try {
    const data = await fetchJSON("/api/search?" + params.toString(), { signal: state.controller.signal });
    if (requestId !== state.requestId) return;
    state.total = data.total;
    state.items = state.items.concat(data.items);
    renderResults();
  } catch (err) {
    if (err.name === "AbortError") return;
    if (requestId !== state.requestId) return;
    els.resultsList.innerHTML = "";
    els.resultsCount.textContent = "加载失败，请重试";
    els.empty.classList.add("hidden");
    els.pagination.classList.add("hidden");
  } finally {
    if (requestId === state.requestId) {
      els.resultsList.removeAttribute("aria-busy");
    }
  }
}

function searchByKeyword(keyword) {
  state.query = keyword;
  els.searchInput.value = keyword;
  els.clearBtn.hidden = false;
  backToList();
  search(true);
}

/* ---------------------------------------------------------------- 搜索交互 */
let inputTimer = null;

els.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(inputTimer);
  state.query = els.searchInput.value.trim();
  search(true);
});

els.searchInput.addEventListener("input", () => {
  els.clearBtn.hidden = !els.searchInput.value;
  clearTimeout(inputTimer);
  inputTimer = setTimeout(() => {
    state.query = els.searchInput.value.trim();
    search(true);
  }, 380);
});

els.clearBtn.addEventListener("click", () => {
  clearTimeout(inputTimer);
  els.searchInput.value = "";
  els.clearBtn.hidden = true;
  state.query = "";
  els.searchInput.focus();
  search(true);
});

els.sortGroup.addEventListener("click", (event) => {
  const button = event.target.closest(".sort-btn");
  if (!button) return;
  els.sortGroup.querySelectorAll(".sort-btn").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  state.sort = button.dataset.sort;
  search(true);
});

els.loadMore.addEventListener("click", () => {
  state.page += 1;
  search(false);
});

document.addEventListener("keydown", (event) => {
  const target = event.target;
  const isTyping = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA");
  if (event.key === "/" && !isTyping) {
    event.preventDefault();
    els.searchInput.focus();
  }
  if (event.key === "Escape" && isTyping && els.searchInput.value) {
    els.clearBtn.click();
  }
});

els.resultsList.addEventListener("click", (event) => {
  const tag = event.target.closest(".tag[data-kw]");
  if (tag) {
    event.stopPropagation();
    searchByKeyword(tag.dataset.kw);
    return;
  }
  const card = event.target.closest(".teacher-card");
  if (card) openDetail(card.dataset.id);
});

els.resultsList.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const card = event.target.closest(".teacher-card");
  if (!card) return;
  event.preventDefault();
  openDetail(card.dataset.id);
});

/* ---------------------------------------------------------------- 详情 */
function disposeCharts() {
  activeCharts.forEach((chart) => {
    try { chart.dispose(); } catch (err) { /* 忽略 */ }
  });
  activeCharts = [];
}

function makeChart(elementId) {
  const element = document.getElementById(elementId);
  if (!element) return null;
  const previous = echarts.getInstanceByDom(element);
  if (previous) previous.dispose();
  const chart = echarts.init(element);
  activeCharts.push(chart);
  return chart;
}

function openDetail(id, options = {}) {
  els.viewSearch.classList.add("hidden");
  els.viewDetail.classList.remove("hidden");
  disposeCharts();
  els.detailRoot.innerHTML = '<div class="skeleton-card" style="height:260px"></div><div class="skeleton-card" style="height:220px;margin-top:14px"></div>';
  if (!options.fromHash) {
    // 档案页可直接分享：把当前教师写进 URL
    const hash = "#/teacher/" + encodeURIComponent(id);
    if (location.hash !== hash) history.pushState({ teacher: id }, "", hash);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });

  fetchJSON("/api/teacher/" + encodeURIComponent(id))
    .then((data) => {
      state.detail = data;
      renderDetail(data);
    })
    .catch(() => {
      els.detailRoot.innerHTML = `
        <div class="back-bar"><button class="back-btn" id="back-btn" type="button">← 返回导师名录</button></div>
        <div class="empty"><p class="empty-title">档案加载失败</p><p class="empty-sub">请返回列表后重试</p></div>`;
      const back = document.getElementById("back-btn");
      if (back) back.addEventListener("click", backToList);
    });
}

function teacherIdFromHash() {
  const match = /^#\/teacher\/(\d+)$/.exec(location.hash || "");
  return match ? Number(match[1]) : null;
}

window.addEventListener("popstate", () => {
  const id = teacherIdFromHash();
  if (id) openDetail(id, { fromHash: true });
  else backToList();
});

window.addEventListener("hashchange", () => {
  const id = teacherIdFromHash();
  if (id && (!state.detail || Number(state.detail.id) !== id)) openDetail(id, { fromHash: true });
});

function renderDetail(data) {
  disposeCharts();
  const meta = collegeMeta(data.college);
  const honors = (data.honors || []).map((honor) => `<span class="badge">${esc(honor)}</span>`).join("");
  const phd = data.is_phd_advisor ? '<span class="badge badge-phd">博导</span>' : "";
  const keywords = (data.keywords || []).map((keyword) => `<span class="tag" data-kw="${esc(keyword)}">${esc(keyword)}</span>`).join("");
  const ratingAvg = data.rating && data.rating.avg != null ? Number(data.rating.avg) : null;
  const ratingCount = data.rating ? Number(data.rating.count || 0) : 0;
  const paperTotal = data.paper_total != null ? data.paper_total : (data.papers || []).length;
  const publishedTotal = data.paper_count != null ? data.paper_count : paperTotal;
  const score = fmtScore(data.score);
  const coverage = data.score_coverage != null ? Math.round(Number(data.score_coverage) * 100) : null;

  const metrics = [
    { label: "H 指数", value: fmt(data.h_index) },
    { label: "总引用", value: fmt(data.citation_count, true) },
    { label: "论文数", value: fmt(publishedTotal) },
    { label: "教学评分", value: ratingAvg != null ? ratingAvg.toFixed(1) : "—" },
    { label: "综合评分", value: score, accent: true },
  ].map((item) => `
    <div class="dm">
      <div class="dm-value ${item.accent ? "accent" : ""}">${esc(item.value)}</div>
      <div class="dm-label">${esc(item.label)}</div>
    </div>`).join("");

  const courseHtml = (data.courses || []).map((course) => {
    const rating = course.rating != null
      ? `<span class="course-rating">评分 ${Number(course.rating).toFixed(1)}<span class="cnt">(${course.count || 0})</span></span>`
      : '<span class="muted-note">暂无评分</span>';
    return `
      <div class="course-item">
        <div>
          <div><span class="course-name">${esc(course.name)}</span><span class="course-code">${esc(course.code || "")}</span></div>
          <div class="course-meta">${esc(course.semester || "学期未收录")}</div>
        </div>
        ${rating}
      </div>`;
  }).join("") || '<p class="muted-note">暂无课程记录</p>';

  const paperHtml = (data.papers || []).map((paper) => {
    const metaText = [
      paper.venue,
      paper.year ? String(paper.year) : "",
      paper.citations != null ? `被引 ${paper.citations}` : "",
    ].filter(Boolean).map(esc).join(" · ");
    return `
      <div class="paper-item">
        <div class="paper-title">${esc(paper.title)}</div>
        <div class="paper-meta">${metaText || "论文信息待补充"}</div>
      </div>`;
  }).join("") || '<p class="muted-note">暂无论文记录</p>';

  const similarHtml = (data.similar || []).map((teacher) => `
    <button class="similar-pill" type="button" data-id="${teacher.id}">
      ${esc(teacher.name)}<span class="sub">${esc(collegeMeta(teacher.college).short)}</span>
    </button>`).join("") || '<p class="muted-note">暂无相似导师数据</p>';

  const collaborators = data.collaborators || [];
  const collabNote = collaborators.length
    ? `<p class="chart-note">共 ${collaborators.length} 位直接合作者，线条越粗表示合作次数越多。</p>`
    : '<p class="muted-note">暂无合作网络数据（当前仅计算机学院论文含完整作者列表）</p>';

  const contactRows = [];
  if (data.email) {
    contactRows.push(`<div class="kv-item"><b>邮箱</b><a href="mailto:${esc(data.email)}">${esc(data.email)}</a></div>`);
  }
  const personal = safeUrl(data.personal_homepage);
  if (personal) {
    contactRows.push(`<div class="kv-item"><b>个人主页</b><a href="${esc(personal)}" target="_blank" rel="noopener">${esc(personal)}</a></div>`);
  }
  const official = safeUrl(data.homepage_url);
  if (official) {
    contactRows.push(`<div class="kv-item"><b>教师主页</b><a href="${esc(official)}" target="_blank" rel="noopener">查看官网档案</a></div>`);
  }

  const miniStats = [];
  if (data.cluster != null) miniStats.push(`<div class="mini-stat"><b>${esc(data.cluster)}</b><span>研究方向簇</span></div>`);
  if (data.community != null) miniStats.push(`<div class="mini-stat"><b>${esc(data.community)}</b><span>合作社区</span></div>`);
  if (data.pagerank != null) miniStats.push(`<div class="mini-stat"><b>${Number(data.pagerank).toFixed(3)}</b><span>PageRank</span></div>`);
  if (data.hits_authority != null) miniStats.push(`<div class="mini-stat"><b>${Number(data.hits_authority).toFixed(3)}</b><span>HITS 权威度</span></div>`);

  const scorePartsHtml = renderScoreParts(data.score_parts);
  const missingDims = Object.entries(data.radar_known || {})
    .filter(([, known]) => !known)
    .map(([dim]) => dim);
  const radarNote = missingDims.length
    ? `<p class="chart-note">无公开数据：${missingDims.map(esc).join("、")}（雷达图按 0 显示，且不计入综合评分）。</p>`
    : '<p class="chart-note">按全库百分位计算。</p>';

  const paperNote = data.paper_count != null
    ? `<p class="chart-note">AMiner 统计 ${esc(data.paper_count)} 篇；本地收录 ${paperTotal} 篇代表论文${(data.papers || []).length ? `，展示被引最高的 ${(data.papers || []).length} 篇` : ""}。</p>`
    : (paperTotal > (data.papers || []).length
      ? `<p class="chart-note">共收录 ${paperTotal} 篇，展示其中的 ${(data.papers || []).length} 篇。</p>`
      : "");

  const contactBlock = contactRows.length
    ? `<div class="kv">${contactRows.join("")}</div>`
    : '<p class="muted-note">公开渠道暂未收录联系方式</p>';
  const miniBlock = miniStats.length ? `<div class="mini-grid">${miniStats.join("")}</div>` : "";

  els.detailRoot.innerHTML = `
    <div class="back-bar"><button class="back-btn" id="back-btn" type="button">← 返回导师名录</button></div>

    <section class="profile-card ${collegeClass(data.college)}">
      <div class="profile-main">
        <div class="detail-avatar" aria-hidden="true">${esc((data.name || "?").charAt(0))}</div>
        <div class="profile-id">
          <span class="eyebrow">${esc(meta.name || "教师档案")}</span>
          <h2 class="detail-name">${esc(data.name)}</h2>
          <div class="detail-title">${esc(data.title || "职称未收录")}${data.institute ? " · " + esc(data.institute) : ""}</div>
          <div class="detail-badges">${phd}${honors}</div>
        </div>
      </div>
      <div class="profile-score">
        <span>综合评分</span>
        <strong>${score}</strong>
        <em>COMPOSITE SCORE</em>
        ${data.score_v2 != null ? `<i class="coverage-note">改进评分 v2 ${fmtScore(data.score_v2)}</i>` : ""}
        ${coverage != null ? `<i class="coverage-note">数据完整度 ${coverage}%</i>` : ""}
      </div>
    </section>

    <div class="detail-metrics">${metrics}</div>
    ${scorePartsHtml}

    <div class="detail-grid">
      <div class="detail-col">
        <section class="panel">
          <div class="section-title">研究方向</div>
          <p class="dir-text">${esc(data.research_directions || "暂未收录研究方向")}</p>
          ${keywords ? `<div class="tc-tags" style="margin-top:12px">${keywords}</div>` : ""}
        </section>
        ${data.bio ? `<section class="panel"><div class="section-title">个人简介</div><p class="bio-text">${esc(data.bio)}</p></section>` : ""}
        <section class="panel">
          <div class="section-title">联系方式</div>
          ${contactBlock}
          ${miniBlock}
        </section>
        <section class="panel">
          <div class="section-title">讲授课程</div>
          <div class="course-list">${courseHtml}</div>
        </section>
      </div>

      <div class="detail-col">
        <section class="panel">
          <div class="section-title">能力画像</div>
          <div class="chart-box" id="radar-chart"></div>
          ${radarNote}
        </section>
        <section class="panel">
          <div class="section-title">合作网络</div>
          ${collabNote}
          <div class="chart-box" id="network-chart" style="${collaborators.length ? "" : "display:none"}"></div>
        </section>
        <section class="panel">
          <div class="section-title">相似导师</div>
          <div class="similar-list">${similarHtml}</div>
        </section>
        <section class="panel">
          <div class="section-title">代表论文</div>
          <div class="paper-list">${paperHtml}</div>
          ${paperNote}
        </section>
      </div>
    </div>`;

  document.getElementById("back-btn").addEventListener("click", backToList);
  els.detailRoot.querySelectorAll("[data-kw]").forEach((element) => {
    element.addEventListener("click", () => searchByKeyword(element.dataset.kw));
  });
  els.detailRoot.querySelectorAll(".similar-pill[data-id]").forEach((element) => {
    element.addEventListener("click", () => openDetail(element.dataset.id));
  });

  requestAnimationFrame(() => {
    renderRadar(data.radar || {});
    renderNetwork(data);
  });
}

function renderScoreParts(parts) {
  if (!parts || !Object.keys(parts).length) return "";
  const rows = Object.entries(parts).map(([key, part]) => {
    const label = DIM_LABELS[key] || key;
    const pct = part && part.pct != null ? Math.max(0, Math.min(100, Number(part.pct))) : null;
    if (pct == null) {
      return `<div class="score-row is-missing">
        <span class="score-label">${esc(label)}</span>
        <span class="score-bar"><i style="width:0"></i></span>
        <span class="score-value">无数据</span>
      </div>`;
    }
    return `<div class="score-row">
      <span class="score-label">${esc(label)}</span>
      <span class="score-bar"><i style="width:${pct.toFixed(1)}%"></i></span>
      <span class="score-value">${pct.toFixed(0)}</span>
    </div>`;
  }).join("");
  return `<section class="panel score-panel">
    <div class="section-title">评分构成（改进版 v2）</div>
    <div class="score-parts">${rows}</div>
    <p class="chart-note">每项为全库百分位分数；缺失维度不计入，权重按可用维度重新归一，并向中位数做收缩。上方"综合评分"仍为原始算法得分，可对照查看。</p>
  </section>`;
}

function backToList() {
  els.viewDetail.classList.add("hidden");
  els.viewSearch.classList.remove("hidden");
  disposeCharts();
  if (location.hash) history.pushState({}, "", location.pathname + location.search);
  // 从分享链接直接进档案时列表还没加载过，返回时补一次检索，避免“返回后空白”。
  if (state.items.length === 0) search(true);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------------------------------------------------------------- 图表 */
function chartTheme() {
  return {
    ink: cssVar("--ink", "#17211d"),
    ink2: cssVar("--ink-2", "#5d6a63"),
    ink3: cssVar("--ink-3", "#8a958e"),
    surface: cssVar("--surface", "#fffdf8"),
    bg: cssVar("--bg", "#f6f2e9"),
    accent: cssVar("--accent", "#1f6f63"),
    gold: cssVar("--gold", "#b27a2c"),
  };
}

function renderRadar(radar) {
  const chart = makeChart("radar-chart");
  if (!chart) return;
  const keys = Object.keys(radar);
  if (!keys.length) return;
  const theme = chartTheme();
  chart.setOption({
    animationDuration: 450,
    tooltip: {
      trigger: "item",
      backgroundColor: theme.surface,
      borderColor: theme.ink3,
      textStyle: { color: theme.ink, fontSize: 12 },
    },
    radar: {
      indicator: keys.map((key) => ({ name: key, max: 100 })),
      radius: "64%",
      splitNumber: 4,
      axisName: { color: theme.ink2, fontSize: 11 },
      splitLine: { lineStyle: { color: theme.bg, width: 1 } },
      splitArea: { areaStyle: { color: [theme.surface, theme.bg] } },
      axisLine: { lineStyle: { color: theme.bg } },
    },
    series: [{
      type: "radar",
      data: [{
        value: keys.map((key) => Number(radar[key]) || 0),
        name: "能力画像",
        symbolSize: 5,
        itemStyle: { color: theme.accent },
        lineStyle: { color: theme.accent, width: 2 },
        areaStyle: { color: "rgba(31, 111, 99, 0.16)" },
      }],
    }],
  });
}

function renderNetwork(data) {
  const collaborators = data.collaborators || [];
  if (!collaborators.length) return;
  const chart = makeChart("network-chart");
  if (!chart) return;
  const theme = chartTheme();
  const nodes = [{
    id: String(data.id),
    name: data.name,
    symbolSize: 48,
    itemStyle: { color: theme.accent },
    label: { show: true, color: theme.ink, fontSize: 12, fontWeight: 600 },
  }];
  const links = [];
  collaborators.forEach((teacher) => {
    nodes.push({
      id: String(teacher.id),
      name: teacher.name,
      symbolSize: Math.max(16, Math.min(32, 14 + (teacher.weight || 0) / 4)),
      itemStyle: { color: theme.gold },
      label: { show: true, color: theme.ink2, fontSize: 10 },
    });
    links.push({
      source: String(data.id),
      target: String(teacher.id),
      lineStyle: { color: theme.ink3, width: 1.2, opacity: 0.55 },
    });
  });
  chart.setOption({
    animationDuration: 500,
    tooltip: {
      trigger: "item",
      backgroundColor: theme.surface,
      borderColor: theme.ink3,
      textStyle: { color: theme.ink, fontSize: 12 },
      formatter: (params) => params.dataType === "node"
        ? `${params.name}${params.data.id === String(data.id) ? "（本人）" : ""}`
        : "",
    },
    series: [{
      type: "graph",
      layout: "force",
      roam: true,
      draggable: true,
      data: nodes,
      links,
      force: { repulsion: 170, edgeLength: 95, gravity: 0.08 },
      emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
    }],
  });
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    activeCharts.forEach((chart) => {
      try { chart.resize(); } catch (err) { /* 忽略 */ }
    });
  }, 120);
});

/* ---------------------------------------------------------------- 初始化 */
initTheme();
(async function init() {
  await Promise.allSettled([loadStats(), loadColleges()]);
  const initialPage = readInitialSearch();
  markInitialFilters();
  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get("teacher");
  const teacherId = fromQuery || teacherIdFromHash();
  if (teacherId) {
    // 支持 ?teacher=1002 与 #/teacher/1002 两种直达链接
    if (!location.hash) history.replaceState({ teacher: teacherId }, "", "#/teacher/" + teacherId);
    openDetail(teacherId, { fromHash: true });
  } else {
    if (initialPage > 1) {
      state.items = [];
      for (let page = 1; page <= initialPage; page += 1) {
        state.page = page;
        await search(page === 1);
      }
    } else {
      search(true);
    }
    // URL 里带检索条件时，直接落到名录页看结果；设置/概况等显式视图保持不动。
    const view = params.get("view");
    if ((state.query || state.college) && window.MentorTabs
        && (!view || view === "search" || view === "directory")) {
      window.MentorTabs.activate("directory");
    }
  }
})();
