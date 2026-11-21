"use strict";

/* ================================================================
   交我导 · 移动端 AI 助手
   使用离线教师数据做规则检索与模板回答
   ================================================================ */
(function () {
  const sheet = document.getElementById("ai-sheet");
  if (!sheet) return;

  const DATA = window.__MOBILE_DATA__ || { teachers: [], details: {} };
  const TEACHERS = Array.isArray(DATA.teachers) ? DATA.teachers : [];
  const DETAILS = DATA.details || {};

  const HISTORY_KEY = "mobile_ai_history";
  const API_SETTINGS_KEY = "mobile_ai_settings";
  const DEFAULT_API_BASE = "https://api.deepseek.com/v1";
  const DEFAULT_API_MODEL = "deepseek-flash";

  const el = {
    handle: document.getElementById("ai-handle"),
    tri: document.getElementById("ai-tri"),
    engine: document.getElementById("ai-engine"),
    messages: document.getElementById("ai-messages"),
    suggest: document.getElementById("ai-suggest"),
    form: document.getElementById("ai-form"),
    input: document.getElementById("ai-input"),
    send: document.getElementById("ai-send"),
    clear: document.getElementById("ai-clear"),
    apiEnabled: document.getElementById("ai-api-enabled"),
    apiBase: document.getElementById("ai-api-base"),
    apiModel: document.getElementById("ai-api-model"),
    apiKey: document.getElementById("ai-api-key"),
    apiSave: document.getElementById("ai-api-save"),
    apiTest: document.getElementById("ai-api-test"),
    apiStatus: document.getElementById("ai-api-status")
  };

  const PEEK = 60;
  let sheetState = "peek";
  let chat = [];
  let busy = false;
  let drag = null;
  let lastSuggestions = [];
  let apiSettings = loadApiSettings();

  /* ---------------------------------------------------------------- 词典 */
  const ALIASES = {
    "数据挖掘": ["数据挖掘", "知识发现", "data mining", "kdd"],
    "机器学习": ["机器学习", "machine learning"],
    "深度学习": ["深度学习", "deep learning", "神经网络"],
    "人工智能": ["人工智能", "artificial intelligence"],
    "计算机视觉": ["计算机视觉", "图像处理", "图像识别", "图像分割", "computer vision", "image processing"],
    "自然语言处理": ["自然语言处理", "nlp", "大模型", "语言模型"],
    "语音识别": ["语音识别", "语音", "speech", "asr", "speech recognition"],
    "推荐系统": ["推荐系统", "推荐算法", "recommender"],
    "强化学习": ["强化学习", "reinforcement learning"],
    "知识图谱": ["知识图谱", "knowledge graph"],
    "图神经网络": ["图神经网络", "gnn", "graph neural"],
    "芯片设计": ["芯片", "集成电路", "微电子", "vlsi"],
    "电力系统": ["电力系统", "智能电网", "电网"],
    "机器人": ["机器人", "具身智能", "robotics"],
    "操作系统": ["操作系统", "operating system"],
    "网络与信息安全": ["网络安全", "信息安全", "隐私保护", "security", "privacy"],
    "软件工程": ["软件工程", "software engineering", "程序分析"],
    "控制理论": ["控制理论", "自动控制", "control theory"],
    "通信与信号处理": ["通信", "无线", "信号处理", "communication"],
    "数据库": ["数据库", "database"],
    "多模态": ["多模态", "multimodal"]
  };
  const TOO_BROAD = { "计算机": 1, "人工智能": 1, "自动化": 1, "软件": 1, "通信": 1, "电子": 1 };
  const GENERIC_TERMS = {
    "实验室": 1, "课题组": 1, "团队": 1, "研究所": 1, "组里": 1, "同组": 1,
    "同事": 1, "方面": 1, "老师": 1, "导师": 1, "教授": 1,
    "研究方向": 1, "干什么": 1, "做什么": 1, "评价": 1
  };
  const LAB = ["实验室", "课题组", "团队", "组里", "同组", "同事", "研究所",
               "实验组", "lab", "group", "team"];
  const SALARY = ["薪资", "工资", "薪水", "年薪", "收入", "就业", "高薪", "salary", "income", "job", "career"];
  const COMPARE = ["比较", "对比", "区别", "差异", "compare", "difference"];
  const RECENT = ["最近", "近年", "最新", "recent", "latest"];
  const LOOKUP = ["介绍", "是谁", "邮箱", "主页", "怎么样", "研究方向", "方向是什么",
                  "h指数", "h 指数", "职称", "哪个学院", "学院", "课程", "带哪些课",
                  "招生", "名额", "博士", "干什么", "做什么", "干嘛", "研究什么",
                  "做什么的", "评价", "profile", "email", "homepage"];
  const DEPTH = ["深耕", "擅长", "主要研究", "专注", "expert", "focus on"];
  const COLLEGE_SHORT = {
    "计算机学院": ["计算机学院", "计算机系"],
    "自动化与感知学院": ["自动化与感知学院", "自动化系"],
    "集成电路学院": ["集成电路学院", "微电子学院"],
    "电气工程学院": ["电气工程学院", "电气学院"],
    "人工智能学院": ["人工智能学院"]
  };

  const VOCAB = (function () {
    const set = new Set();
    TEACHERS.forEach(function (t) {
      (t.keywords || []).forEach(function (k) {
        if (k && k.length >= 2 && k.length <= 14) set.add(k);
      });
      String(t.research_directions || "").split(/[、,，;；/|]+/).forEach(function (s) {
        s = s.trim();
        if (s.length >= 2 && s.length <= 14) set.add(s);
      });
    });
    return Array.from(set).sort(function (a, b) { return b.length - a.length; });
  })();
  const NAMES = TEACHERS.map(function (t) { return t.name; })
    .filter(Boolean)
    .sort(function (a, b) { return b.length - a.length; });
  const COLLEGES = Array.from(new Set(TEACHERS.map(function (t) { return t.college; }).filter(Boolean)));

  /* ---------------------------------------------------------------- 工具 */
  function contains(hay, needle) {
    if (!hay || !needle) return false;
    return String(hay).toLowerCase().indexOf(String(needle).toLowerCase()) >= 0;
  }

  function unique(list) {
    const out = [];
    list.forEach(function (x) { if (x && out.indexOf(x) < 0) out.push(x); });
    return out;
  }

  function truncate(text, size) {
    text = String(text || "").trim();
    return text.length <= size ? text : text.slice(0, size).replace(/\s+$/, "") + "…";
  }

  function fmt(n) {
    if (n === null || n === undefined || n === "") return "—";
    const value = Number(n);
    if (isNaN(value)) return String(n);
    return value.toLocaleString ? value.toLocaleString() : String(value);
  }

  function surfaces(term) {
    return [term].concat(ALIASES[term] || []);
  }

  function detailsOf(t) {
    return DETAILS[String(t.id)] || {};
  }

  function saveHistory() {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(chat.slice(-40))); } catch (e) { /* 忽略 */ }
  }

  /* ---------------------------------------------------------------- 解析 */
  function findNames(text) {
    const out = [];
    NAMES.forEach(function (name) {
      if (name.length < 2) return;
      if (text.indexOf(name) >= 0 && !out.some(function (x) { return x.indexOf(name) >= 0; })) {
        out.push(name);
      }
    });
    return out.slice(0, 3);
  }

  function findCollege(text) {
    for (let i = 0; i < COLLEGES.length; i += 1) {
      if (text.indexOf(COLLEGES[i]) >= 0) return COLLEGES[i];
    }
    const keys = Object.keys(COLLEGE_SHORT);
    for (let i = 0; i < keys.length; i += 1) {
      if (COLLEGES.indexOf(keys[i]) < 0) continue;
      const shorts = COLLEGE_SHORT[keys[i]];
      for (let j = 0; j < shorts.length; j += 1) {
        if (text.indexOf(shorts[j]) >= 0) return keys[i];
      }
    }
    return "";
  }

  function findTerms(text, names) {
    const out = [];
    Object.keys(ALIASES).forEach(function (key) {
      if (ALIASES[key].some(function (s) { return contains(text, s); })) out.push(key);
    });
    let body = text;
    names.forEach(function (n) { body = body.split(n).join(" "); });
    for (let i = 0; i < VOCAB.length && out.length < 4; i += 1) {
      const term = VOCAB[i];
      if (term.length < 2 || GENERIC_TERMS[term]) continue;
      if (out.some(function (o) { return o.indexOf(term) >= 0 || term.indexOf(o) >= 0; })) continue;
      if (body.indexOf(term) >= 0) out.push(term);
    }
    return out.slice(0, 4);
  }

  function lastCards() {
    for (let i = chat.length - 1; i >= 0; i -= 1) {
      const meta = chat[i].meta;
      if (meta && meta.cards && meta.cards.length) return meta.cards;
    }
    return [];
  }

  function parse(text) {
    const raw = String(text || "").trim();
    const low = raw.toLowerCase();
    let names = findNames(raw);
    const college = findCollege(raw);
    let terms = findTerms(raw, names);
    if (college) terms = terms.filter(function (x) { return !TOO_BROAD[x]; });

    if (!names.length && /这位|那位|他们|她们/.test(raw)) {
      const cards = lastCards();
      if (cards.length) names = [cards[0].name];
    }

    let intent = "recommend";
    if (raw.length <= 14 && /^(你好|您好|hi|hello|hey)/i.test(raw)) {
      intent = "greeting";
    } else if (SALARY.some(function (w) { return contains(low, w); })) {
      intent = "career";
    } else if (names.length && LAB.some(function (w) { return contains(low, w); }) &&
               !COMPARE.some(function (w) { return contains(low, w); })) {
      intent = "lab";
    } else if (COMPARE.some(function (w) { return contains(low, w); }) &&
               (names.length >= 2 || (names.length >= 1 && lastCards().length >= 2))) {
      intent = "compare";
    } else if (names.length && RECENT.some(function (w) { return contains(low, w); })) {
      intent = "recent";
    } else if (names.length && LOOKUP.concat(DEPTH).some(function (w) { return contains(low, w); })) {
      intent = "teacher";
    } else if (DEPTH.some(function (w) { return contains(low, w); })) {
      intent = "experts";
    }

    if (intent === "compare" && names.length < 2) {
      names = lastCards().slice(0, 2).map(function (c) { return c.name; });
    }
    if (intent === "lab") terms = [];
    return { intent: intent, names: names, terms: terms, college: college, topK: 3, raw: raw };
  }

  /* ---------------------------------------------------------------- 检索 */
  function search(terms, college, limit, depth) {
    const out = [];
    TEACHERS.forEach(function (t) {
      if (college && t.college !== college) return;
      if (!terms.length) return;

      let score = 0;
      const dirHits = [];
      const kwHits = [];
      terms.forEach(function (term) {
        surfaces(term).forEach(function (sf) {
          const weight = sf === term ? 1 : 0.5;
          if (contains(t.research_directions, sf)) {
            score += 3 * weight;
            dirHits.push(sf);
          }
          if ((t.keywords || []).some(function (k) { return contains(k, sf); })) {
            score += 2.2 * weight;
            kwHits.push(sf);
          }
        });
      });
      if (score <= 0) return;

      const detail = detailsOf(t);
      const papers = (detail.papers || []).filter(function (p) {
        if (!p.title) return false;
        return terms.some(function (term) {
          return surfaces(term).some(function (sf) { return contains(p.title, sf); });
        });
      });
      score += Math.min(papers.length, 6) * 0.45;

      out.push({
        teacher: t,
        detail: detail,
        score: score,
        dirHits: unique(dirHits).slice(0, 3),
        kwHits: unique(kwHits).slice(0, 3),
        papers: papers.slice(0, 2),
        depth: papers.length
      });
    });

    out.sort(depth
      ? function (a, b) { return (b.depth - a.depth) || (b.score - a.score); }
      : function (a, b) { return b.score - a.score; });
    return out.slice(0, limit);
  }

  function listCollege(college, limit) {
    return TEACHERS.filter(function (t) { return t.college === college; })
      .sort(function (a, b) {
        return ((Number(b.score) || 0) - (Number(a.score) || 0)) ||
          ((Number(b.h_index) || 0) - (Number(a.h_index) || 0));
      })
      .slice(0, limit)
      .map(function (t) {
        return {
          teacher: t,
          detail: detailsOf(t),
          score: 0,
          dirHits: [],
          kwHits: [],
          papers: [],
          depth: 0
        };
      });
  }

  /* ---------------------------------------------------------------- 回答 */
  function cardOf(t) {
    return { id: t.id, name: t.name, college: t.college, title: t.title };
  }

  function entry(item, index, zh) {
    const t = item.teacher;
    const head = (index + 1) + ". " + t.name + " · " + (t.college || "") +
      (t.title ? " · " + t.title : "");
    const lines = [head];
    if (t.research_directions) {
      lines.push((zh ? "   方向：" : "   Areas: ") + truncate(t.research_directions, 60));
    }
    const evidence = [];
    if (item.dirHits.length) {
      evidence.push((zh ? "研究方向命中「" : "area matches \"") +
        item.dirHits.slice(0, 2).join("、") + (zh ? "」" : "\""));
    }
    if (item.kwHits.length) {
      evidence.push((zh ? "关键词命中「" : "keywords match \"") +
        item.kwHits.slice(0, 2).join("、") + (zh ? "」" : "\""));
    }
    if (item.papers.length) {
      const p = item.papers[0];
      evidence.push((zh ? "相关论文：" : "paper: ") + truncate(p.title, 46) +
        (p.year ? "（" + p.year + "）" : ""));
    }
    if (evidence.length) {
      lines.push((zh ? "   依据：" : "   Evidence: ") + evidence.join("；"));
    }
    return lines.join("\n");
  }

  function sourcesOf(cards) {
    const out = [];
    cards.slice(0, 2).forEach(function (card) {
      const detail = DETAILS[String(card.id)] || {};
      const url = detail.personal_homepage || detail.homepage_url;
      if (url) out.push({ label: card.name + " · 主页", url: url });
    });
    return out;
  }

  function answerFor(slots, lang) {
    const zh = lang !== "en";
    const terms = slots.terms.join("、") || (zh ? "该方向" : "that area");

    if (slots.intent === "greeting") {
      return { reply: t("ai.welcome"), cards: [], sources: [], notes: [] };
    }

    if (slots.intent === "career") {
      const text = zh
        ? "本地库没有毕业生薪资、去向或收入数据，无法判断哪位导师“毕业薪资更高”。论文和引用也不能当作薪资证据。\n\n你可以换成具体研究方向，例如“数据挖掘”“芯片设计”，我再按方向筛选。"
        : "The local database has no salary or destination data, so it cannot rank advisors by expected salary. Papers and citations are not salary evidence.\n\nTry a research area instead, such as data mining or chip design.";
      return { reply: text, cards: [], sources: [], notes: [] };
    }

    if (slots.intent === "lab") {
      const name = slots.names[0] || "";
      const teacher = TEACHERS.filter(function (x) { return x.name === name; })[0];
      if (!teacher) {
        return { reply: zh ? "没有在本地库中找到这位教师。" : "I could not find that faculty member locally.",
                 cards: [], sources: [], notes: [] };
      }
      const detail = detailsOf(teacher);
      const institute = teacher.institute || detail.institute || "";
      let mates = [];
      if (institute) {
        mates = TEACHERS.filter(function (x) {
          return x.id !== teacher.id && x.institute === institute;
        }).sort(function (a, b) {
          return (Number(b.score) || 0) - (Number(a.score) || 0);
        }).slice(0, 10);
      }
      const collabs = (detail.collaborators || []).slice(0, 6);

      const lines = [teacher.name + " · " + (teacher.college || "") +
        (teacher.title ? " · " + teacher.title : "")];
      if (detail.bio) {
        const match = String(detail.bio).match(/([A-Za-z][A-Za-z0-9\-& ]{1,30}(?:Lab|LAB|Laboratory))/);
        if (match) lines.push((zh ? "简介中提到的实验室：" : "Lab mentioned in the bio: ") + match[1].trim());
      }
      if (institute) lines.push((zh ? "所在单位：" : "Institute: ") + institute);
      if (mates.length) {
        lines.push((zh ? "同研究所教师（" + mates.length + " 位）：" : "Faculty in the same institute (" + mates.length + "): ") +
          mates.map(function (m) { return m.name; }).join("、"));
      }
      if (collabs.length) {
        lines.push((zh ? "有合作记录的教师：" : "Recorded collaborators: ") + collabs.map(function (c) {
          if (zh) return c.name + (c.college ? "（" + c.college + "，权重 " + c.weight + "）" : "（权重 " + c.weight + "）");
          return c.name + (c.college ? " (" + c.college + ", weight " + c.weight + ")" : " (weight " + c.weight + ")");
        }).join("、"));
      }
      lines.push(zh
        ? "说明：本地教师库没有“实验室成员”字段，以上按研究所与合作记录推断，不等于实验室完整名单；具体成员请以官方主页为准。"
        : "Note: the local database has no lab-membership field. The lists above are inferred from institute and collaboration records, not a complete roster; verify on the official page.");

      const cards = [];
      const seen = {};
      mates.concat(collabs).forEach(function (x) {
        if (!x || seen[x.id]) return;
        seen[x.id] = 1;
        cards.push({ id: x.id, name: x.name, college: x.college, title: x.title || "" });
      });
      return { reply: lines.join("\n"), cards: cards.slice(0, 6), sources: sourcesOf(cards), notes: [] };
    }

    if (slots.intent === "teacher" || slots.intent === "recent") {
      const name = slots.names[0] || "";
      const teacher = TEACHERS.filter(function (x) { return x.name === name; })[0];
      if (!teacher) {
        return { reply: zh ? "没有在本地库中找到这位教师。" : "I could not find that faculty member locally.",
                 cards: [], sources: [], notes: [] };
      }
      const detail = detailsOf(teacher);
      const lines = [teacher.name + " · " + (teacher.college || "") + (teacher.title ? " · " + teacher.title : "")];
      if (teacher.research_directions) {
        lines.push((zh ? "研究方向：" : "Research areas: ") + teacher.research_directions);
      }
      const metrics = [];
      if (teacher.h_index != null) metrics.push((zh ? "h 指数 " : "h-index ") + teacher.h_index);
      if (teacher.citation_count != null) metrics.push((zh ? "总引用 " : "citations ") + fmt(teacher.citation_count));
      if (metrics.length) lines.push((zh ? "学术指标：" : "Metrics: ") + metrics.join("，"));
      const papers = (detail.papers || []).slice(0, 2);
      if (papers.length) {
        lines.push(zh ? "代表论文：" : "Papers: ");
        papers.forEach(function (p) {
          lines.push("· " + truncate(p.title, 60) + (p.year ? "（" + p.year + "）" : ""));
        });
      }
      if (slots.intent === "recent") {
        lines.push(zh ? "本地收录可能不完整，建议以官方主页为准。" : "Local records may be incomplete; verify on the official page.");
      }
      if (slots.raw && slots.raw.indexOf("评价") >= 0) {
        lines.push(zh ? "这里只提供公开档案信息，不做主观评价。"
                     : "Only public profile fields are reported; no subjective evaluation.");
      }
      const card = cardOf(teacher);
      return { reply: lines.join("\n"), cards: [card], sources: sourcesOf([card]), notes: [] };
    }

    if (slots.intent === "compare") {
      const profiles = slots.names.slice(0, 2).map(function (name) {
        return TEACHERS.filter(function (x) { return x.name === name; })[0];
      }).filter(Boolean);
      if (profiles.length < 2) {
        return { reply: zh ? "我需要两位教师的姓名才能比较。" : "I need two faculty names to compare.",
                 cards: [], sources: [], notes: [] };
      }
      const blocks = profiles.map(function (p) {
        const lines = [p.name + " · " + (p.college || "")];
        if (p.research_directions) lines.push((zh ? "方向：" : "Areas: ") + truncate(p.research_directions, 80));
        const metrics = [];
        if (p.h_index != null) metrics.push((zh ? "h 指数 " : "h-index ") + p.h_index);
        if (p.citation_count != null) metrics.push((zh ? "总引用 " : "citations ") + fmt(p.citation_count));
        if (metrics.length) lines.push((zh ? "指标：" : "Metrics: ") + metrics.join("，"));
        return lines.join("\n");
      });
      const cards = profiles.map(cardOf);
      return {
        reply: blocks.join("\n\n") + (zh ? "\n\n以上只比较公开档案字段，不代表指导质量。" : "\n\nPublic profile fields only, not advising quality."),
        cards: cards,
        sources: sourcesOf(cards),
        notes: []
      };
    }

    let items;
    if (slots.terms.length) {
      items = search(slots.terms, slots.college, slots.topK, slots.intent === "experts");
    } else if (slots.college) {
      items = listCollege(slots.college, slots.topK);
    } else {
      items = [];
    }
    if (!items.length) {
      return {
        reply: zh ? "我还没有识别出具体研究方向。可以说“数据挖掘”“计算机视觉”或“计算机学院有哪些导师”。"
                  : "I could not identify a research area. Try data mining, computer vision, or a school name.",
        cards: [], sources: [], notes: []
      };
    }

    const scope = slots.college ? (zh ? "（限定 " + slots.college + "）" : " in " + slots.college) : "";
    let head;
    if (!slots.terms.length) {
      head = zh
        ? "在“" + slots.college + "”中，我按现有综合评分列出 " + items.length + " 位教师。"
        : "Here are " + items.length + " faculty members in " + slots.college +
          ", ordered by the existing overall score.";
    } else if (slots.intent === "experts") {
      head = zh
        ? "在已收录资料中，有 " + items.length + " 位教师持续涉及“" + terms + "”" + scope + "。"
        : "The local records show " + items.length + " faculty members with sustained work on \"" + terms + "\"" + scope + ".";
    } else {
      head = zh
        ? "根据“" + terms + "”，我在本地教师库中筛出 " + items.length + " 位方向较接近的导师" + scope + "。"
        : "For \"" + terms + "\", I found " + items.length + " advisors" + scope + ".";
    }

    const body = items.map(function (item, i) { return entry(item, i, zh); }).join("\n\n");
    const tail = zh
      ? "\n\n以上是信息匹配，不代表招生意愿、指导风格或录取难度。"
      : "\n\nInformation matches only; not admission willingness or advising style.";
    const cards = items.map(function (item) { return cardOf(item.teacher); });
    return {
      reply: head + "\n\n" + body + tail,
      cards: cards,
      sources: sourcesOf(cards),
      notes: [zh ? "本地教师库共 " + TEACHERS.length + " 人。" : TEACHERS.length + " local faculty records."]
    };
  }

  /* ---------------------------------------------------------------- 面板 */
  function viewportH() { return window.innerHeight || document.documentElement.clientHeight; }

  function topbarH() {
    const bar = document.querySelector(".topbar");
    return bar ? Math.round(bar.getBoundingClientRect().height) : 56;
  }

  function snapHeight(name) {
    if (name === "peek") return PEEK;
    if (name === "full") return Math.max(260, viewportH() - topbarH());
    return Math.max(300, Math.min(560, Math.round(viewportH() * 0.6)));
  }

  function setState(name) {
    sheetState = name;
    sheet.dataset.state = name;
    sheet.style.height = snapHeight(name) + "px";
    // 抽屉是 overflow:hidden，聚焦或被裁切的子元素会把内部滚动位置带偏，
    // 顶栏被挤出可视区后就再也抓不到拖拽把手，因此每次切换都复位。
    sheet.scrollTop = 0;
    el.tri.setAttribute("aria-expanded", name === "peek" ? "false" : "true");
    el.tri.setAttribute("aria-label", name === "peek" ? t("ai.expand") : t("ai.collapse"));
    if (name === "peek" && document.activeElement === el.input) el.input.blur();
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

  function onDown(e) {
    if (e.button != null && e.button !== 0) return;
    drag = { y: e.clientY, height: sheet.getBoundingClientRect().height, moved: false, dy: 0 };
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
    sheet.scrollTop = 0;
    sheet.dataset.state = h > snapHeight("full") * 0.9 ? "full" : (h > PEEK + 28 ? "half" : "peek");
  }

  function onUp() {
    if (!drag) return;
    const moved = drag.moved;
    const dy = drag.dy;
    const h = sheet.getBoundingClientRect().height;
    drag = null;
    sheet.dataset.dragging = "false";
    if (!moved) { toggle(); return; }
    const options = [["peek", PEEK], ["half", snapHeight("half")], ["full", snapHeight("full")]];
    let best = "peek";
    let dist = Infinity;
    options.forEach(function (opt) {
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
    bubble.textContent = t("ai.welcome");
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
    hint.textContent = t("ai.card.open");
    btn.appendChild(name);
    btn.appendChild(meta);
    btn.appendChild(hint);
    return btn;
  }

  function sourceNode(source) {
    const node = document.createElement("a");
    node.className = "ai-source";
    node.textContent = source.label;
    node.href = source.url;
    node.target = "_blank";
    node.rel = "noopener";
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
      meta.cards.forEach(function (card) { cards.appendChild(cardNode(card)); });
      wrap.appendChild(cards);
    }
    if (meta.sources && meta.sources.length) {
      const sources = document.createElement("div");
      sources.className = "ai-sources";
      meta.sources.forEach(function (src) { sources.appendChild(sourceNode(src)); });
      wrap.appendChild(sources);
    }
    if (meta.notes && meta.notes.length) {
      const notes = document.createElement("div");
      notes.className = "ai-notes";
      meta.notes.forEach(function (text) {
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
    bubble.textContent = t("ai.thinking");
    wrap.appendChild(bubble);
    return wrap;
  }

  function renderSuggest(list) {
    lastSuggestions = list || [];
    el.suggest.innerHTML = "";
    lastSuggestions.forEach(function (text) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "ai-chip";
      chip.textContent = text;
      el.suggest.appendChild(chip);
    });
    el.suggest.classList.toggle("hidden", !lastSuggestions.length);
  }

  function defaultSuggestions() {
    return [t("ai.suggest.1"), t("ai.suggest.2"), t("ai.suggest.3")];
  }

  function renderAll() {
    el.messages.innerHTML = "";
    if (!chat.length) {
      el.messages.appendChild(welcomeNode());
      renderSuggest(defaultSuggestions());
    } else {
      chat.forEach(function (msg) { el.messages.appendChild(messageNode(msg)); });
      renderSuggest(lastSuggestions.length ? lastSuggestions : defaultSuggestions());
    }
    scrollBottom();
  }

  function pushMessage(msg) {
    chat.push(msg);
    if (chat.length > 40) chat = chat.slice(-40);
    const node = messageNode(msg);
    el.messages.appendChild(node);
    saveHistory();
    scrollBottom();
    return node;
  }

  /* ---------------------------------------------------------------- API 与 RAG */
  const RAG_STOP = {
    "哪些": 1, "哪位": 1, "什么": 1, "怎么": 1, "如何": 1, "老师": 1, "导师": 1,
    "教师": 1, "教授": 1, "学生": 1, "学院": 1, "学校": 1, "推荐": 1, "介绍": 1,
    "一下": 1, "请问": 1, "是否": 1, "可以": 1, "帮我": 1, "希望": 1, "喜欢": 1,
    "想找": 1, "方向": 1, "领域": 1, "研究": 1, "方面": 1, "相关": 1, "信息": 1,
    "情况": 1, "成果": 1, "论文": 1, "我们": 1, "你们": 1, "他们": 1,
    "the": 1, "and": 1, "for": 1, "with": 1, "what": 1, "which": 1, "who": 1,
    "is": 1, "are": 1, "of": 1, "in": 1, "on": 1, "to": 1, "a": 1, "an": 1
  };

  function loadApiSettings() {
    try {
      const raw = JSON.parse(localStorage.getItem(API_SETTINGS_KEY) || "{}");
      return {
        enabled: !!raw.enabled,
        base_url: raw.base_url || DEFAULT_API_BASE,
        model: raw.model || DEFAULT_API_MODEL,
        api_key: raw.api_key || ""
      };
    } catch (e) {
      return { enabled: false, base_url: DEFAULT_API_BASE, model: DEFAULT_API_MODEL, api_key: "" };
    }
  }

  function apiKeyHint(key) {
    return key ? (key.slice(0, 5) + "…" + key.slice(-4)) : "";
  }

  function setApiStatus(text, kind) {
    if (!el.apiStatus) return;
    el.apiStatus.textContent = text || "";
    if (kind) el.apiStatus.dataset.kind = kind;
    else delete el.apiStatus.dataset.kind;
  }

  function fillApiSettings() {
    if (!el.apiEnabled) return;
    el.apiEnabled.checked = !!apiSettings.enabled;
    el.apiBase.value = apiSettings.base_url || DEFAULT_API_BASE;
    el.apiModel.value = apiSettings.model || DEFAULT_API_MODEL;
    el.apiKey.value = "";
    el.apiKey.placeholder = apiSettings.api_key
      ? t("settings.ai.keySaved", { hint: apiKeyHint(apiSettings.api_key) })
      : "sk-...";
    if (apiSettings.enabled && apiSettings.api_key) {
      setApiStatus(t("settings.ai.testOk"), "ok");
    } else {
      setApiStatus("");
    }
  }

  function saveApiSettings() {
    if (!el.apiEnabled) return;
    const key = el.apiKey.value.trim();
    apiSettings = {
      enabled: el.apiEnabled.checked,
      base_url: el.apiBase.value.trim() || DEFAULT_API_BASE,
      model: el.apiModel.value.trim() || DEFAULT_API_MODEL,
      api_key: key || apiSettings.api_key
    };
    try { localStorage.setItem(API_SETTINGS_KEY, JSON.stringify(apiSettings)); } catch (e) { /* 忽略 */ }
    fillApiSettings();
    setEngine();
    setApiStatus(t("settings.ai.saved"), "ok");
  }

  async function apiChat(messages, maxTokens) {
    const base = (apiSettings.base_url || DEFAULT_API_BASE).replace(/\/+$/, "");
    const url = base.indexOf("/chat/completions") >= 0 ? base : base + "/chat/completions";
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + apiSettings.api_key,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model: apiSettings.model || DEFAULT_API_MODEL,
        messages: messages,
        max_tokens: maxTokens,
        temperature: 0.3,
        stream: false,
        thinking: { type: "disabled" }
      })
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error("HTTP " + res.status + " " + body.slice(0, 120));
    }
    const data = await res.json();
    const choice = (data.choices || [])[0] || {};
    const message = choice.message || {};
    return message.content || "";
  }

  async function testApi() {
    if (!el.apiEnabled) return;
    if (el.apiKey.value.trim()) saveApiSettings();
    if (!apiSettings.api_key) {
      setApiStatus(t("settings.ai.testFail"), "error");
      return;
    }
    setApiStatus(t("settings.ai.testing"), "");
    el.apiTest.disabled = true;
    const started = Date.now();
    try {
      const text = await apiChat([{ role: "user", content: "只回复：连接成功" }], 16);
      if (text.indexOf("连接成功") < 0) throw new Error(text.slice(0, 60));
      setApiStatus(t("settings.ai.testOk") + " · " + (Date.now() - started) + " ms", "ok");
    } catch (err) {
      setApiStatus(t("settings.ai.testFail") + " · " + String(err.message || err).slice(0, 120), "error");
    } finally {
      el.apiTest.disabled = false;
    }
  }

  function tokenizeQuery(text) {
    const lower = String(text || "").toLowerCase();
    const out = [];
    (lower.match(/[a-z0-9]+/g) || []).forEach(function (w) {
      if (w.length >= 2 && !RAG_STOP[w]) out.push(w);
    });
    lower.replace(/[^\u4e00-\u9fa5]/g, " ").split(/\s+/).forEach(function (run) {
      for (let i = 0; i + 2 <= run.length; i += 1) {
        const gram = run.slice(i, i + 2);
        if (!RAG_STOP[gram]) out.push(gram);
      }
    });
    return unique(out);
  }

  function ragScore(t, queryLower, phrase, terms, tokens) {
    const detail = detailsOf(t);
    const honors = Array.isArray(t.honors) ? t.honors.join(" ") : String(t.honors || "");
    const fields = [
      [honors, 3.0],
      [t.research_directions || "", 3.0],
      [(t.keywords || []).join(" "), 2.5],
      [String(detail.bio || ""), 2.0],
      [(detail.papers || []).map(function (p) { return p.title || ""; }).join(" "), 1.2],
      [(detail.courses || []).map(function (c) { return c.name || ""; }).join(" "), 0.5]
    ];
    let score = 0;
    fields.forEach(function (item) {
      const low = String(item[0]).toLowerCase();
      let hits = 0;
      tokens.forEach(function (tok) { if (low.indexOf(tok) >= 0) hits += 1; });
      if (hits) score += hits * item[1];
      if (phrase && low.indexOf(phrase) >= 0) score += 6 * item[1];
      (terms || []).forEach(function (term) {
        if (term && low.indexOf(String(term).toLowerCase()) >= 0) score += 4 * item[1];
      });
    });
    const honorText = honors.toLowerCase();
    [
      ["ieee fellow", 40], ["isca fellow", 40], ["acm fellow", 40],
      ["院士", 30], ["杰青", 20], ["长江学者", 20], ["优青", 16], ["博导", 4]
    ].forEach(function (item) {
      if (queryLower.indexOf(item[0]) >= 0 && honorText.indexOf(item[0]) >= 0) {
        score += item[1];
      }
    });
    return score;
  }

  function mobileRag(slots, question) {
    const zh = currentLang !== "en";
    const queryLower = String(question || "").toLowerCase();
    const phrase = (slots.terms && slots.terms.length ? slots.terms.join(" ") : question).toLowerCase();
    const tokens = tokenizeQuery(question + " " + (slots.terms || []).join(" "));

    function profileEvidence(t, graphReason) {
      const detail = detailsOf(t);
      return {
        name: t.name,
        college: t.college,
        title: t.title,
        directions: t.research_directions,
        honors: Array.isArray(t.honors) ? t.honors.slice(0, 4) : [],
        h_index: t.h_index,
        citations: t.citation_count,
        paper_count: t.paper_count,
        papers: (detail.papers || []).slice(0, 2).map(function (p) { return p.title; }),
        graph_reason: graphReason || ""
      };
    }

    function cardsOf(list) {
      const seen = {};
      const out = [];
      list.forEach(function (t) {
        if (!t || seen[t.id]) return;
        seen[t.id] = 1;
        out.push(cardOf(t));
      });
      return out.slice(0, 4);
    }

    if (slots.intent === "teacher" || slots.intent === "recent") {
      const name = slots.names[0] || "";
      const teacher = TEACHERS.filter(function (x) { return x.name === name; })[0];
      if (!teacher) return { evidence: [], cards: [], sources: [] };
      const cards = cardsOf([teacher]);
      return { evidence: [profileEvidence(teacher)], cards: cards, sources: sourcesOf(cards) };
    }

    if (slots.intent === "lab") {
      const name = slots.names[0] || "";
      const teacher = TEACHERS.filter(function (x) { return x.name === name; })[0];
      if (!teacher) return { evidence: [], cards: [], sources: [] };
      const detail = detailsOf(teacher);
      const institute = teacher.institute || detail.institute || "";
      const mates = TEACHERS.filter(function (x) {
        return x.id !== teacher.id && x.institute === institute;
      }).slice(0, 8);
      const collabs = (detail.collaborators || []).slice(0, 6).map(function (c) {
        return { id: c.id, name: c.name, college: c.college, title: "", weight: c.weight };
      });
      const cards = cardsOf(mates.concat(collabs));
      const match = String(detail.bio || "").match(/([A-Za-z][A-Za-z0-9\-& ]{1,30}(?:Lab|Laboratory))/);
      return {
        evidence: [{
          name: teacher.name,
          college: teacher.college,
          title: teacher.title,
          lab_name: match ? match[1].trim() : "",
          institute: institute,
          mates: mates.map(function (m) { return { name: m.name, directions: m.research_directions }; }),
          collaborators: collabs.map(function (c) {
            return { name: c.name, college: c.college, weight: c.weight };
          })
        }],
        cards: cards,
        sources: sourcesOf(cards)
      };
    }

    if (slots.intent === "compare") {
      const list = slots.names.slice(0, 2).map(function (name) {
        return TEACHERS.filter(function (x) { return x.name === name; })[0];
      }).filter(Boolean);
      if (list.length < 2) return { evidence: [], cards: [], sources: [] };
      const cards = cardsOf(list);
      return {
        evidence: list.map(function (t) { return profileEvidence(t); }),
        cards: cards,
        sources: sourcesOf(cards)
      };
    }

    const scores = {};
    const reasons = {};
    TEACHERS.forEach(function (t) {
      const score = ragScore(t, queryLower, phrase, slots.terms || [], tokens);
      if (score > 0) scores[t.id] = score;
    });

    const seeds = Object.keys(scores).map(Number)
      .sort(function (a, b) { return scores[b] - scores[a]; }).slice(0, 3);
    seeds.forEach(function (seedId) {
      const seed = TEACHERS.filter(function (x) { return x.id === seedId; })[0];
      if (!seed) return;
      const detail = detailsOf(seed);
      (detail.collaborators || []).forEach(function (c) {
        if (scores[c.id] > 0) {
          scores[c.id] += scores[seedId] * Math.min(0.2, (c.weight || 1) / 50);
          if (!reasons[c.id]) {
            reasons[c.id] = (zh ? "与" : "with ") + seed.name + (zh ? "有合作关系" : " (collaboration)");
          }
        }
      });
      if (seed.institute) {
        TEACHERS.forEach(function (x) {
          if (x.id !== seed.id && x.institute === seed.institute && scores[x.id] > 0) {
            scores[x.id] += scores[seedId] * 0.03;
            if (!reasons[x.id]) {
              reasons[x.id] = (zh ? "与" : "with ") + seed.name + (zh ? "同研究所" : " (same institute)");
            }
          }
        });
      }
    });

    const top = Object.keys(scores).map(Number)
      .sort(function (a, b) { return scores[b] - scores[a]; })
      .slice(0, 4)
      .map(function (id) { return TEACHERS.filter(function (t) { return t.id === id; })[0]; })
      .filter(Boolean);
    const cards = cardsOf(top);
    return {
      evidence: top.map(function (t) { return profileEvidence(t, reasons[t.id] || ""); }),
      cards: cards,
      sources: sourcesOf(cards)
    };
  }

  function cleanApiText(text) {
    return String(text || "").replace(/```/g, "").replace(/\*\*/g, "").trim().slice(0, 2500);
  }

  async function mobileApiAnswer(question, slots) {
    if (!apiSettings.enabled || !apiSettings.api_key) return null;
    const rag = mobileRag(slots, question);
    if (!rag.evidence.length) return null;
    const zh = currentLang !== "en";
    const system = zh
      ? "你是“交我导”的导师助手。只能依据下面的本地检索证据回答，不得编造教师、论文、指标或荣誉。可以自由组织语言。同研究所教师和合作记录不等于实验室成员，若使用必须说明。不要使用 Markdown 表格或加粗。用中文简洁回答。"
      : "You are the Advisor Finder assistant. Answer only from the local evidence below; do not invent names, papers, metrics or honors. Same-institute teachers and collaboration records are not lab membership; say so if used. No Markdown tables or bold. Answer in English.";
    const user = (zh ? "用户问题：" : "Question: ") + question +
      "\n\n" + (zh ? "本地检索证据：" : "Local evidence:") + "\n" +
      JSON.stringify(rag.evidence).slice(0, 5000);
    try {
      const text = cleanApiText(await apiChat([
        { role: "system", content: system },
        { role: "user", content: user }
      ], 800));
      if (!text) return null;
      return { reply: text, cards: rag.cards, sources: rag.sources, notes: [] };
    } catch (err) {
      return null;
    }
  }

  /* ---------------------------------------------------------------- 引擎标识 */
  function setEngine() {
    if (apiSettings.enabled && apiSettings.api_key) {
      el.engine.textContent = apiSettings.model || "API";
      el.engine.title = apiSettings.base_url || "";
      el.engine.dataset.mode = "model";
    } else {
      el.engine.textContent = t("ai.engine.rule");
      el.engine.title = t("ai.engine.rule.hint");
      el.engine.dataset.mode = "rule";
    }
  }

  /* ---------------------------------------------------------------- 对话 */
  function setBusy(value) {
    busy = value;
    el.send.disabled = value;
  }

  async function send(text) {
    const content = String(text || "").trim();
    if (!content || busy) return;
    if (sheetState === "peek") setState("half");

    setBusy(true);
    pushMessage({ role: "user", content: content });
    const pending = pendingNode();
    el.messages.appendChild(pending);
    scrollBottom();

    try {
      const slots = parse(content);
      let result = answerFor(slots, currentLang);
      let apiFailed = false;
      const canApi = ["teacher", "recent", "lab", "compare", "recommend", "experts", "search"].indexOf(slots.intent) >= 0;
      if (apiSettings.enabled && apiSettings.api_key && canApi) {
        const bubble = pending.querySelector(".ai-bubble");
        if (bubble) bubble.textContent = t("ai.apiThinking");
        const apiResult = await mobileApiAnswer(content, slots);
        if (apiResult) {
          result = apiResult;
        } else {
          apiFailed = true;
        }
      }
      pending.remove();
      if (apiFailed) {
        result.notes = (result.notes || []).concat([t("ai.apiFailed")]);
      }
      const msg = {
        role: "assistant",
        content: result.reply,
        meta: { cards: result.cards, sources: result.sources, notes: result.notes, intent: slots.intent }
      };
      const node = pushMessage(msg);
      renderSuggest(defaultSuggestions());
    } catch (err) {
      pending.remove();
      pushMessage({ role: "assistant", content: t("ai.error"), meta: {} });
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
    el.input.style.height = Math.min(el.input.scrollHeight, 96) + "px";
  }

  /* ---------------------------------------------------------------- 事件 */
  el.handle.addEventListener("pointerdown", onDown);
  el.handle.addEventListener("pointermove", onMove);
  el.handle.addEventListener("pointerup", onUp);
  el.handle.addEventListener("pointercancel", onUp);
  // 指针捕获被系统回收时同样收敛状态，避免 dragging 标记残留
  el.handle.addEventListener("lostpointercapture", onUp);
  el.tri.addEventListener("click", function (e) {
    if (e.detail === 0) { e.preventDefault(); toggle(); }
  });

  el.form.addEventListener("submit", function (e) {
    e.preventDefault();
    submitText();
  });
  el.input.addEventListener("input", autoGrow);
  // 收起状态下不接受焦点，否则软键盘与内部滚动会把抽屉顶栏顶出可视区
  el.input.addEventListener("focus", function () {
    if (sheetState === "peek") {
      el.input.blur();
      sheet.scrollTop = 0;
    }
  });
  el.input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submitText();
    }
  });

  el.suggest.addEventListener("click", function (e) {
    const chip = e.target.closest(".ai-chip");
    if (chip) send(chip.textContent);
  });

  el.messages.addEventListener("click", function (e) {
    const node = e.target.closest("[data-teacher]");
    if (!node) return;
    const tid = Number(node.dataset.teacher);
    if (!tid) return;
    setState("peek");
    if (typeof openDetail === "function") openDetail(tid);
  });

  el.clear.addEventListener("click", function () {
    if (!window.confirm(t("ai.clear.confirm"))) return;
    chat = [];
    lastSuggestions = [];
    saveHistory();
    renderAll();
  });

  if (el.apiSave) el.apiSave.addEventListener("click", saveApiSettings);
  if (el.apiTest) el.apiTest.addEventListener("click", testApi);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && sheetState !== "peek") setState("peek");
  });

  window.addEventListener("resize", function () {
    if (sheetState !== "peek") sheet.style.height = snapHeight(sheetState) + "px";
  });

  window.MobileAI = {
    refresh: function () {
      setEngine();
      el.tri.setAttribute("aria-label", sheetState === "peek" ? t("ai.expand") : t("ai.collapse"));
      if (!chat.length) renderAll();
      else renderSuggest(lastSuggestions.length ? lastSuggestions : defaultSuggestions());
    },
    isOpen: function () { return sheetState !== "peek"; },
    close: function () { setState("peek"); },
    open: function () { if (sheetState === "peek") setState("half"); }
  };

  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (Array.isArray(saved)) chat = saved;
  } catch (e) { chat = []; }

  setState("peek");
  renderAll();
  fillApiSettings();
  setEngine();
})();
