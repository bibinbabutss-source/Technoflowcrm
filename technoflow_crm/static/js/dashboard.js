/* Dashboard charts: data from /dashboard/chart/<key>/ (JSON); click a bar/point to open the records behind it. */
(function () {
  "use strict";
  var COLORS = ["#8C9A12", "#5F6062", "#2F6FB3", "#C47F00", "#7A4FA0", "#B42318"];
  var fmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
  document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
    fetch(canvas.getAttribute("data-chart"), { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        var box = canvas.parentNode;
        var total = d.datasets.reduce(function (s, ds) { return s + ds.data.reduce(function (a, b) { return a + (+b || 0); }, 0); }, 0);
        if (d.empty || !d.labels.length || total === 0) {
          box.innerHTML = '<div class="tf-empty h-100 d-flex align-items-center justify-content-center">' +
            (d.empty || "No data for this period yet.") + "</div>";
          return;
        }
        var horizontal = !!d.horizontal;
        new Chart(canvas, {
          type: d.type,
          data: {
            labels: d.labels,
            datasets: d.datasets.map(function (ds, i) {
              return Object.assign({ backgroundColor: COLORS[i % COLORS.length], borderColor: COLORS[i % COLORS.length],
                tension: 0.25, borderRadius: 3, maxBarThickness: 40 }, ds);
            })
          },
          options: {
            maintainAspectRatio: false, indexAxis: horizontal ? "y" : "x",
            plugins: { legend: { display: d.datasets.length > 1, position: "bottom" },
              tooltip: { callbacks: { label: function (c) {
                var v = horizontal ? c.parsed.x : c.parsed.y;
                return c.dataset.label + ": " + fmt.format(v) + (d.percent ? "%" : "");
              } } } },
            scales: (function () { var s = {}; s[horizontal ? "x" : "y"] = { beginAtZero: true,
              ticks: { callback: function (v) { return fmt.format(v) + (d.percent ? "%" : ""); } } }; return s; })(),
            onClick: function (evt, els) {
              if (els.length && d.links && d.links[els[0].index]) { window.location.href = d.links[els[0].index]; }
            },
            onHover: function (evt, els) { evt.native.target.style.cursor = els.length && d.links ? "pointer" : "default"; }
          }
        });
      })
      .catch(function () { canvas.parentNode.innerHTML = '<div class="tf-empty">Chart could not be loaded.</div>'; });
  });
})();
