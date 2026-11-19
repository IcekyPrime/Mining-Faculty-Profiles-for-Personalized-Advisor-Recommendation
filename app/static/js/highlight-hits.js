/* 命中词高亮：对结果卡片中的姓名、方向、标签做轻量标记，不改动任何业务数据。 */
(function () {
  "use strict";

  const list = document.getElementById("results-list");
  const input = document.getElementById("search-input");
  if (!list || !input) return;

  let timer = null;
  let applying = false;

  function tokens() {
    return input.value.trim().split(/\s+/).filter((token) => token.length >= 2).slice(0, 6);
  }

  function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function markTextNode(node, pattern) {
    const text = node.nodeValue || "";
    pattern.lastIndex = 0;
    if (!pattern.test(text)) return;
    pattern.lastIndex = 0;
    const fragment = document.createDocumentFragment();
    let last = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > last) fragment.appendChild(document.createTextNode(text.slice(last, match.index)));
      const mark = document.createElement("mark");
      mark.className = "hit";
      mark.textContent = match[0];
      fragment.appendChild(mark);
      last = match.index + match[0].length;
      if (match[0].length === 0) pattern.lastIndex += 1;
    }
    if (last < text.length) fragment.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(fragment, node);
  }

  function apply() {
    if (applying) return;
    const words = tokens();
    if (!words.length) return;
    const cards = list.querySelectorAll(".teacher-card");
    if (!cards.length) return;

    applying = true;
    const pattern = new RegExp(words.map(escapeRegExp).join("|"), "gi");
    cards.forEach((card) => {
      const targets = card.querySelectorAll(".tc-name, .tc-title, .tc-meta, .tc-dir, .tc-tags");
      targets.forEach((target) => {
        const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT, {
          acceptNode(node) {
            if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
            const parent = node.parentElement;
            if (!parent) return NodeFilter.FILTER_REJECT;
            if (parent.closest("mark.hit")) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
          },
        });
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach((node) => markTextNode(node, pattern));
      });
    });
    applying = false;
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(apply, 60);
  }

  const observer = new MutationObserver((mutations) => {
    if (applying) return;
    if (mutations.some((mutation) => mutation.addedNodes.length)) schedule();
  });
  observer.observe(list, { childList: true, subtree: true });

  // 输入变化后，结果列表会由 app.js 重绘；MutationObserver 会接住。
  input.addEventListener("change", schedule);
})();
