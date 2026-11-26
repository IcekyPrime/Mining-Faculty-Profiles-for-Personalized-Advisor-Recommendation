"use strict";

/* ---------------------------------------------------------------- 状态 */
const state = {
  query: "",
  college: "",
  sort: "score",
  page: 1,
  size: 20,
  total: 0,
  items: [],
  view: "search",
  detailTab: "overview",
  detail: null,
  insights: null,
  stats: null,
  colleges: [],
};

const els = {
  searchInput: document.getElementById("search-input"),
  searchForm: document.getElementById("search-form"),
  clearBtn: document.getElementById("clear-btn"),
  collegePills: document.getElementById("college-pills"),
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
  settingsBtn: document.getElementById("settings-btn"),
  settingsDrawer: document.getElementById("settings-drawer"),
  settingsBackdrop: document.getElementById("settings-backdrop"),
  settingsClose: document.getElementById("settings-close"),
  brandHome: document.getElementById("brand-home"),
  editQuery: document.getElementById("edit-query"),
  queryChips: document.getElementById("query-chips"),
};

const charts = {};

/* ---------------------------------------------------------------- 工具 */
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
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function fmt(v, short) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  if (short && n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toLocaleString();
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function chart(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  if (charts[id]) {
    charts[id].dispose();
  }
  charts[id] = echarts.init(el);
  return charts[id];
}

function palette() {
  return {
    accent: cssVar("--accent"),
    accentText: cssVar("--accent-text"),
    line: cssVar("--line"),
    ink: cssVar("--ink"),
    ink2: cssVar("--ink-2"),
    ink3: cssVar("--ink-3"),
    surface: cssVar("--surface"),
    surface2: cssVar("--surface-2"),
  };
}

/* 隐藏面板中初始化 ECharts 会得到零宽容器，因此只在可见时建图 */
function paneVisible(id) {
  const el = document.getElementById(id);
  return !!el && el.offsetParent !== null;
}

const baseText = () => ({
  color: palette().ink2,
  fontFamily: '"Inter","PingFang SC","Microsoft YaHei",Arial,sans-serif',
});

/* ---------------------------------------------------------------- 主题 */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
  document.querySelectorAll("[data-theme-choice]").forEach(b => {
    b.classList.toggle("active", b.dataset.themeChoice === theme);
  });
  Object.keys(charts).forEach(id => { if (charts[id]) { charts[id].dispose(); delete charts[id]; } });
  renderDynamic();
}

/* ---------------------------------------------------------------- 语言 */
function refreshLang() {
  applyI18n();
  renderDynamic();
}

function renderDynamic() {
  renderStats();
  renderCollegePills();
  renderResults();
  renderDetail();
  renderInsights();
  if (window.MobileAI && MobileAI.refresh) MobileAI.refresh();
}

