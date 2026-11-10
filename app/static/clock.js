/* Typed clock times (D104): forgiving input, normalised on leaving the field.
   7 → 07:00, 730 → 07:30, 15.30 → 15:30, 24 → 00:00. Arrow up/down moves by
   half an hour (Shift: a full hour); in an empty field it suggests a time. No build step, no dependencies. */
var Clock = (function () {
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function parse(text) {
    var v = String(text || "").trim().replace(/[.,]/g, ":"), h, m;
    if (!v) return null;
    if (v.indexOf(":") >= 0) {
      var p = v.split(":");
      if (p.length !== 2 || !/^\d{1,2}$/.test(p[0]) || !/^\d{1,2}$/.test(p[1])) return null;
      h = +p[0]; m = +p[1];
    } else if (/^\d{1,2}$/.test(v)) { h = +v; m = 0; }
    else if (/^\d{3,4}$/.test(v)) { h = +v.slice(0, -2); m = +v.slice(-2); }
    else return null;
    if (h === 24 && m === 0) h = 0;
    if (h > 23 || m > 59) return null;
    return h * 60 + m;
  }
  function format(minutes) {
    minutes = ((minutes % 1440) + 1440) % 1440;
    return pad(Math.floor(minutes / 60)) + ":" + pad(minutes % 60);
  }
  function describe(start, end) {
    if (start === end) return "Start og slutt kan ikke være like.";
    var d = end - start, night = d < 0;
    if (night) d += 1440;
    return Math.floor(d / 60) + " t" + (d % 60 ? " " + (d % 60) + " min" : "") + (night ? " · over midnatt" : "");
  }
  function attach(input, options) {
    options = options || {};
    var step = options.step || 30;
    function check() {
      var m = parse(input.value);
      if (!input.value.trim()) { input.setCustomValidity(""); return; }
      if (m === null) { input.setCustomValidity("Skriv et klokkeslett, f.eks. 7, 730 eller 15:30."); return; }
      if (options.halfHours && m % 30) { input.setCustomValidity("Bruk hele eller halve timer (f.eks. 07:00 eller 07:30)."); return; }
      input.setCustomValidity("");
    }
    input.addEventListener("blur", function () {
      var m = parse(input.value);
      if (m !== null) input.value = format(m);
      check();
      input.dispatchEvent(new Event("change", {bubbles: true}));
    });
    input.addEventListener("input", check);
    input.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      e.preventDefault();
      var m = parse(input.value), delta = (e.shiftKey ? 60 : step) * (e.key === "ArrowUp" ? 1 : -1);
      if (m === null) {          // empty: start from a sensible suggestion, don't step it
        m = options.fallback ? parse(options.fallback()) : null;
        if (m === null) m = 7 * 60;
      } else {
        m = Math.round((m + delta) / step) * step;
      }
      input.value = format(m);
      check();
      input.dispatchEvent(new Event("input", {bubbles: true}));
    });
    check();
  }
  return {parse: parse, format: format, describe: describe, attach: attach};
})();
