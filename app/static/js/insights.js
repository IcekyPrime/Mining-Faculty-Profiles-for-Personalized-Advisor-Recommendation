/* 数据洞察页：一次拉取 /api/insights，渲染图表与列表（懒加载，只在切到该页时执行）。 */
(function () {
  "use strict";

  const charts = [];
  let loaded = false;
  let loading = false;
  let lastData = null;

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function theme() {
    const css = getComputedStyle(document.documentElement);
    return {
      ink: css.getPropertyValue("--ink").trim() || "#17211d",
      ink2: css.getPropertyValue("--ink-2").trim() || "#5d6a63",
      ink3: css.getPropertyValue("--ink-3").trim() || "#8a958e",
      accent: css.getPropertyValue("--accent").trim() || "#1f6f63",
      gold: css.getPropertyValue("--gold").trim() || "#b27a2c",
      surface: css.getPropertyValue("--surface").trim() || "#fffdf8",
      line: css.getPropertyValue("--line").trim() || "#e6e0d4",
    };
  }

  function chart(id) {
    const node = document.getElementById(id);
    if (!node) return null;
    const instance = echarts.getInstanceByDom(node) || echarts.init(node);
    if (charts.indexOf(instance) === -1) charts.push(instance);
    return instance;
  }

  function renderColleges(items) {
    const instance = chart("insight-colleges");
    if (!instance) return;
    const t = theme();
    instance.setOption({
      grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.ink } },
      xAxis: {
        type: "value",
        axisLabel: { color: t.ink3, fontSize: 11 },
        splitLine: { lineStyle: { color: t.line, type: "dashed" } },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: items.map(function (item) { return item.name; }),
        axisLabel: { color: t.ink2, fontSize: 12 },
        axisLine: { lineStyle: { color: t.line } },
      },
      series: [{
        type: "bar",
        name: "教师数",
        data: items.map(function (item) { return item.count; }),
        barWidth: 14,
        itemStyle: {
          borderRadius: [0, 7, 7, 0],
          color: {
            type: "linear", x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: t.accent },
              { offset: 1, color: t.gold },
            ],
          },
        },
        label: { show: true, position: "right", color: t.ink2, fontSize: 11 },
      }],
    });
  }

  function renderCoverage(items) {
    const node = document.getElementById("insight-coverage");
    if (!node) return;
    node.innerHTML = items.map(function (item) {
      const pct = Math.round((item.ratio || 0) * 100);
      return '<div class="coverage-row">' +
        '<span class="coverage-label">' + esc(item.label) + '</span>' +
        '<span class="coverage-track"><i style="width:' + pct + '%"></i></span>' +
        '<span class="coverage-value">' + esc(item.count) + '/' + esc(item.total) +
        ' <em>' + pct + '%</em></span>' +
        '</div>';
    }).join("");
  }

  function renderScores(data) {
    const hist = data.histogram || { labels: [], original: [], improved: [] };
    const instance = chart("insight-scores");
    if (instance) {
      const t = theme();
      instance.setOption({
        grid: { left: 8, right: 12, top: 30, bottom: 8, containLabel: true },
        legend: { top: 0, textStyle: { color: t.ink2, fontSize: 11 } },
        tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.ink } },
        xAxis: {
          type: "category",
          data: hist.labels,
          axisLabel: { color: t.ink3, fontSize: 10, interval: 0 },
          axisLine: { lineStyle: { color: t.line } },
        },
        yAxis: {
          type: "value",
          axisLabel: { color: t.ink3, fontSize: 11 },
          splitLine: { lineStyle: { color: t.line, type: "dashed" } },
        },
        series: [
          { name: "原始 v1", type: "bar", data: hist.original, barWidth: 9,
            itemStyle: { color: t.ink3, borderRadius: [4, 4, 0, 0] } },
          { name: "改进 v2", type: "bar", data: hist.improved, barWidth: 9,
            itemStyle: { color: t.accent, borderRadius: [4, 4, 0, 0] } },
        ],
      });
    }

    const topNode = document.getElementById("insight-top");
    if (!topNode) return;
    const rows = (data.top_improved || []).map(function (item, index) {
      return '<button class="top-score-item" type="button" data-id="' + esc(item.id) + '">' +
        '<span class="rank">' + String(index + 1).padStart(2, "0") + '</span>' +
        '<span class="who">' + esc(item.name) + '<em>' + esc(item.college || "") + '</em></span>' +
        '<span class="scores"><b>' + Number(item.score_v2).toFixed(1) + '</b><i>v1 ' +
        (item.score == null ? "—" : Number(item.score).toFixed(1)) + '</i></span>' +
        '</button>';
    }).join("");
    topNode.innerHTML = '<div class="top-score-head">改进评分 Top 10（含原始分对照）</div>' + rows;
  }

  function renderClusters(items) {
    const node = document.getElementById("insight-clusters");
    if (!node) return;
    node.innerHTML = items.map(function (cluster) {
      const tags = (cluster.keywords || []).map(function (word) {
        return '<span class="mini-tag">' + esc(word) + '</span>';
      }).join("");
      const members = (cluster.members || []).map(function (member) {
        return '<button class="member-link" type="button" data-id="' + esc(member.id) + '">' +
          esc(member.name) + '</button>';
      }).join("");
      return '<article class="cluster-card">' +
        '<div class="cluster-head"><span class="cluster-id">簇 ' + esc(cluster.id) + '</span>' +
        '<strong>' + esc(cluster.size) + ' 人</strong></div>' +
        '<div class="mini-tags">' + tags + '</div>' +
        '<div class="cluster-members">代表：' + members + '</div>' +
        '</article>';
    }).join("");
  }

  function renderCommunities(count, items) {
    const node = document.getElementById("insight-communities");
    if (!node) return;
    const max = items.length ? items[0].size : 1;
    node.innerHTML = '<p class="chart-note">共 ' + esc(count) + ' 个社区，列出人数最多的 6 个。</p>' +
      items.map(function (item) {
        const pct = Math.round(item.size / max * 100);
        return '<div class="community-row">' +
          '<span class="community-id">#' + esc(item.id) + '</span>' +
          '<span class="community-track"><i style="width:' + pct + '%"></i></span>' +
          '<span class="community-size">' + esc(item.size) + ' 人</span>' +
          '</div>';
      }).join("");
  }

  function renderRules(items) {
    const node = document.getElementById("insight-rules");
    if (!node) return;
    if (!items.length) {
      node.innerHTML = '<p class="muted-note">暂无关联规则</p>';
      return;
    }
    const rows = items.map(function (rule) {
      return '<tr><td>' + esc(rule.antecedent) + ' → ' + esc(rule.consequent) + '</td>' +
        '<td>' + (Number(rule.support) * 100).toFixed(1) + '%</td>' +
        '<td>' + (Number(rule.confidence) * 100).toFixed(0) + '%</td>' +
        '<td>' + Number(rule.lift).toFixed(1) + '</td></tr>';
    }).join("");
    node.innerHTML = '<table class="rule-grid"><thead><tr><th>规则</th><th>支持度</th><th>置信度</th><th>提升度</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table>';
  }

  function bindLinks() {
    document.querySelectorAll("#pane-insights [data-id]").forEach(function (node) {
      node.addEventListener("click", function () {
        const id = node.dataset.id;
        if (id) location.hash = "#/teacher/" + encodeURIComponent(id);
      });
    });
  }

  function render(data) {
    loaded = true;
    lastData = data;
    renderColleges(data.colleges || []);
    renderCoverage(data.coverage || []);
    renderScores(data.scores || { histogram: { labels: [], original: [], improved: [] } });
    renderClusters(data.clusters || []);
    renderCommunities(data.community_count || 0, data.communities || []);
    renderRules(data.rules || []);
    bindLinks();
  }

  function load() {
    if (loaded || loading) return;
    loading = true;
    fetch("/api/insights")
      .then(function (response) {
        if (!response.ok) throw new Error("insights " + response.status);
        return response.json();
      })
      .then(render)
      .catch(function () {
        const node = document.getElementById("insight-clusters");
        if (node) node.innerHTML = '<p class="muted-note">数据洞察加载失败，请刷新重试</p>';
      })
      .finally(function () { loading = false; });
  }

  window.MentorInsights = {
    render: function () {
      if (!loaded) load();
      // 容器由隐藏变为可见后再 resize，避免 ECharts 以 0 宽高初始化
      requestAnimationFrame(function () {
        charts.forEach(function (instance) {
          try { instance.resize(); } catch (err) { /* 忽略 */ }
        });
      });
    },
  };

  window.addEventListener("resize", function () {
    charts.forEach(function (instance) {
      try { instance.resize(); } catch (err) { /* 忽略 */ }
    });
  });

  // 切换深浅色后，图表颜色取自 CSS 变量，需要按新主题重绘一次
  const themeToggle = document.getElementById("theme-toggle");
  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      setTimeout(function () {
        if (loaded && lastData) render(lastData);
      }, 0);
    });
  }
})();