/* ---------------------------------------------------------------- 标签页 */
function setView(view) {
  state.view = view;
  document.querySelectorAll(".view-tab").forEach(b => {
    b.classList.toggle("active", b.dataset.view === view);
  });
  document.querySelectorAll("[data-pane]").forEach(el => {
    el.classList.toggle("hidden", el.dataset.pane !== view);
  });
  els.viewSearch.classList.remove("hidden");
  els.viewDetail.classList.add("hidden");
  if (view === "overview") {
    if (state.insights) renderInsights();
    else loadInsights();
  }
  requestAnimationFrame(() => {
    Object.values(charts).forEach(c => c && c.resize());
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------------------------------------------------------------- 统计 */
async function loadStats() {
  try {
    state.stats = await fetchJSON("/api/stats");
    state.colleges = state.stats.colleges || [];
    renderStats();
    renderCollegePills();
    const panelTotal = document.getElementById("panel-total");
    if (panelTotal) panelTotal.textContent = state.stats.total_teachers;
  } catch (e) {
    state.stats = null;
  }
}

function renderStats() {
  if (!els.stats || !state.stats) return;
  const s = state.stats;
  const cards = [
    { v: s.total_teachers, l: t("stats.teachers") },
    { v: s.colleges.length, l: t("stats.colleges") },
    { v: fmt(s.total_papers, true), l: t("stats.papers") },
    { v: fmt(s.total_courses, true), l: t("stats.courses") },
  ];
  els.stats.innerHTML = cards.map((c, i) => `
    <div class="stat-card">
      <span class="stat-index">0${i + 1}</span>
      <div class="stat-value">${c.v}</div>
      <div class="stat-label">${esc(c.l)}</div>
      <span class="stat-orbit"></span>
    </div>`).join("");
}

function renderCollegePills() {
  if (!els.collegePills) return;
  const cols = state.colleges.length ? state.colleges : [];
  els.collegePills.innerHTML =
    `<button class="pill${state.college ? "" : " active"}" data-college="" type="button">${esc(t("filter.all"))}</button>` +
    cols.map(c => `<button class="pill${state.college === c.name ? " active" : ""}" data-college="${esc(c.name)}" type="button">${esc(collegeName(c.name))}</button>`).join("");
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
    els.resultsCount.textContent = "—";
  }
}

function cardHtml(item) {
  const honors = (item.honors || []).slice(0, 3)
    .map(h => `<span class="badge" title="${esc(h)}">${esc(h)}</span>`).join("");
  const kws = (item.keywords || []).slice(0, 4)
    .map(k => `<span class="tag" data-kw="${esc(k)}">${esc(k)}</span>`).join("");
  const adv = item.is_phd_advisor
    ? `<span class="badge">${currentLang === "en" ? "PhD supervisor" : "博导"}</span>` : "";
  const rating = item.rating && item.rating.avg != null
    ? `<span class="metric">${esc(t("sort.teaching"))}<b>${item.teaching_imputed ? "0" : item.rating.avg.toFixed(1)}</b></span>`
    : `<span class="metric">${esc(t("card.noTeaching"))}</span>`;
  const score = item.score != null ? item.score.toFixed(1) : "—";
  return `
    <article class="teacher-card" data-id="${item.id}">
      <div class="tc-top">
        <div class="tc-avatar">${esc((item.name || "?").charAt(0))}</div>
        <div class="tc-main">
          <div class="tc-name-row">
            <span class="tc-name">${esc(item.name)}</span>
            <span class="tc-title">${esc(item.title)}</span>
            ${adv}
          </div>
          <div class="tc-meta">${esc(collegeName(item.college))}${item.institute ? " · " + esc(item.institute) : ""}</div>
          ${item.research_directions ? `<div class="tc-dir">${esc(item.research_directions)}</div>` : ""}
          <div class="tc-tags">${honors}${kws}</div>
          <div class="tc-metrics">
            <span class="metric">h 指数<b>${fmt(item.h_index)}</b></span>
            <span class="metric">${esc(t("detail.metric.paper"))}<b>${fmt(item.paper_count)}</b></span>
            <span class="metric">${esc(t("detail.metric.cite"))}<b>${fmt(item.citation_count, true)}</b></span>
            ${rating}
          </div>
        </div>
      </div>
      <div class="tc-score">
        <div class="tc-score-label">${esc(t("detail.metric.score"))}</div>
        <div class="tc-score-value">${score}</div>
        <div class="tc-score-sub">${esc(t("card.view"))}</div>
      </div>
    </article>`;
}

function renderResults() {
  if (!els.resultsList) return;
  els.resultsCount.textContent = t("dir.count", { n: state.total });
  if (!state.items.length) {
    els.resultsList.innerHTML = "";
    els.empty.classList.remove("hidden");
    els.pagination.classList.add("hidden");
    return;
  }
  els.empty.classList.add("hidden");
  els.resultsList.innerHTML = state.items.map(cardHtml).join("");
  els.pagination.classList.toggle("hidden", state.page * state.size >= state.total);
}

/* ---------------------------------------------------------------- 详情 */
async function openDetail(id) {
  els.viewDetail.classList.remove("hidden");
  els.viewSearch.classList.add("hidden");
  els.detailRoot.innerHTML = "";
  window.scrollTo({ top: 0, behavior: "smooth" });
  try {
    state.detail = await fetchJSON("/api/teacher/" + id);
    state.detailTab = "overview";
    renderDetail();
  } catch (e) {
    els.detailRoot.innerHTML = `<p class="muted-note">—</p>`;
  }
}

function backToList() {
  els.viewDetail.classList.add("hidden");
  els.viewSearch.classList.remove("hidden");
  renderDynamic();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function metricBox(value, label, cls) {
  return `<div class="metric-box"><b${cls ? ` class="${cls}"` : ""}>${value}</b><span>${esc(label)}</span></div>`;
}

function renderDetail() {
  const d = state.detail;
  if (!d || !els.detailRoot) return;

  const honors = (d.honors || []).map(h =>
    `<span class="badge" title="${esc(h)}">${esc(h)}</span>`).join("");
  const adv = d.is_phd_advisor
    ? `<span class="badge">${currentLang === "en" ? "PhD supervisor" : "博导"}</span>` : "";
  const rating = d.teaching_imputed ? "0"
    : (d.rating && d.rating.avg != null ? d.rating.avg.toFixed(1) : t("detail.noRating"));
  const score = d.score != null ? d.score.toFixed(1) : "—";

  const tabs = [
    ["overview", t("detail.tab.overview")],
    ["academic", t("detail.tab.academic")],
    ["teaching", t("detail.tab.teaching")],
    ["network", t("detail.tab.network")],
  ].map(([k, label]) =>
    `<button class="detail-tab${state.detailTab === k ? " active" : ""}" data-dtab="${k}" type="button">${esc(label)}</button>`
  ).join("");

  els.detailRoot.innerHTML = `
    <div class="back-bar"><button class="back-btn" id="back-btn" type="button">← ${esc(t("detail.back"))}</button></div>
    <div class="detail-tabs">${tabs}</div>

    <section class="profile-card">
      <div class="profile-head">
        <div class="profile-avatar">${esc((d.name || "?").charAt(0))}</div>
        <div class="profile-main">
          <div class="profile-name">${esc(d.name)}</div>
          <div class="profile-title">${esc(d.title)}</div>
          <div class="profile-meta">${esc(collegeName(d.college))}${d.institute ? " · " + esc(d.institute) : ""}</div>
          <div class="profile-badges">${adv}${honors}</div>
        </div>
        <div class="profile-score">
          <div class="profile-score-label">${esc(t("detail.metric.score"))}</div>
          <div class="profile-score-value">${score}</div>
        </div>
      </div>
      <div class="metrics-row">
        ${metricBox(fmt(d.h_index), t("detail.metric.h"))}
        ${metricBox(fmt(d.citation_count, true), t("detail.metric.cite"))}
        ${metricBox(fmt(d.paper_count), t("detail.metric.paper"))}
        ${metricBox(rating, t("detail.metric.teaching"))}
        ${metricBox(score, t("detail.metric.score"))}
      </div>
    </section>

    <div id="detail-pane">${detailPaneHtml(d)}</div>`;

  document.getElementById("back-btn").addEventListener("click", backToList);
  els.detailRoot.querySelectorAll("[data-dtab]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.detailTab = btn.dataset.dtab;
      renderDetail();
    });
  });
  els.detailRoot.querySelectorAll("[data-kw]").forEach(el =>
    el.addEventListener("click", e => { e.stopPropagation(); searchByKeyword(el.dataset.kw); }));
  els.detailRoot.querySelectorAll("[data-similar]").forEach(el =>
    el.addEventListener("click", () => openDetail(el.dataset.similar)));

  drawDetailCharts();
}

