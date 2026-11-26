"use strict";

/* ---------------------------------------------------------------- AI 对话抽屉
   停靠底部，可拖动三角手柄展开；展开后高度止于顶栏下沿。
   与现有界面共用设计令牌，因此自动支持深浅色与中英文切换。
*/
(function () {
  const sheet = document.getElementById("ai-sheet");
  if (!sheet) return;

  const el = {
    handle: document.getElementById("ai-handle"),
    tri: document.getElementById("ai-tri"),
    engine: document.getElementById("ai-engine"),
    messages: document.getElementById("ai-messages"),
    suggest: document.getElementById("ai-suggest"),
    form: document.getElementById("ai-form"),
    input: document.getElementById("ai-input"),
    online: document.getElementById("ai-online"),
    send: document.getElementById("ai-send"),
    clear: document.getElementById("ai-clear"),
  };

  const PEEK = 60;
  let sheetState = "peek";
  let chat = [];
  let historyPromise = null;
  let busy = false;
  let drag = null;
  let lastSuggestions = [];
  let engineInfo = { mode: "rule", name: "" };

  /* 浏览器或桌面壳里都保留同一个客户端 ID，避免 Cookie 丢失后历史断开 */
  function clientId() {
    let value = "";
    try { value = localStorage.getItem("ai_cid") || ""; } catch (err) { value = ""; }
    if (/^[0-9a-f]{32}$/.test(value)) return value;
    const bytes = new Uint8Array(16);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    }
    value = Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
    try { localStorage.setItem("ai_cid", value); } catch (err) { /* 忽略 */ }
    return value;
  }

  const CLIENT_ID = clientId();

  function apiFetch(url, options) {
    const opts = options || {};
    const headers = Object.assign({}, opts.headers || {}, { "X-Client-Id": CLIENT_ID });
    return fetch(url, Object.assign({}, opts, { headers: headers }));
  }

  function viewportH() {
    return window.innerHeight || document.documentElement.clientHeight;
  }

  function topbarH() {
    const bar = document.querySelector(".topbar");
    return bar ? Math.round(bar.getBoundingClientRect().height) : 60;
  }

  function snapHeight(name) {
    if (name === "peek") return PEEK;
    if (name === "full") return Math.max(260, viewportH() - topbarH());
    return Math.max(320, Math.min(560, Math.round(viewportH() * 0.58)));
  }

  function setState(name) {
    sheetState = name;
    sheet.dataset.state = name;
    sheet.style.height = snapHeight(name) + "px";
    el.tri.setAttribute("aria-expanded", name === "peek" ? "false" : "true");
    el.tri.setAttribute("aria-label", name === "peek" ? t("chat.expand") : t("chat.collapse"));
    if (name !== "peek") {
      ensureHistory();
      setTimeout(() => el.input.focus(), 260);
    }
    scrollBottom();
  }

  function toggle() {
    if (sheetState === "peek") setState("half");
    else if (sheetState === "half") setState("peek");
    else setState("half");
  }

  function scrollBottom() {
    if (el.messages) el.messages.scrollTop = el.messages.scrollHeight;
  }

  /* ---------------------------------------------------------------- 拖动 */
  function onDown(e) {
    if (e.button != null && e.button !== 0) return;
    drag = {
      y: e.clientY,
      height: sheet.getBoundingClientRect().height,
      moved: false,
      dy: 0,
    };
    sheet.dataset.dragging = "true";
    try { el.handle.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
    e.preventDefault();
  }

  function onMove(e) {
    if (!drag) return;
    drag.dy = drag.y - e.clientY;
    if (Math.abs(drag.dy) > 4) drag.moved = true;
    const h = Math.max(PEEK, Math.min(snapHeight("full"), drag.height + drag.dy));
    sheet.style.height = h + "px";
    sheet.dataset.state = h > snapHeight("full") * 0.9 ? "full"
      : (h > PEEK + 28 ? "half" : "peek");
  }

  function onUp() {
    if (!drag) return;
    const moved = drag.moved;
    const dy = drag.dy;
    const h = sheet.getBoundingClientRect().height;
    drag = null;
    sheet.dataset.dragging = "false";
    if (!moved) {
      toggle();
      return;
    }
    const options = [["peek", PEEK], ["half", snapHeight("half")], ["full", snapHeight("full")]];
    let best = "peek";
    let dist = Infinity;
    options.forEach(opt => {
      const d = Math.abs(opt[1] - h);
      if (d < dist) { dist = d; best = opt[0]; }
    });
    if (dy > 48 && best === "peek" && h > PEEK + 24) best = "half";
    if (dy < -48 && best === "full" && h < snapHeight("full") - 24) best = "half";
    setState(best);
  }

  /* ---------------------------------------------------------------- 渲染 */
  function welcomeNode() {
    const wrap = document.createElement("div");
    wrap.className = "ai-msg assistant";
    const bubble = document.createElement("div");
    bubble.className = "ai-bubble";
    bubble.textContent = t("chat.welcome");
    wrap.appendChild(bubble);
    return wrap;
  }

  function cardNode(card) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ai-card";
    btn.dataset.teacher = card.id;

    const name = document.createElement("b");
    name.textContent = card.name || "";
    const meta = document.createElement("span");
    meta.textContent = [card.college, card.title].filter(Boolean).join(" · ");
    const hint = document.createElement("em");
    hint.textContent = t("chat.card.open");
    btn.append(name, meta, hint);
    return btn;
  }

  function sourceNode(source) {
    const url = source.url || "";
    const local = url.indexOf("/api/teacher/") === 0;
    const node = document.createElement(local ? "button" : "a");
    node.className = "ai-source";
    node.textContent = source.label || url;
    if (local) {
      node.type = "button";
      node.dataset.teacher = url.split("/").pop();
    } else {
      node.href = url;
      node.target = "_blank";
      node.rel = "noopener";
    }
    return node;
  }

  function messageNode(msg) {
    const wrap = document.createElement("div");
    wrap.className = "ai-msg " + (msg.role === "user" ? "user" : "assistant");

    const bubble = document.createElement("div");
    bubble.className = "ai-bubble";
    bubble.textContent = msg.content || "";
    wrap.appendChild(bubble);

    const meta = msg.meta || {};
    if (meta.cards && meta.cards.length) {
      const cards = document.createElement("div");
      cards.className = "ai-cards";
      meta.cards.forEach(card => cards.appendChild(cardNode(card)));
      wrap.appendChild(cards);
    }
    if (meta.sources && meta.sources.length) {
      const sources = document.createElement("div");
      sources.className = "ai-sources";
      meta.sources.forEach(src => sources.appendChild(sourceNode(src)));
      wrap.appendChild(sources);
    }
    if (meta.notes && meta.notes.length) {
      const notes = document.createElement("div");
      notes.className = "ai-notes";
      meta.notes.forEach(text => {
        const line = document.createElement("span");
        line.textContent = text;
        notes.appendChild(line);
      });
      wrap.appendChild(notes);
    }
    return wrap;
  }

  function pendingNode() {
    const wrap = document.createElement("div");
    wrap.className = "ai-msg assistant";
    const bubble = document.createElement("div");
    bubble.className = "ai-bubble ai-pending";
    bubble.textContent = t("chat.thinking");
    wrap.appendChild(bubble);
    return wrap;
  }

  function renderSuggest(list) {
    lastSuggestions = list || [];
    el.suggest.innerHTML = "";
    lastSuggestions.forEach(text => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "ai-chip";
      chip.textContent = text;
      el.suggest.appendChild(chip);
    });
    el.suggest.classList.toggle("hidden", !lastSuggestions.length);
  }

  function defaultSuggestions() {
    return [t("chat.suggest.1"), t("chat.suggest.2"), t("chat.suggest.3")];
  }

  function renderAll() {
    el.messages.innerHTML = "";
    if (!chat.length) {
      el.messages.appendChild(welcomeNode());
      renderSuggest(defaultSuggestions());
    } else {
      chat.forEach(msg => el.messages.appendChild(messageNode(msg)));
      renderSuggest(lastSuggestions.length ? lastSuggestions : defaultSuggestions());
    }
    scrollBottom();
  }

  function pushMessage(msg) {
    chat.push(msg);
    el.messages.appendChild(messageNode(msg));
    if (msg.meta && msg.meta.suggestions) renderSuggest(msg.meta.suggestions);
    scrollBottom();
  }

  /* ---------------------------------------------------------------- 数据 */
  function ensureHistory() {
    if (!historyPromise) historyPromise = loadHistory();
    return historyPromise;
  }

  async function loadHistory() {
    try {
      const res = await apiFetch("/api/chat/history?limit=40");
      const data = await res.json();
      (data.messages || []).forEach(msg => chat.push(msg));
    } catch (err) { /* 无历史时保持欢迎页 */ }
    renderAll();
  }

  async function loadStatus() {
    try {
      const res = await apiFetch("/api/chat/status");
      const data = await res.json();
      if (data.engine) setEngine(data.engine);
    } catch (err) { /* 状态不可用时不阻塞对话 */ }
  }

  function setEngine(info) {
    engineInfo = info || { mode: "rule", name: "" };
    if ((engineInfo.mode === "model" || engineInfo.mode === "api") && engineInfo.name) {
      el.engine.textContent = engineInfo.preset || engineInfo.name;
      el.engine.title = engineInfo.base_url ||
        (engineInfo.name + (engineInfo.size_mb ? " · " + engineInfo.size_mb + " MB" : ""));
      el.engine.dataset.mode = "model";
    } else {
      el.engine.textContent = t("chat.engine.rule");
      el.engine.title = engineInfo.reason || t("chat.engine.rule.hint");
      el.engine.dataset.mode = "rule";
    }
  }

  function setBusy(value) {
    busy = value;
    el.send.disabled = value;
    el.form.setAttribute("aria-busy", value ? "true" : "false");
  }

  async function send(text) {
    const content = String(text || "").trim();
    if (!content || busy) return;
    if (sheetState === "peek") setState("half");

    setBusy(true);
    await ensureHistory();
    pushMessage({ role: "user", content: content });
    const pending = pendingNode();
    el.messages.appendChild(pending);
    scrollBottom();

    try {
      const res = await apiFetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: content,
          lang: currentLang,
          online: !!(el.online && el.online.checked),
        }),
      });
      const data = await res.json();
      pending.remove();
      if (!data.ok) throw new Error(data.error || "request failed");

      pushMessage({
        role: "assistant",
        content: data.reply,
        meta: {
          cards: data.cards || [],
          sources: data.sources || [],
          suggestions: data.suggestions || [],
          notes: data.notes || [],
          intent: data.intent,
        },
      });
      if (data.engine) setEngine(data.engine);
    } catch (err) {
      pending.remove();
      pushMessage({ role: "assistant", content: t("chat.error"), meta: {} });
    } finally {
      setBusy(false);
      el.input.focus();
      scrollBottom();
    }
  }

  function submitText() {
    const value = el.input.value;
    el.input.value = "";
    autoGrow();
    send(value);
  }

  function autoGrow() {
    el.input.style.height = "auto";
    el.input.style.height = Math.min(el.input.scrollHeight, 108) + "px";
  }

  /* ---------------------------------------------------------------- 事件 */
  el.handle.addEventListener("pointerdown", onDown);
  el.handle.addEventListener("pointermove", onMove);
  el.handle.addEventListener("pointerup", onUp);
  el.handle.addEventListener("pointercancel", onUp);
  el.tri.addEventListener("click", e => {
    // 指针操作已在 pointerup 处理，这里只补键盘触发的点击
    if (e.detail === 0) {
      e.preventDefault();
      toggle();
    }
  });

  el.form.addEventListener("submit", e => {
    e.preventDefault();
    submitText();
  });
  el.input.addEventListener("input", autoGrow);
  el.input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submitText();
    }
  });

  el.suggest.addEventListener("click", e => {
    const chip = e.target.closest(".ai-chip");
    if (chip) send(chip.textContent);
  });

  el.messages.addEventListener("click", e => {
    const node = e.target.closest("[data-teacher]");
    if (!node) return;
    const tid = Number(node.dataset.teacher);
    if (!tid) return;
    setState("peek");
    if (typeof openDetail === "function") openDetail(tid);
  });

  el.clear.addEventListener("click", async () => {
    if (!window.confirm(t("chat.clear.confirm"))) return;
    try {
      await apiFetch("/api/chat/clear", { method: "POST" });
    } catch (err) { /* 忽略网络错误 */ }
    chat = [];
    lastSuggestions = [];
    historyPromise = Promise.resolve();
    renderAll();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && sheetState !== "peek") setState("peek");
  });

  window.addEventListener("resize", () => {
    if (sheetState !== "peek") sheet.style.height = snapHeight(sheetState) + "px";
  });

  /* ---------------------------------------------------------------- 对外 */
  window.ChatUI = {
    refresh: function () {
      setEngine(engineInfo);
      el.tri.setAttribute("aria-label", sheetState === "peek" ? t("chat.expand") : t("chat.collapse"));
      if (!chat.length) renderAll();
      else renderSuggest(lastSuggestions.length ? lastSuggestions : defaultSuggestions());
    },
    open: function () {
      if (sheetState === "peek") setState("half");
    },
    refreshStatus: function () {
      return loadStatus();
    },
  };

  setState("peek");
  renderAll();
  loadStatus();
  el.tri.setAttribute("aria-label", t("chat.expand"));
})();
