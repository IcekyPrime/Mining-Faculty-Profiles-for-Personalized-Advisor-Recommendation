/* 移动端离线 API：拦截桌面端 app.js 的 /api/* 请求，用内置数据在本地实现。 */
(function () {
  "use strict";

  var D = window.__MOBILE_DATA__ || { stats: {}, insights: {}, teachers: [], details: {} };
  var originalFetch = window.fetch ? window.fetch.bind(window) : null;

  function jsonResponse(obj, status) {
    status = status || 200;
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status: status,
      json: function () { return Promise.resolve(obj); },
      text: function () { return Promise.resolve(JSON.stringify(obj)); }
    });
  }

  function byName(a, b) {
    var x = a.name || "";
    var y = b.name || "";
    return x < y ? -1 : (x > y ? 1 : 0);
  }

  function fieldNum(v) {
    if (v == null || v === "") return null;
    var n = Number(v);
    return isNaN(n) ? null : n;
  }

  /* 与桌面端 app.py 的排序口径一致：缺失值最后，再按次级指标排序 */
  function compare(sort) {
    if (sort === "relevance") {
      return function (a, b) {
        return (b.relevance - a.relevance) || byName(a, b);
      };
    }
    if (sort === "academic") {
      return function (a, b) {
        var ah = fieldNum(a.h_index), bh = fieldNum(b.h_index);
        if ((ah == null) !== (bh == null)) return ah == null ? 1 : -1;
        if ((bh || 0) !== (ah || 0)) return (bh || 0) - (ah || 0);
        return (fieldNum(b.citation_count) || 0) - (fieldNum(a.citation_count) || 0);
      };
    }
    if (sort === "teaching") {
      return function (a, b) {
        var ar = a.rating || {}, br = b.rating || {};
        var aa = fieldNum(ar.avg), ba = fieldNum(br.avg);
        if ((aa == null) !== (ba == null)) return aa == null ? 1 : -1;
        if ((ba || 0) !== (aa || 0)) return (ba || 0) - (aa || 0);
        return (br.count || 0) - (ar.count || 0);
      };
    }
    return function (a, b) {
      var as = fieldNum(a.score), bs = fieldNum(b.score);
      if ((as == null) !== (bs == null)) return as == null ? 1 : -1;
      if ((bs || 0) !== (as || 0)) return (bs || 0) - (as || 0);
      return (fieldNum(b.h_index) || 0) - (fieldNum(a.h_index) || 0);
    };
  }

  function search(params) {
    var q = (params.get("q") || "").trim();
    var college = (params.get("college") || "").trim();
    var sort = params.get("sort") || "score";
    if (["score", "academic", "teaching", "relevance"].indexOf(sort) < 0) sort = "score";
    var page = Math.max(parseInt(params.get("page") || "1", 10) || 1, 1);
    var size = Math.min(Math.max(parseInt(params.get("size") || "20", 10) || 20, 1), 100);

    var results = D.teachers.slice().sort(byName).map(function (t) {
      var item = {};
      for (var k in t) if (Object.prototype.hasOwnProperty.call(t, k)) item[k] = t[k];
      item.relevance = 0;
      return item;
    });

    if (q) {
      var ql = q.toLowerCase();
      results.forEach(function (it) {
        var name = it.name || "";
        if (name === q) it.relevance = 100;
        else if (name.indexOf(q) >= 0) it.relevance = 85;
        else if ((it.name_pinyin || "").toLowerCase().indexOf(ql) >= 0) it.relevance = 75;
        else if ((it.keywords || []).some(function (kw) { return kw.indexOf(q) >= 0; })) it.relevance = 60;
        else if ((it.research_directions || "").indexOf(q) >= 0) it.relevance = 50;
        else if ((it.institute || "").indexOf(q) >= 0) it.relevance = 30;
        else if ((it.title || "").indexOf(q) >= 0) it.relevance = 20;
      });
      results = results.filter(function (r) { return r.relevance > 0; });
    }

    if (college) {
      results = results.filter(function (r) { return r.college === college; });
    }

    results.sort(compare(sort));
    var total = results.length;
    var start = (page - 1) * size;
    return {
      total: total,
      page: page,
      size: size,
      pages: Math.ceil(total / size),
      sort: sort,
      items: results.slice(start, start + size)
    };
  }

  window.fetch = function (url, options) {
    var u = String(url || "");
    if (u.indexOf("/api/") !== 0) {
      return originalFetch ? originalFetch(url, options) : jsonResponse({}, 404);
    }
    var parts = u.split("?");
    var path = parts[0];
    var params = new URLSearchParams(parts[1] || "");

    if (path === "/api/stats") return jsonResponse(D.stats);
    if (path === "/api/colleges") return jsonResponse((D.stats || {}).colleges || []);
    if (path === "/api/insights") return jsonResponse(D.insights || {});
    if (path === "/api/search") return jsonResponse(search(params));

    var m = path.match(/^\/api\/teacher\/(\d+)$/);
    if (m) {
      var detail = (D.details || {})[m[1]];
      return detail ? jsonResponse(detail) : jsonResponse({ error: "not found" }, 404);
    }
    return jsonResponse({ error: "not found" }, 404);
  };
})();