function scorePartsHtml(d) {
  const sp = d.score_parts;
  if (!sp || !sp.parts || !sp.parts.length) return "";
  const labels = {
    paper: t("score.paper"),
    citation: t("score.citation"),
    honor: t("score.honor"),
    teaching: t("score.teaching"),
  };
  const rows = sp.parts.map(p => {
    const pct = Math.max(0, Math.min(100, p.norm * 100));
    return `<div class="score-row">
      <span class="score-label">${esc(labels[p.key] || p.key)}<em>×${p.weight}</em></span>
      <span class="score-track"><i style="width:${pct.toFixed(1)}%"></i></span>
      <span class="score-value${p.key === "teaching" && d.teaching_imputed ? " imputed-value" : ""}">${p.contribution.toFixed(1)}</span>
    </div>`;
  }).join("");
  return `<section class="panel">
    <div class="section-title">${esc(t("score.title"))}</div>
    <div class="score-parts">${rows}</div>
    <div class="score-total">
      <span>${esc(t("detail.metric.score"))}</span>
      <b>${sp.total.toFixed(1)}</b>
    </div>
  </section>`;
}

function detailPaneHtml(d) {
  if (state.detailTab === "overview") {
    const kws = (d.keywords || [])
      .map(k => `<span class="tag" data-kw="${esc(k)}">${esc(k)}</span>`).join("");
    return `
      <div class="detail-grid">
        <div class="detail-col">
          <section class="panel">
            <div class="section-title">${esc(t("detail.direction"))}</div>
            <p class="body-text">${d.research_directions ? esc(d.research_directions) : "—"}</p>
            ${kws ? `<div class="tc-tags" style="margin-top:12px">${kws}</div>` : ""}
          </section>
          ${d.bio ? `<section class="panel"><div class="section-title">${esc(t("detail.about"))}</div><p class="body-text">${esc(d.bio)}</p></section>` : ""}
          <section class="panel">
            <div class="section-title">${esc(t("detail.similar"))}</div>
            <div>${(d.similar || []).map(s =>
              `<span class="similar-pill" data-similar="${s.id}">${esc(s.name)}<span class="sub">${esc(collegeName(s.college))}</span></span>`
            ).join("") || `<p class="muted-note">${esc(t("detail.empty.similar"))}</p>`}</div>
          </section>
        </div>
        <div class="detail-col">
          ${scorePartsHtml(d)}
          <section class="panel">
            <div class="section-title">${esc(t("detail.contact"))}</div>
            <div class="kv">
              ${d.email ? `<div class="kv-item"><b>${esc(t("detail.email"))}</b>${esc(d.email)}</div>` : ""}
              ${d.personal_homepage ? `<div class="kv-item"><b>${esc(t("detail.homepage"))}</b><a href="${esc(d.personal_homepage)}" target="_blank" rel="noopener">${esc(d.personal_homepage)}</a></div>` : ""}
              ${d.homepage_url ? `<div class="kv-item"><b>${esc(t("detail.official"))}</b><a href="${esc(d.homepage_url)}" target="_blank" rel="noopener">${esc(d.homepage_url)}</a></div>` : ""}
            </div>
          </section>
        </div>
      </div>`;
  }

  if (state.detailTab === "academic") {
    const papers = (d.papers || []).map(p => `
      <div class="paper-item">
        <div class="paper-title">${esc(p.title)}</div>
        <div class="paper-meta">${esc(p.venue || "")} · ${esc(p.year || "")}${p.citations != null ? " · " + p.citations : ""}</div>
      </div>`).join("") || `<p class="muted-note">${esc(t("detail.empty.paper"))}</p>`;
    return `
      <div class="detail-grid">
        <div class="detail-col">
          <section class="panel">
            <div class="section-title">${esc(t("detail.radar"))}</div>
            <div class="chart-box" id="radar-chart"></div>
          </section>
        </div>
        <div class="detail-col">
          <section class="panel">
            <div class="section-title">${esc(t("detail.papers"))}</div>
            <div class="paper-list">${papers}</div>
          </section>
        </div>
      </div>`;
  }

  if (state.detailTab === "teaching") {
    const courses = (d.courses || []).map(c => {
      const r = c.rating != null
        ? `<span class="course-rating">★ ${c.rating.toFixed(1)}<span class="cnt">(${c.count || 0})</span></span>`
        : `<span class="muted-note">${esc(t("detail.noRating"))}</span>`;
      return `<div class="course-item">
        <div><span class="course-name">${esc(c.name)}</span><span class="course-code">${esc(c.code || "")}</span></div>${r}
      </div>`;
    }).join("") || `<p class="muted-note">${esc(t("detail.empty.course"))}</p>`;
    return `
      <div class="detail-grid">
        <div class="detail-col">
          <section class="panel">
            <div class="section-title">${esc(t("detail.courses"))}</div>
            <div class="course-list">${courses}</div>
          </section>
        </div>
        <div class="detail-col">
          <section class="panel">
            <div class="section-title">${esc(t("detail.metric.teaching"))}</div>
            <div class="metrics-row" style="grid-template-columns:repeat(2,1fr)">
              ${metricBox(d.teaching_imputed ? "0" : (d.rating && d.rating.avg != null ? d.rating.avg.toFixed(1) : "—"), t("detail.metric.teaching"))}
              ${metricBox(fmt(d.rating ? d.rating.count : 0), currentLang === "en" ? "ratings" : "评分人数")}
            </div>
          </section>
        </div>
      </div>`;
  }

  return `
    <div class="detail-grid">
      <div class="detail-col">
        <section class="panel">
          <div class="section-title">${esc(t("detail.network"))}</div>
          ${(d.collaborators || []).length
            ? `<p class="muted-note" style="margin-bottom:8px">${esc(t("detail.networkHint"))}</p>
               <div class="chart-box" id="network-chart"></div>`
            : `<p class="muted-note">${esc(t("detail.empty.collab"))}</p>`}
        </section>
      </div>
      <div class="detail-col">
        <section class="panel">
          <div class="section-title">${esc(t("detail.similar"))}</div>
          <div>${(d.similar || []).map(s =>
            `<span class="similar-pill" data-similar="${s.id}">${esc(s.name)}<span class="sub">${esc(collegeName(s.college))}</span></span>`
          ).join("") || `<p class="muted-note">${esc(t("detail.empty.similar"))}</p>`}</div>
        </section>
      </div>
    </div>`;
}

