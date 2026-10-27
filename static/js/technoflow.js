// Technoflow CRM — small shared behaviours. No business logic lives here;
// every action is validated again on the server.
(function () {
  "use strict";

  // Mobile sidebar toggle
  document.addEventListener("click", function (e) {
    const toggle = e.target.closest("[data-tf-toggle-nav]");
    if (toggle) {
      document.body.classList.toggle("tf-nav-open");
      return;
    }
    if (document.body.classList.contains("tf-nav-open") && !e.target.closest(".tf-sidebar")) {
      document.body.classList.remove("tf-nav-open");
    }
  });

  // Confirmation for sensitive actions: <form data-confirm="Deactivate this user?">
  document.addEventListener("submit", function (e) {
    const form = e.target;
    const message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      e.preventDefault();
      return;
    }
    // Loading indicator and double-submit protection
    const button = form.querySelector("button[type=submit]:not([data-no-spinner])");
    if (button && !form.hasAttribute("data-no-spinner")) {
      window.setTimeout(function () {
        button.disabled = true;
        button.insertAdjacentHTML("afterbegin",
          '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>');
      }, 0);
    }
  });

  // Auto-hide success messages after 6 s (errors stay until closed)
  document.querySelectorAll(".tf-messages .alert-success").forEach(function (el) {
    window.setTimeout(function () {
      if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(el).close();
    }, 6000);
  });
})();

// ---------------------------------------------------------------- Kanban boards
// Cards are moved between stages by drag-and-drop or by the stage drop-down on each
// card (keyboard / mobile). The server checks permissions and rules for every move.
(function () {
  "use strict";
  const board = document.querySelector(".tf-kanban[data-move-url]");
  if (!board) return;

  function csrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function move(cardId, stageId) {
    const url = board.dataset.moveUrl.replace("/0/", "/" + cardId + "/");
    const body = new URLSearchParams({ stage: stageId });
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
      body: body,
      credentials: "same-origin",
    }).then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (res) {
        if (res.data.redirect) { window.location.href = res.data.redirect; return; }
        if (!res.ok) { window.alert(res.data.error || "The card could not be moved."); }
        window.location.reload();
      })
      .catch(function () { window.alert("Connection problem. Please try again."); window.location.reload(); });
  }

  let dragged = null;
  board.addEventListener("dragstart", function (e) {
    const card = e.target.closest(".tf-kcard");
    if (!card) return;
    dragged = card;
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", card.dataset.id);
  });
  board.addEventListener("dragend", function () {
    if (dragged) dragged.classList.remove("dragging");
    board.querySelectorAll(".drag-over").forEach(function (c) { c.classList.remove("drag-over"); });
  });
  board.querySelectorAll(".tf-kcol").forEach(function (col) {
    col.addEventListener("dragover", function (e) { e.preventDefault(); col.classList.add("drag-over"); });
    col.addEventListener("dragleave", function () { col.classList.remove("drag-over"); });
    col.addEventListener("drop", function (e) {
      e.preventDefault();
      col.classList.remove("drag-over");
      if (!dragged || dragged.closest(".tf-kcol") === col) return;
      move(dragged.dataset.id, col.dataset.stage);
    });
  });
  board.addEventListener("change", function (e) {
    const sel = e.target.closest("select[data-move]");
    if (sel && sel.value) move(sel.dataset.move, sel.value);
  });
})();

// ---------------------------------------------------------------- dynamic form rows (quotation / invoice lines)
(function () {
  "use strict";
  document.querySelectorAll("[data-formset]").forEach(function (wrap) {
    const prefix = wrap.dataset.formset;
    const total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
    const tmpl = wrap.querySelector("template");
    const body = wrap.querySelector("[data-formset-body]");
    const addBtn = wrap.querySelector("[data-formset-add]");
    if (!total || !tmpl || !body || !addBtn) return;
    addBtn.addEventListener("click", function () {
      const index = parseInt(total.value, 10);
      const html = tmpl.innerHTML.replace(/__prefix__/g, index);
      body.insertAdjacentHTML("beforeend", html);
      total.value = index + 1;
      recalc(wrap);
    });
    wrap.addEventListener("input", function () { recalc(wrap); });
    wrap.addEventListener("change", function () { recalc(wrap); });
    recalc(wrap);
  });

  // Live preview only. The server recalculates every amount when the form is saved.
  function num(v) { const n = parseFloat(v); return isNaN(n) ? 0 : n; }
  function recalc(wrap) {
    let sub = 0, tax = 0;
    wrap.querySelectorAll("[data-line]").forEach(function (row) {
      const del = row.querySelector("input[name$='-DELETE']");
      const qty = num((row.querySelector("input[name$='-quantity']") || {}).value);
      const price = num((row.querySelector("input[name$='-unit_price']") || {}).value);
      const disc = num((row.querySelector("input[name$='-discount_pct']") || {}).value);
      const taxSel = row.querySelector("select[name$='-tax_rate']");
      const rate = taxSel && taxSel.selectedOptions[0] ? num(taxSel.selectedOptions[0].dataset.rate) : 0;
      const net = Math.round(qty * price * (1 - disc / 100) * 100) / 100;
      const out = row.querySelector("[data-line-total]");
      if (del && del.checked) { if (out) out.textContent = "—"; return; }
      if (out) out.textContent = net.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      sub += net; tax += Math.round(net * rate) / 100;
    });
    const fmt = function (v) { return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
    const s = wrap.querySelector("[data-sum-subtotal]"), t = wrap.querySelector("[data-sum-tax]"), g = wrap.querySelector("[data-sum-total]");
    if (s) s.textContent = fmt(sub);
    if (t) t.textContent = fmt(tax);
    if (g) g.textContent = fmt(sub + tax);
  }
})();

// Re-enable submit buttons when the page is shown again from the back/forward cache
window.addEventListener("pageshow", function (e) {
  if (!e.persisted) return;
  document.querySelectorAll("button[type=submit][disabled]").forEach(function (b) {
    b.disabled = false;
    const sp = b.querySelector(".spinner-border");
    if (sp) sp.remove();
  });
});
