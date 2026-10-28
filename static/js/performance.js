/* Employee dashboard activity chart (data embedded in the page; no extra request). */
(function () {
  "use strict";
  var el = document.getElementById("act-data"), canvas = document.getElementById("act-chart");
  if (!el || !canvas || typeof Chart === "undefined") return;
  var d = JSON.parse(el.textContent);
  var colors = ["#2F6FB3", "#1E8E3E", "#C47F00"];
  var total = d.datasets.reduce(function (s, ds) { return s + ds.data.reduce(function (a, b) { return a + b; }, 0); }, 0);
  if (!total) { canvas.parentNode.innerHTML = '<div class="tf-empty h-100 d-flex align-items-center justify-content-center">No leads, visits or quotations recorded in this period.</div>'; return; }
  new Chart(canvas, { type: "bar", data: { labels: d.labels, datasets: d.datasets.map(function (ds, i) {
      return Object.assign({ backgroundColor: colors[i], borderRadius: 3, maxBarThickness: 28 }, ds); }) },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } },
      scales: { x: { stacked: false }, y: { beginAtZero: true, ticks: { precision: 0 } } } } });
})();