function drawDetailCharts() {
  const d = state.detail;
  if (!d || els.viewDetail.classList.contains("hidden")) return;
  const p = palette();

  if (state.detailTab === "academic" && d.radar) {
    const c = chart("radar-chart");
    if (c) {
      const keys = Object.keys(d.radar);
      c.setOption({
        tooltip: {},
        radar: {
          indicator: keys.map(k => ({ name: k, max: 100 })),
          radius: "64%",
          splitNumber: 4,
          axisName: { color: p.ink2, fontSize: 11 },
          splitLine: { lineStyle: { color: p.line } },
          splitArea: { areaStyle: { color: [p.surface, p.surface2] } },
          axisLine: { lineStyle: { color: p.line } },
        },
        series: [{
          type: "radar",
          data: [{
            value: keys.map(k => d.radar[k]),
            name: t("detail.radar"),
            symbolSize: 4,
            itemStyle: { color: p.accentText },
            lineStyle: { color: p.accentText, width: 2 },
            areaStyle: { color: p.accent, opacity: 0.25 },
          }],
        }],
      });
    }
  }

  if (state.detailTab === "network" && (d.collaborators || []).length) {
    const c = chart("network-chart");
    if (c) {
      const nodes = [{
        id: "self",
        name: d.name,
        symbolSize: 44,
        itemStyle: { color: p.accentText },
        label: { show: true, color: p.ink, fontSize: 12 },
      }];
      const links = [];
      const idByName = { [d.name]: d.id };
      (d.collaborators || []).forEach(co => {
        nodes.push({
          id: String(co.id),
          name: co.name,
          symbolSize: Math.max(16, Math.min(34, 14 + co.weight / 4)),
          itemStyle: { color: p.accent },
          label: { show: true, color: p.ink2, fontSize: 10 },
        });
        idByName[co.name] = co.id;
        links.push({ source: "self", target: String(co.id), lineStyle: { color: p.line, width: 1.4 } });
      });
      c.setOption({
        tooltip: { trigger: "item", formatter: o => o.dataType === "node" ? o.name : "" },
        series: [{
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          data: nodes,
          links,
          force: { repulsion: 180, edgeLength: 90, gravity: 0.08 },
          emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
        }],
      });
      c.off("click");
      c.on("click", params => {
        if (params.dataType !== "node") return;
        const target = idByName[params.name];
        if (target && target !== d.id) openDetail(target);
      });
    }
  }
}

