/* 搜索补全 + 最近检索：输入即给出导师建议，空输入时显示最近 6 条检索。 */
(function () {
  "use strict";

  const input = document.getElementById("search-input");
  const form = document.getElementById("search-form");
  const box = document.getElementById("search-suggest");
  if (!input || !form || !box) return;

  const RECENT_KEY = "mentor-recent-searches";
  const MAX_RECENT = 6;
  let items = [];
  let active = -1;
  let timer = null;
  let requestId = 0;
  let composing = false;

  function readRecent() {
    try {
      const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(raw) ? raw.filter((item) => typeof item === "string" && item.trim()) : [];
    } catch (err) {
      return [];
    }
  }

  function saveRecent(query) {
    const value = String(query || "").trim();
    if (!value) return;
    const list = readRecent().filter((item) => item !== value);
    list.unshift(value);
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, MAX_RECENT)));
    } catch (err) {
      /* 隐私模式下写入失败时静默降级 */
    }
  }

  function clearRecent() {
    try { localStorage.removeItem(RECENT_KEY); } catch (err) { /* 忽略 */ }
    if (!input.value.trim()) showRecent();
  }

  function open() {
    box.classList.remove("hidden");
    input.setAttribute("aria-expanded", "true");
  }

  function close() {
    box.classList.add("hidden");
    box.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    active = -1;
    items = [];
  }

  function choose(value) {
    saveRecent(value);
    input.value = value;
    const clear = document.getElementById("clear-btn");
    if (clear) clear.hidden = false;
    close();
    form.requestSubmit();
  }

  function makeRow(options) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sg-item";
    button.setAttribute("role", "option");
    button.dataset.value = options.value;
    if (options.teacherId) button.dataset.teacher = String(options.teacherId);

    const avatar = document.createElement("span");
    avatar.className = "sg-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = options.avatar || "?";

    const main = document.createElement("span");
    main.className = "sg-main";
    const name = document.createElement("b");
    name.className = "sg-name";
    name.textContent = options.title;
    const meta = document.createElement("span");
    meta.className = "sg-meta";
    meta.textContent = options.meta || "";
    main.append(name, meta);

    const score = document.createElement("span");
    score.className = "sg-score";
    score.textContent = options.score || "";

    button.append(avatar, main, score);
    button.addEventListener("click", () => {
      if (options.onChoose) options.onChoose();
      else choose(options.value);
    });
    return button;
  }

  function showRecent() {
    const recent = readRecent();
    if (!recent.length) {
      close();
      return;
    }
    box.innerHTML = "";
    const head = document.createElement("div");
    head.className = "sg-label";
    const label = document.createElement("span");
    label.textContent = "最近检索";
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "sg-clear";
    clear.textContent = "清空";
    clear.addEventListener("click", clearRecent);
    head.append(label, clear);
    box.appendChild(head);

    recent.forEach((query) => {
      box.appendChild(makeRow({
        value: query,
        avatar: "↺",
        title: query,
        meta: "点击重新检索",
      }));
    });
    open();
  }

  function renderSuggestions() {
    box.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "sg-empty";
      empty.textContent = "没有匹配的导师，按 Enter 直接搜索";
      box.appendChild(empty);
      open();
      return;
    }
    const head = document.createElement("div");
    head.className = "sg-label";
    const label = document.createElement("span");
    label.textContent = "导师建议";
    const hint = document.createElement("span");
    hint.textContent = "Enter 检索 · ↑↓ 选择";
    head.append(label, hint);
    box.appendChild(head);

    items.forEach((teacher) => {
      box.appendChild(makeRow({
        value: teacher.name || "",
        teacherId: teacher.id,
        avatar: String(teacher.name || "?").charAt(0),
        title: teacher.name || "未命名",
        meta: [teacher.college, teacher.title].filter(Boolean).join(" · "),
        score: teacher.score != null ? Number(teacher.score).toFixed(1) : "",
        onChoose: () => choose(teacher.name || ""),
      }));
    });
    open();
  }

  async function loadSuggestions(query) {
    const token = ++requestId;
    try {
      const response = await fetch("/api/search?q=" + encodeURIComponent(query) + "&size=7&mode=suggest");
      if (!response.ok) throw new Error("search failed");
      const data = await response.json();
      if (token !== requestId || input.value.trim() !== query) return;
      items = Array.isArray(data.items) ? data.items : [];
      active = -1;
      renderSuggestions();
    } catch (err) {
      if (token !== requestId) return;
      close();
    }
  }

  input.addEventListener("compositionstart", () => { composing = true; });
  input.addEventListener("compositionend", () => {
    composing = false;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

  input.addEventListener("input", () => {
    if (composing) return;
    clearTimeout(timer);
    const query = input.value.trim();
    if (!query) {
      requestId += 1;
      items = [];
      showRecent();
      return;
    }
    timer = setTimeout(() => loadSuggestions(query), 170);
  });

  input.addEventListener("focus", () => {
    if (!input.value.trim()) showRecent();
  });

  input.addEventListener("keydown", (event) => {
    const isOpen = !box.classList.contains("hidden");
    if (event.key === "Escape") {
      if (isOpen) {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
      return;
    }
    if (!isOpen) return;
    const rows = Array.from(box.querySelectorAll(".sg-item"));
    if (!rows.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      active = (active + step + rows.length) % rows.length;
      rows.forEach((row, index) => row.classList.toggle("active", index === active));
      rows[active].scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      rows[active].click();
    }
  });

  form.addEventListener("submit", () => {
    saveRecent(input.value);
    close();
  });

  document.addEventListener("click", (event) => {
    if (!box.contains(event.target) && event.target !== input) close();
  });

  // 供命令面板等外部模块调用
  window.MentorRecent = { clear: clearRecent, save: saveRecent, close: close };
})();
