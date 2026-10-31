/* Lead form, customer first: show the customer picker for an existing customer, the company details for a new one. */
(function () {
  "use strict";
  var radios = document.querySelectorAll("input[name=customer_mode]");
  if (!radios.length) return;
  function box(id) {
    var el = document.getElementById(id);
    return el ? el.closest(".col-md-6, .col-12") : null;
  }
  function sync() {
    var checked = document.querySelector("input[name=customer_mode]:checked");
    var mode = checked ? checked.value : "existing";
    var pick = box("id_customer");
    if (pick) pick.hidden = mode !== "existing";
    var confirmBox = box("id_confirm_new_customer");
    if (confirmBox) confirmBox.hidden = mode !== "new" || !document.getElementById("customer-dups");
    var name = document.getElementById("id_company_name");
    if (name) {
      name.readOnly = mode === "existing";
      name.placeholder = mode === "existing" ? "Taken from the chosen customer" : "Company name of the new customer";
    }
  }
  radios.forEach(function (r) { r.addEventListener("change", sync); });
  sync();
})();
