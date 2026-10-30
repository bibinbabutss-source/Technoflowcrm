/* Searchable drop-downs (Tom Select, vendored): type to filter long lists in data-entry forms.
   Applies to <select class="form-select"> inside POST forms with more than 7 options, and to multi-selects.
   Opt out with data-plain. The original <select> keeps its name/value, so the server sees the same data. */
(function () {
  "use strict";
  if (typeof TomSelect === "undefined") return;
  function wanted(sel) {
    if (sel.tomselect || sel.hasAttribute("data-plain") || sel.hasAttribute("data-move") || sel.closest("template")) return false;
    if (!sel.classList.contains("form-select")) return false;
    var form = sel.closest("form");
    if (!form || (form.method || "").toLowerCase() !== "post") return false;
    return sel.multiple || sel.options.length > 7;
  }
  function enhance(root) {
    (root.querySelectorAll ? root.querySelectorAll("select") : []).forEach(function (sel) {
      if (!wanted(sel)) return;
      try {
        new TomSelect(sel, {
          maxOptions: 500, allowEmptyOption: true, create: false,
          plugins: sel.multiple ? ["remove_button"] : [],
          render: { no_results: function () { return '<div class="no-results">No match</div>'; } }
        });
      } catch (e) { /* leave the native select in place */ }
    });
  }
  document.addEventListener("DOMContentLoaded", function () { enhance(document); });
  new MutationObserver(function (records) {
    records.forEach(function (r) { r.addedNodes.forEach(function (n) { if (n.nodeType === 1) enhance(n); }); });
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