/* ---------------------------------------------------------------- 概况 */
async function loadInsights() {
  try {
    state.insights = await fetchJSON("/api/insights");
    renderInsights();
  } catch (e) {
    state.insights = null;
  }
}

function renderInsights() {
  const ins = state.insights;
  if (!ins) return;
  const p = palette();

  const sig = (id, val) => {
    const v = document.getElementById(id);
    if (v) v.textContent = val;
  };
  const cov = {};
  (ins.coverage || []).forEach(c => { cov[c.field] = c.pct; });
  const dirPct = cov.research_directions || 0;
  const acaPct = cov.h_index || 0;
  const teaPct = ins.teaching ? ins.teaching.pct : 0;
  sig("signal-direction", dirPct);
  sig("signal-academic", acaPct);
  sig("signal-teaching", teaPct);
  const bar = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.style.width = Math.min(100, v) + "%";
  };
  bar("bar-direction", dirPct);
  bar("bar-academic", acaPct);
  bar("bar-teaching", teaPct);

  const c1 = paneVisible("pane-overview") ? chart("insight-colleges") : null;
  if (c1) {
    c1.setOption({
      grid: { left: 8, right: 40, top: 10, bottom: 6, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        type: "value",
        splitLine: { lineStyle: { color: p.line } },
        axisLabel: { color: p.ink3, fontSize: 10 },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: ins.colleges.map(c => collegeName(c.name)),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: p.ink2, fontSize: 11 },
      },
      series: [{
        type: "bar",
        data: ins.colleges.map(c => c.count),
        barWidth: 12,
        itemStyle: { color: p.accent, borderRadius: [0, 6, 6, 0] },
        label: { show: true, position: "right", color: p.ink3, fontSize: 10 },
      }],
    });
  }

  const covBox = document.getElementById("insight-coverage");
  if (covBox) {
    covBox.innerHTML = ins.coverage.map(c => `
      <div class="cov-row">
        <span class="cov-name">${esc(t("field." + c.field))}</span>
        <span class="cov-track"><i style="width:${c.pct}%"></i></span>
        <span class="cov-val">${c.filled}/${c.total} · ${c.pct}%</span>
      </div>`).join("");
  }

  const c2 = paneVisible("pane-overview") ? chart("insight-scores") : null;
  if (c2) {
    c2.setOption({
      grid: { left: 8, right: 12, top: 16, bottom: 6, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: ins.histogram.bins,
        axisLine: { lineStyle: { color: p.line } },
        axisTick: { show: false },
        axisLabel: { color: p.ink3, fontSize: 10, rotate: 30 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: p.line } },
        axisLabel: { color: p.ink3, fontSize: 10 },
      },
      series: [{
        type: "bar",
        data: ins.histogram.counts,
        barWidth: "52%",
        itemStyle: { color: p.accent, borderRadius: [4, 4, 0, 0] },
      }],
    });
  }

  const topBox = document.getElementById("insight-top");
  if (topBox) {
    topBox.innerHTML = ins.top.map((x, i) => `
      <div class="top-row" data-top="${x.id}">
        <span class="top-rank">${String(i + 1).padStart(2, "0")}</span>
        <span class="top-name">${esc(x.name)}</span>
        <span class="top-college">${esc(collegeName(x.college))}</span>
        <span class="top-score">${x.score != null ? x.score.toFixed(1) : "—"}</span>
      </div>`).join("");
    topBox.querySelectorAll("[data-top]").forEach(el =>
      el.addEventListener("click", () => openDetail(el.dataset.top)));
  }

  const clBox = document.getElementById("insight-clusters");
  if (clBox) {
    clBox.innerHTML = ins.clusters.slice(0, 8).map(c => `
      <div class="cluster-card">
        <div class="cluster-size">${c.size}</div>
        <div class="cluster-label">${esc(t("insight.people"))}${currentLang === "zh" ? "" : " members"}</div>
        <div class="cluster-kw">${c.keywords.map(esc).join(" · ")}</div>
      </div>`).join("");
  }

  const coBox = document.getElementById("insight-communities");
  if (coBox) {
    coBox.innerHTML = ins.communities.slice(0, 8).map(c => `
      <div class="comm-row">
        <span class="comm-id">#${c.id}</span>
        <span class="comm-size">${c.size}</span>
        <span class="comm-sample">${c.sample.slice(0, 4).map(esc).join("、")}</span>
      </div>`).join("");
  }

  const ruBox = document.getElementById("insight-rules");
  if (ruBox) {
    ruBox.innerHTML = ins.rules.map(r => `
      <div class="rule-row">
        <b>{${esc(r.antecedent)}}</b><span class="rule-arrow">→</span><b>{${esc(r.consequent)}}</b>
        <span class="rule-stat">sup ${r.support} · conf ${r.confidence} · lift ${r.lift}</span>
      </div>`).join("") || `<p class="muted-note">—</p>`;
  }
}

