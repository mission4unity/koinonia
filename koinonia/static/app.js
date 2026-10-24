// Small progressive enhancements. Every page works without this file.
(function () {
  "use strict";
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // Ask before destructive actions.
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest("[data-confirm]");
    if (!el) return;
    var only = el.getAttribute("data-confirm-if");
    if (only) {
      var sel = el.form && el.form.querySelector('[name="action"]');
      if (!sel || sel.value !== only) return;
    }
    if (!window.confirm(el.getAttribute("data-confirm"))) ev.preventDefault();
  });

  // "Select all" checkbox in tables.
  document.querySelectorAll("[data-check-all]").forEach(function (box) {
    box.addEventListener("change", function () {
      document.querySelectorAll('input[name="' + box.getAttribute("data-check-all") + '"]').forEach(function (c) { c.checked = box.checked; });
    });
  });

  // Bulk actions: only show the input that the chosen action needs.
  var bulk = document.getElementById("bulk");
  if (bulk) {
    var action = bulk.querySelector('[name="action"]');
    var sync = function () {
      var tag = bulk.querySelector('[name="tag"]'), list = bulk.querySelector('[name="list_id"]');
      if (tag) tag.hidden = action.value !== "tag";
      if (list) list.hidden = !(action.value === "list" || action.value === "unlist");
    };
    action.addEventListener("change", sync);
    sync();
  }

  // Read a CSV file into a textarea (nothing is uploaded until the form is sent).
  document.querySelectorAll("[data-read-into]").forEach(function (input) {
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () { document.getElementById(input.getAttribute("data-read-into")).value = reader.result; };
      reader.readAsText(file);
    });
  });

  // Copy-to-clipboard buttons.
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var src = document.getElementById(btn.getAttribute("data-copy"));
      var label = btn.textContent;
      var done = function () { btn.textContent = "✓"; setTimeout(function () { btn.textContent = label; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(src.value).then(done, function () { src.select(); });
      else { src.select(); document.execCommand("copy"); done(); }
    });
  });

  // Upload an image and put its address in a text field.
  document.querySelectorAll("[data-upload-into]").forEach(function (input) {
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      window.koinoniaUpload(file).then(function (url) {
        document.getElementById(input.getAttribute("data-upload-into")).value = url;
      }, function (err) { window.alert(err); });
    });
  });

  window.koinoniaUpload = function (file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        fetch("/upload", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ name: file.name, data: reader.result }) })
          .then(function (r) { return r.json().then(function (j) { return r.ok ? resolve(j.url) : reject(j.error || r.status); }); })
          .catch(function (e) { reject(String(e)); });
      };
      reader.onerror = function () { reject("read error"); };
      reader.readAsDataURL(file);
    });
  };
})();
