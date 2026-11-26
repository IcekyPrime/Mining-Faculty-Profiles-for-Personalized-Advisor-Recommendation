/* 移动端环境兜底：个别 WebView 在 file:// 下禁用 localStorage 时使用内存存储。 */
(function () {
  "use strict";
  try {
    window.localStorage.getItem("__probe__");
    return;
  } catch (e) {
    var mem = {};
    var shim = {
      getItem: function (k) {
        return Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null;
      },
      setItem: function (k, v) { mem[k] = String(v); },
      removeItem: function (k) { delete mem[k]; },
      clear: function () { mem = {}; }
    };
    try {
      Object.defineProperty(window, "localStorage", { configurable: true, value: shim });
    } catch (ignored) {
      window.__memoryStorage = shim;
    }
  }
})();