/* ---------------------------------------------------------------- 交互 */
function searchByKeyword(kw) {
  state.query = kw;
  els.searchInput.value = kw;
  els.clearBtn.classList.remove("hidden");
  backToList();
  setView("search");
  search(true).then(() => setView("directory"));
}

function bindEvents() {
  els.searchForm.addEventListener("submit", e => {
    e.preventDefault();
    state.query = els.searchInput.value.trim();
    search(true).then(() => setView("directory"));
  });
  els.searchInput.addEventListener("input", () => {
    els.clearBtn.classList.toggle("hidden", !els.searchInput.value);
  });
  els.clearBtn.addEventListener("click", () => {
    els.searchInput.value = "";
    state.query = "";
    els.clearBtn.classList.add("hidden");
    search(true);
  });
  els.collegePills.addEventListener("click", e => {
    const btn = e.target.closest("[data-college]");
    if (!btn) return;
    state.college = btn.dataset.college;
    renderCollegePills();
    search(true).then(() => setView("directory"));
  });
  els.sortGroup.addEventListener("click", e => {
    const btn = e.target.closest(".sort-btn");
    if (!btn) return;
    els.sortGroup.querySelectorAll(".sort-btn").forEach(b => b.classList.remove("active"));
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
    if (card) openDetail(card.dataset.id);
  });
  els.queryChips.addEventListener("click", e => {
    const chip = e.target.closest(".query-chip");
    if (!chip) return;
    searchByKeyword(chip.dataset.q);
  });
  document.querySelectorAll(".view-tab").forEach(btn =>
    btn.addEventListener("click", () => setView(btn.dataset.view)));
  els.editQuery.addEventListener("click", () => setView("search"));
  els.brandHome.addEventListener("click", e => {
    e.preventDefault();
    backToList();
    setView("search");
  });
  document.querySelectorAll("[data-theme-choice]").forEach(btn =>
    btn.addEventListener("click", () => applyTheme(btn.dataset.themeChoice)));
  document.querySelectorAll("[data-lang-choice]").forEach(btn =>
    btn.addEventListener("click", () => { setLang(btn.dataset.langChoice); refreshLang(); }));
  els.settingsBtn.addEventListener("click", () => {
    if (window.MobileAI && MobileAI.close) MobileAI.close();
    els.settingsDrawer.classList.remove("hidden");
    els.settingsBackdrop.classList.remove("hidden");
  });
  const closeSettings = () => {
    els.settingsDrawer.classList.add("hidden");
    els.settingsBackdrop.classList.add("hidden");
  };
  els.settingsClose.addEventListener("click", closeSettings);
  els.settingsBackdrop.addEventListener("click", closeSettings);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeSettings();
  });
  window.addEventListener("resize", () => Object.values(charts).forEach(c => c && c.resize()));
}

/* ---------------------------------------------------------------- 初始化 */
(async function init() {
  applyTheme(localStorage.getItem("theme") || "light");
  applyI18n();
  bindEvents();
  await loadStats();
  await Promise.all([search(true), loadInsights()]);
  setView("search");
})();
