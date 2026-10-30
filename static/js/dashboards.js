/* Module and Owner dashboards: draw the charts embedded in the page; clicking a bar / slice opens its records. */
(function () {
  "use strict";
  var el = document.getElementById("dash-charts");
  if (!el || typeof Chart === "undefined") return;
  var charts = JSON.parse(el.textContent);
  var palette = ["#1F66B3", "#1F8A4C", "#C9741A", "#B42318", "#7A8B1C", "#6B4FBB", "#0F8B8D", "#8A5A00", "#4B5563"];
  var fmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  charts.forEach(function (c, i) {
    var canvas = document.querySelector('[data-dash-chart="' + i + '"]');
    if (!canvas) return;
    var total = c.datasets.reduce(function (s, ds) { return s + ds.data.reduce(function (a, b) { return a + b; }, 0); }, 0);
    if (!total) {
      canvas.parentNode.innerHTML = '<div class="tf-empty h-100 d-flex align-items-center justify-content-center">No records for this chart in the selected period.</div>';
      return;
    }
    var round = c.type === "doughnut";
    var cfg = {
      type: c.type,
      data: { labels: c.labels, datasets: c.datasets.map(function (ds, k) {
        return Object.assign({ backgroundColor: round ? palette : palette[k % palette.length], borderRadius: round ? 0 : 3,
          maxBarThickness: 36 }, ds); }) },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: round || c.datasets.length > 1, position: "bottom" },
          tooltip: { callbacks: { label: function (ctx) { var v = ctx.parsed.y !== undefined ? ctx.parsed.y : ctx.parsed;
            return (ctx.dataset.label ? ctx.dataset.label + ": " : "") + fmt.format(v); } } } },
        onClick: function (evt, items) {
          if (items.length && c.links && c.links[items[0].index]) window.location.href = c.links[items[0].index];
        },
        onHover: function (evt, items) { evt.native.target.style.cursor = items.length && c.links && c.links.length ? "pointer" : "default"; }
      }
    };
    if (!round) cfg.options.scales = { y: { beginAtZero: true, ticks: { precision: c.money ? undefined : 0 } } };
    new Chart(canvas, cfg);
  });
})();
