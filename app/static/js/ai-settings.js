/* AI 设置：模型 / 联网搜索配置。密钥只提交给本机 Flask 服务。 */
(function () {
  "use strict";

  const els = {
    badge: document.getElementById("ai-config-badge"),
    base: document.getElementById("ai-api-base"),
    model: document.getElementById("ai-model"),
    apiKey: document.getElementById("ai-api-key"),
    provider: document.getElementById("ai-web-provider"),
    searchKey: document.getElementById("ai-search-key"),
    max: document.getElementById("ai-search-max"),
    enabled: document.getElementById("ai-enabled"),
    webEnabled: document.getElementById("ai-web-enabled"),
    summary: document.getElementById("ai-config-summary"),
    dirty: document.getElementById("ai-dirty"),
    save: document.getElementById("ai-save"),
    test: document.getElementById("ai-test"),
    status: document.getElementById("ai-config-status"),
  };
  if (!els.save) return;

  const state = {
    loaded: false,
    dirty: false,
    saving: false,
    testing: false,
    hasApiKey: false,
    hasSearchKey: false,
  };

  function setStatus(message, type) {
    if (!els.status) return;
    els.status.textContent = message || "";
    els.status.classList.toggle("is-ok", type === "ok");
    els.status.classList.toggle("is-error", type === "error");
  }

  function setDirty(value) {
    state.dirty = Boolean(value);
    if (els.dirty) els.dirty.classList.toggle("hidden", !state.dirty);
  }

  function markDirty() {
    if (state.loaded) setDirty(true);
  }

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = Boolean(busy);
    button.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function clearInvalid() {
    document.querySelectorAll(".ai-field.is-invalid").forEach(function (node) {
      node.classList.remove("is-invalid");
    });
  }

  function invalidate(field, message) {
    clearInvalid();
    if (field) {
      const wrap = field.closest(".ai-field");
      if (wrap) wrap.classList.add("is-invalid");
    }
    setStatus(message, "error");
    if (field && field.focus) field.focus();
    return false;
  }

  function isLocalBase(base) {
    if (!base) return false;
    try {
      const url = new URL(base);
      return ["localhost", "127.0.0.1", "0.0.0.0", "::1"].includes(url.hostname);
    } catch (err) {
      return false;
    }
  }

  function setBadge(config) {
    if (!els.badge) return;
    const ready = config.enabled && config.configured;
    els.badge.textContent = ready ? "已启用" : (config.configured ? "已配置未启用" : "未配置");
    els.badge.classList.toggle("is-ok", ready);
    els.badge.classList.toggle("is-warn", !ready && config.configured);
  }

  function render(config) {
    state.loaded = true;
    state.hasApiKey = Boolean(config.has_api_key);
    state.hasSearchKey = Boolean(config.web_search && config.web_search.has_api_key);
    els.base.value = config.api_base || "";
    els.model.value = config.model || "";
    els.enabled.checked = Boolean(config.enabled);
    els.webEnabled.checked = Boolean(config.web_search && config.web_search.enabled);
    els.provider.value = (config.web_search && config.web_search.provider) || "tavily";
    els.max.value = String((config.web_search && config.web_search.max_results) || 5);
    els.apiKey.value = "";
    els.searchKey.value = "";
    els.apiKey.placeholder = state.hasApiKey ? "已保存，留空不修改" : "输入模型 API Key";
    els.searchKey.placeholder = state.hasSearchKey ? "已保存，留空不修改" : "输入搜索 API Key";
    if (els.summary) {
      els.summary.textContent = config.configured
        ? `模型：${config.model || "未填写"} · 联网：${(config.web_search && config.web_search.provider) || "none"}`
        : "尚未完成模型配置";
    }
    clearInvalid();
    setDirty(false);
    setBadge(config);
  }

  async function request(url, options) {
    const response = await fetch(url, options);
    let payload = null;
    try { payload = await response.json(); } catch (err) { payload = null; }
    if (!response.ok) {
      const message = payload && payload.error ? payload.error.message : `请求失败（${response.status}）`;
      throw new Error(message);
    }
    return payload;
  }

  async function load() {
    try {
      const config = await request("/api/ai/config");
      render(config);
    } catch (err) {
      setStatus(err.message || "读取 AI 配置失败", "error");
    }
  }

  function validate() {
    clearInvalid();
    const base = els.base.value.trim();
    if (!/^https?:\/\//i.test(base)) {
      return invalidate(els.base, "API Base URL 必须以 http:// 或 https:// 开头");
    }
    if (els.enabled.checked && !els.model.value.trim()) {
      return invalidate(els.model, "启用 AI 查询时必须填写模型名称");
    }
    const newApiKey = els.apiKey.value.trim();
    if (els.enabled.checked && !newApiKey && !state.hasApiKey && !isLocalBase(base)) {
      return invalidate(els.apiKey, "启用 AI 查询时必须填写模型 API Key");
    }
    if (els.webEnabled.checked && els.provider.value !== "none" &&
        !els.searchKey.value.trim() && !state.hasSearchKey) {
      return invalidate(els.searchKey, "启用联网补全时必须填写搜索 API Key");
    }
    const max = Number(els.max.value);
    if (!Number.isInteger(max) || max < 1 || max > 10) {
      return invalidate(els.max, "每次网页结果数必须是 1–10 的整数");
    }
    return true;
  }

  async function save() {
    if (state.saving || state.testing) return;
    if (!validate()) return;
    state.saving = true;
    setBusy(els.save, true);
    setBusy(els.test, true);
    setStatus("正在保存…");
    const payload = {
      enabled: els.enabled.checked,
      api_base: els.base.value.trim(),
      model: els.model.value.trim(),
      api_key: els.apiKey.value.trim(),
      web_search: {
        enabled: els.webEnabled.checked,
        provider: els.provider.value,
        api_key: els.searchKey.value.trim(),
        max_results: Number(els.max.value || 5),
      },
    };
    try {
      const result = await request("/api/ai/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      render(result.config);
      setStatus("配置已保存", "ok");
    } catch (err) {
      setStatus(err.message || "保存失败", "error");
    } finally {
      state.saving = false;
      setBusy(els.save, false);
      setBusy(els.test, false);
    }
  }

  async function test() {
    if (state.saving || state.testing) return;
    if (!validate()) return;
    state.testing = true;
    setBusy(els.save, true);
    setBusy(els.test, true);
    setStatus("正在测试模型与搜索…");
    try {
      const result = await request("/api/ai/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const search = result.result && result.result.search;
      const text = search
        ? `模型连接成功；联网搜索返回 ${search.count} 条结果`
        : "模型连接成功；联网搜索未启用";
      setStatus(text, "ok");
    } catch (err) {
      setStatus(err.message || "连接测试失败", "error");
    } finally {
      state.testing = false;
      setBusy(els.save, false);
      setBusy(els.test, false);
    }
  }

  [els.base, els.model, els.apiKey, els.provider, els.searchKey, els.max,
    els.enabled, els.webEnabled].forEach(function (field) {
    if (!field) return;
    field.addEventListener("input", markDirty);
    field.addEventListener("change", markDirty);
  });
  els.save.addEventListener("click", save);
  els.test.addEventListener("click", test);
  window.addEventListener("beforeunload", function (event) {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  window.MentorAIConfig = {
    load: load,
    reset: load,
    isLoaded: function () { return state.loaded; },
    isDirty: function () { return state.dirty; },
    openSettings: function () {
      if (window.MentorSettings) window.MentorSettings.open();
    },
  };
  load();
})();
