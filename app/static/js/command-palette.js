/* 命令面板：Ctrl/Cmd + K 打开；支持页面切换、收藏、设置、主题和导师直达。 */
(function () {
  "use strict";

  const backdrop = document.getElementById("command-backdrop");
  const modal = document.getElementById("command-palette");
  const input = document.getElementById("command-input");
  const list = document.getElementById("command-list");
  if (!backdrop || !modal || !input || !list) return;

  let active = 0;
  let rows = [];
  let teacherResults = [];
  let timer = null;
  let requestId = 0;

  function activateTab(name) {
    if (window.MentorTabs && typeof window.MentorTabs.activate === "function") {
      window.MentorTabs.activate(name);
    }
  }

  const commands = [
    {
      label: "搜索导师", hint: "聚焦搜索框", icon: "⌕", keywords: "search 搜索 查询",
      run() {
        activateTab("search");
        const search = document.getElementById("search-input");
        if (search) { search.focus(); search.select(); }
      },
    },
    {
      label: "导师名录", hint: "浏览全部教师", icon: "▤", keywords: "directory 名录 列表 教师",
      run() { activateTab("directory"); },
    },
    {
      label: "数据概况", hint: "评分分布与聚类", icon: "◔", keywords: "insights 数据 洞察 统计",
      run() { activateTab("insights"); },
    },
    {
      label: "我的收藏", hint: "收藏与对比", icon: "★", keywords: "favorite shortlist 收藏 对比",
      run() { if (window.MentorShortlist) window.MentorShortlist.open(); },
    },
    {
      label: "打开设置", hint: "外观与项目说明", icon: "⚙", keywords: "settings 设置 主题 关于",
      run() { if (window.MentorSettings) window.MentorSettings.open(); },
    },
    {
      label: "切换深浅色", hint: "跟随当前主题", icon: "◐", keywords: "theme dark light 主题 深色 浅色",
      run() {
        const toggle = document.getElementById("theme-toggle");
        if (toggle) toggle.click();
      },
    },
    {
      label: "清空最近检索", hint: "只清除本地记录", icon: "⌫", keywords: "recent clear 最近 清空",
      run() { if (window.MentorRecent) window.MentorRecent.clear(); },
    },
    {
      label: "复制当前页面链接", hint: "含检索与筛选参数", icon: "⧉", keywords: "copy link 复制 链接 分享",
      run() {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(location.href).catch(() => {});
        }
      },
    },
  ];

  function close() {
    backdrop.classList.add("hidden");
    modal.classList.add("hidden");
    document.body.classList.remove("overlay-open");
    input.value = "";
    teacherResults = [];
  }

  function open() {
    if (window.MentorShortlist) window.MentorShortlist.close();
    if (window.MentorSettings) window.MentorSettings.close();
    backdrop.classList.remove("hidden");
    modal.classList.remove("hidden");
    document.body.classList.add("overlay-open");
    input.value = "";
    teacherResults = [];
    render("");
    requestAnimationFrame(() => input.focus());
  }

  function makeRow(item) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "command-item";

    const main = document.createElement("span");
    main.className = "command-item-main";
    const icon = document.createElement("span");
    icon.className = "command-icon";
    icon.textContent = item.icon || "·";
    const label = document.createElement("span");
    label.className = "command-label";
    label.textContent = item.label;
    main.append(icon, label);

    const hint = document.createElement("span");
    hint.className = "command-hint";
    hint.textContent = item.hint || "";
    button.append(main, hint);
    button.addEventListener("click", () => runItem(item));
    return button;
  }

  function setActive(index) {
    active = index;
    Array.from(list.querySelectorAll(".command-item")).forEach((item, idx) => {
      item.classList.toggle("active", idx === active);
    });
    const current = list.querySelectorAll(".command-item")[active];
    if (current) current.scrollIntoView({ block: "nearest" });
  }

  function render(query) {
    const keyword = query.trim().toLowerCase();
    rows = [];

    if (keyword) {
      rows.push({
        icon: "⌕",
        label: `搜索「${query.trim()}」`,
        hint: "在导师名录中检索",
        run() { submitSearch(query.trim()); },
      });
    }

    commands.forEach((command) => {
      const haystack = (command.label + " " + command.hint + " " + command.keywords).toLowerCase();
      if (!keyword || haystack.includes(keyword)) rows.push(command);
    });

    teacherResults.forEach((teacher) => {
      rows.push({
        icon: String(teacher.name || "?").charAt(0),
        label: teacher.name || "未命名导师",
        hint: [teacher.college, teacher.title].filter(Boolean).join(" · ") || "打开档案",
        run() {
          const url = new URL(location.href);
          url.searchParams.set("teacher", String(teacher.id));
          url.searchParams.delete("view");
          url.searchParams.delete("sub");
          url.hash = "#/teacher/" + encodeURIComponent(teacher.id);
          location.href = url.href;
        },
      });
    });

    list.innerHTML = "";
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "sg-empty";
      empty.textContent = "没有匹配的命令或导师";
      list.appendChild(empty);
      active = 0;
      return;
    }
    rows.forEach((item) => list.appendChild(makeRow(item)));
    setActive(0);
  }

  function runItem(item) {
    close();
    if (item && typeof item.run === "function") item.run();
  }

  function submitSearch(value) {
    activateTab("directory");
    const search = document.getElementById("search-input");
    const form = document.getElementById("search-form");
    const clear = document.getElementById("clear-btn");
    if (search) search.value = value;
    if (clear) clear.hidden = false;
    if (window.MentorRecent) window.MentorRecent.save(value);
    if (form) form.requestSubmit();
    else if (search) search.focus();
  }

  async function loadTeachers(query) {
    const token = ++requestId;
    try {
      const response = await fetch("/api/search?q=" + encodeURIComponent(query) + "&size=5&mode=command");
      if (!response.ok) throw new Error("failed");
      const data = await response.json();
      if (token !== requestId) return;
      teacherResults = Array.isArray(data.items) ? data.items.slice(0, 5) : [];
    } catch (err) {
      if (token !== requestId) return;
      teacherResults = [];
    }
    render(input.value);
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const value = input.value.trim();
    if (!value) {
      requestId += 1;
      teacherResults = [];
      render("");
      return;
    }
    render(value);
    timer = setTimeout(() => loadTeachers(value), 180);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!rows.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((active + step + rows.length) % rows.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      runItem(rows[active]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  });

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (modal.classList.contains("hidden")) open();
      else close();
    } else if (event.key === "Escape" && !modal.classList.contains("hidden")) {
      close();
    }
  });

  backdrop.addEventListener("click", close);
  const trigger = document.getElementById("command-trigger");
  if (trigger) trigger.addEventListener("click", open);

  const resultsList = document.getElementById("results-list");
  if (resultsList) {
    // 结果列表更新时，若面板已打开并有输入，刷新导师结果。
    new MutationObserver(() => {
      if (modal.classList.contains("hidden") || !input.value.trim()) return;
      clearTimeout(timer);
      timer = setTimeout(() => loadTeachers(input.value.trim()), 240);
    }).observe(resultsList, { childList: true, subtree: true });
  }

  window.MentorCommandPalette = { open, close };
})();
