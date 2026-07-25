/* 取得失敗日を日付プルダウンに赤く差し込む共通ウィジェット。
 *
 * 使い方（各サイトの index.html の </body> 直前に1行）:
 *   <script src="/kabutan-ranking/fetchstatus.js" defer></script>
 *   <script src="/kabutan-ranking/fetchstatus.js" data-offset="1" defer></script>   ← PTSのように
 *                                                                                     保存日=売買日+1 の場合
 * data 属性:
 *   data-select  対象 <select> の id（既定 "dateSel"）
 *   data-offset  保存日 - 売買日 の日数（既定 0）
 *
 * 判定: 「土日でも祝日でもない売買日」なのに保存データが無い日 = 取得失敗。
 * 既存の option には触れず、欠損日だけを disabled の赤い option として差し込むので、
 * 各サイトの sel.value / sel.onchange のロジックはそのまま動く。
 */
(function () {
  "use strict";

  var self = document.currentScript;
  // 自身の src を基準にするので、別サイトから読み込んでもローカルでも解決できる
  var HOLIDAYS_URL = new URL("holidays.json", self.src).href;
  var SEL_ID = (self && self.dataset.select) || "dateSel";
  var OFFSET = Number((self && self.dataset.offset) || 0);

  var DAY = 86400000;
  var ymd = function (d) {
    return d.getFullYear() + "-" +
      String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  };
  // 文字列日付をローカル正午で持つ（DSTや時差で日付がずれないように）
  var parse = function (s) {
    var p = s.split("-");
    return new Date(+p[0], +p[1] - 1, +p[2], 12);
  };

  function tradingDay(dateStr, holidays) {
    var d = parse(dateStr);
    var w = d.getDay();
    if (w === 0 || w === 6) return false;
    return !holidays.has(dateStr);
  }

  /* 保存日 from〜to のうち、本来データがあるべき日を返す。
     保存日 D に対応する売買日は D - OFFSET 日。 */
  function expected(from, to, holidays) {
    var out = [];
    for (var t = parse(from).getTime(); t <= parse(to).getTime(); t += DAY) {
      var save = ymd(new Date(t));
      var trade = ymd(new Date(t - OFFSET * DAY));
      if (tradingDay(trade, holidays)) out.push(save);
    }
    return out;
  }

  function decorate(sel, holidays) {
    Array.prototype.slice.call(sel.querySelectorAll("option[data-missing]"))
      .forEach(function (o) { o.remove(); });

    var present = Array.prototype.slice.call(sel.options)
      .map(function (o) { return o.value; })
      .filter(function (v) { return /^\d{4}-\d{2}-\d{2}$/.test(v); });
    if (present.length < 2) return;

    var sorted = present.slice().sort();
    var have = new Set(present);
    var missing = expected(sorted[0], sorted[sorted.length - 1], holidays)
      .filter(function (d) { return !have.has(d); });
    if (!missing.length) return;

    var byDate = {};
    Array.prototype.slice.call(sel.options).forEach(function (o) { byDate[o.value] = o; });

    var all = present.concat(missing).sort().reverse();
    var keep = sel.value;
    var frag = document.createDocumentFragment();

    all.forEach(function (d) {
      if (byDate[d]) {
        frag.appendChild(byDate[d]);          // 既存要素は移動されるだけ
        return;
      }
      var o = document.createElement("option");
      o.value = d;
      o.textContent = d + "  取得失敗";
      o.disabled = true;
      o.dataset.missing = "1";
      o.style.background = "#7f1d24";
      o.style.color = "#ffe1e4";
      o.style.fontWeight = "700";
      frag.appendChild(o);
    });

    sel.appendChild(frag);
    if (keep) sel.value = keep;
    sel.dataset.missingCount = String(missing.length);
    sel.title = "取得失敗 " + missing.length + "日: " + missing.join(", ");
  }

  function start(holidays) {
    var sel = document.getElementById(SEL_ID);
    if (!sel) return;
    var obs = new MutationObserver(function () {
      obs.disconnect();
      try { decorate(sel, holidays); } finally { obs.observe(sel, { childList: true }); }
    });
    try { decorate(sel, holidays); } catch (e) { /* 表示は壊さない */ }
    obs.observe(sel, { childList: true });
  }

  fetch(HOLIDAYS_URL, { cache: "no-cache" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (j) {
      // 祝日リストが読めないまま判定すると、祝日をすべて「取得失敗」と
      // 誤表示してしまう。読めなければ何もしない方が安全。
      if (!j || !Array.isArray(j.dates) || !j.dates.length) {
        console.warn("fetchstatus: holidays.json を読めないため取得失敗表示を行いません");
        return;
      }
      var holidays = new Set(j.dates);
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { start(holidays); });
      } else {
        start(holidays);
      }
    });
})();
