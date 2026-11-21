"use strict";

/* 设置抽屉里的 API 配置：站点、模型、Key 与连接测试。 */
(function () {
  const el = {
    enabled: document.getElementById("ai-api-enabled"),
    base: document.getElementById("ai-api-base"),
    model: document.getElementById("ai-api-model"),
    key: document.getElementById("ai-api-key"),
    save: document.getElementById("ai-api-save"),
    test: document.getElementById("ai-api-test"),
    status: document.getElementById("ai-api-status"),
  };
  if (!el.save) return;

  function setStatus(text, kind) {
    el.status.textContent = text || "";
    if (kind) {
      el.status.dataset.kind = kind;
    } else {
      delete el.status.dataset.kind;
    }
  }

  function fill(settings, status) {
    settings = settings || {};
    el.enabled.checked = !!settings.enabled;
    el.base.value = settings.base_url || "";
    el.model.value = settings.model || "";
    el.key.value = "";
    el.key.placeholder = settings.has_key
      ? t("settings.ai.keySaved", { hint: settings.key_hint || "" })
      : "sk-...";

    if (status && status.mode === "api") {
      setStatus(t("settings.ai.testOk") + " · " + (status.name || ""), "ok");
    } else if (status && status.reason) {
      setStatus(status.reason, "");
    } else {
      setStatus("", "");
    }
  }

  async function load() {
    try {
      const res = await fetch("/api/chat/settings");
      const data = await res.json();
      fill(data.settings, data.status);
    } catch (err) {
      setStatus(t("settings.ai.loadFailed"), "error");
    }
  }

  async function save(silent) {
    const payload = {
      enabled: el.enabled.checked,
      base_url: el.base.value.trim(),
      model: el.model.value.trim(),
      api_key: el.key.value.trim(),
    };
    try {
      const res = await fetch("/api/chat/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      fill(data.settings, data.status);
      if (!silent) setStatus(t("settings.ai.saved"), "ok");
      if (window.ChatUI && ChatUI.refreshStatus) ChatUI.refreshStatus();
      return true;
    } catch (err) {
      setStatus(t("settings.ai.saveFailed"), "error");
      return false;
    }
  }

  async function test() {
    if (el.key.value.trim()) await save(true);
    setStatus(t("settings.ai.testing"), "");
    el.test.disabled = true;
    try {
      const res = await fetch("/api/chat/test", { method: "POST" });
      const data = await res.json();
      if (data.ok) {
        setStatus(t("settings.ai.testOk") + " · " + (data.latency_ms || 0) + " ms", "ok");
      } else {
        setStatus(t("settings.ai.testFail") + " · " + (data.message || ""), "error");
      }
    } catch (err) {
      setStatus(t("settings.ai.testFail"), "error");
    } finally {
      el.test.disabled = false;
    }
  }

  el.save.addEventListener("click", function () { save(false); });
  el.test.addEventListener("click", test);
  load();
})();
