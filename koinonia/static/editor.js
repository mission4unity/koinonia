// The block editor: one campaign, one or more language versions, live preview, autosave.
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("editor-data").textContent);
  var L = data.labels;
  var variants = data.variants;
  var defaultLang = data.default_lang;
  var lang = variants[defaultLang] ? defaultLang : Object.keys(variants)[0];
  var dirty = false, saving = false, saveTimer = null, previewTimer = null, previewSeq = 0, changeSeq = 0;

  var FIELDS = {
    heading: [["text", "input", "wide"], ["level", "level"]],
    text: [["text", "textarea", "wide", 7, "editor.text_help"]],
    scripture: [["reference", "input"], ["translation", "input"], ["text", "textarea", "wide", 3]],
    image: [["src", "image", "wide"], ["alt", "input"], ["href", "url"], ["caption", "input", "wide"]],
    button: [["label", "input"], ["url", "url"]],
    event: [["title", "input", "wide"], ["date", "date"], ["location", "input"], ["time", "time"], ["end_time", "time"], ["description", "textarea", "wide", 3, "editor.text_help"]],
    prayer: [["title", "input", "wide"], ["items", "textarea", "wide", 5, "editor.items_help"]],
    donate: [["title", "input", "wide"], ["text", "textarea", "wide", 3], ["label", "input"], ["url", "url"]],
    video: [["url", "url", "wide"], ["title", "input"], ["thumbnail", "url", null, null, "editor.thumbnail_help"]],
    quote: [["text", "textarea", "wide", 3], ["author", "input"]],
    divider: [],
    spacer: [["size", "number"]]
  };
  var BASIC = ["heading", "text", "image", "button", "divider", "spacer"];
  var CHURCH = ["scripture", "event", "prayer", "donate", "video", "quote"];

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") n.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) n.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function current() { return variants[lang]; }
  function blocks() { return current().blocks; }

  // ------------------------------------------------------------ saving & preview
  function state(text) { document.getElementById("save-state").textContent = text; }
  function changed(structural) {
    dirty = true;
    changeSeq++;
    state(L["editor.unsaved"]);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 1200);
    clearTimeout(previewTimer);
    previewTimer = setTimeout(preview, structural ? 50 : 450);
  }
  function post(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": data.csrf }, body: JSON.stringify(body), credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; }); });
  }
  function save() {
    if (saving) { clearTimeout(saveTimer); saveTimer = setTimeout(save, 600); return Promise.resolve(); }
    saving = true;
    state(L["editor.saving"]);
    var seq = changeSeq;
    return post("/campaigns/" + data.id + "/content", { variants: variants, default_lang: defaultLang })
      .then(function () { saving = false; if (seq === changeSeq) { dirty = false; state(L["editor.saved"]); } })
      .catch(function (e) { saving = false; state(L["editor.error"] + " " + e.message); });
  }
  function preview() {
    var seq = ++previewSeq, v = current();
    post("/campaigns/" + data.id + "/preview", { lang: lang, subject: v.subject, preheader: v.preheader, blocks: v.blocks })
      .then(function (j) { if (seq === previewSeq) document.getElementById("preview").srcdoc = j.html; })
      .catch(function () {});
  }
  window.addEventListener("beforeunload", function (ev) {
    if (dirty) { save(); ev.preventDefault(); ev.returnValue = ""; }
  });
  document.querySelectorAll(".seg button").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll(".seg button").forEach(function (x) { x.classList.toggle("active", x === b); });
      document.getElementById("preview").style.width = b.getAttribute("data-width");
    });
  });

  // ------------------------------------------------------------ language tabs
  function renderTabs() {
    var box = document.getElementById("lang-tabs");
    box.innerHTML = "";
    Object.keys(variants).sort().forEach(function (code) {
      box.appendChild(el("button", {
        type: "button", role: "tab", "aria-selected": code === lang ? "true" : "false",
        onclick: function () { lang = code; renderAll(); }
      }, [(data.langs[code] || code) + " ", code === defaultLang ? el("span", { "class": "default-mark", text: "★" }) : null]));
    });
    var missing = Object.keys(data.langs).filter(function (c) { return !variants[c]; });
    if (missing.length) {
      var sel = el("select", { "aria-label": L["editor.add_language"], onchange: function () {
        if (!sel.value) return;
        variants[sel.value] = JSON.parse(JSON.stringify(current()));
        lang = sel.value;
        renderAll();
        changed(true);
      } }, [el("option", { value: "", text: "+ " + L["editor.add_language"] })].concat(missing.map(function (c) { return el("option", { value: c, text: data.langs[c] }); })));
      box.appendChild(sel);
    }
    if (lang !== defaultLang) {
      box.appendChild(el("button", { type: "button", "class": "btn-ghost", onclick: function () {
        if (!window.confirm(L["editor.confirm_remove_language"])) return;
        delete variants[lang];
        lang = defaultLang;
        renderAll();
        changed(true);
      } }, [L["editor.remove_language"]]));
    }
  }

  // ------------------------------------------------------------ subject & preheader
  function renderMeta() {
    var box = document.getElementById("meta"), v = current();
    box.innerHTML = "";
    var subject = el("input", { type: "text", value: v.subject || "", maxlength: "300", dir: "auto", oninput: function () { v.subject = subject.value; changed(); } });
    var pre = el("input", { type: "text", value: v.preheader || "", maxlength: "300", dir: "auto", oninput: function () { v.preheader = pre.value; changed(); } });
    box.appendChild(el("label", { "class": "field" }, [el("span", { "class": "label", text: L["editor.subject"] }), subject]));
    box.appendChild(el("label", { "class": "field" }, [el("span", { "class": "label", text: L["editor.preheader"] }), pre, el("small", { "class": "hint", text: L["editor.preheader_help"] })]));
    box.appendChild(el("small", { "class": "hint", text: L["editor.merge_help"] }));
  }

  // ------------------------------------------------------------ blocks
  function control(b, spec) {
    var key = spec[0], kind = spec[1], input;
    var update = function () { b[key] = input.value; changed(); };
    if (kind === "textarea") {
      input = el("textarea", { rows: String(spec[3] || 3), dir: "auto", oninput: update });
      input.value = b[key] || "";
    } else if (kind === "level") {
      input = el("select", { onchange: update }, [el("option", { value: "1", text: L["editor.level1"] }), el("option", { value: "2", text: L["editor.level2"] })]);
      input.value = b[key] || "1";
    } else if (kind === "image") {
      input = el("input", { type: "url", value: b[key] || "", placeholder: "https://", oninput: function () { update(); thumb.src = input.value; thumb.hidden = !input.value; } });
      var thumb = el("img", { "class": "thumb", alt: "", src: b[key] || "" });
      thumb.hidden = !b[key];
      var file = el("input", { type: "file", accept: "image/png,image/jpeg,image/gif,image/webp", hidden: true, onchange: function () {
        if (!file.files[0]) return;
        btnLabel.firstChild.textContent = L["editor.uploading"];
        window.koinoniaUpload(file.files[0]).then(function (url) {
          input.value = url; update(); thumb.src = url; thumb.hidden = false; btnLabel.firstChild.textContent = L["editor.upload"];
        }, function (err) { window.alert(err); btnLabel.firstChild.textContent = L["editor.upload"]; });
      } });
      var btnLabel = el("label", { "class": "btn btn-ghost" }, [L["editor.upload"], file]);
      return el("div", { "class": "field wide" }, [el("span", { "class": "label", text: L["f." + key] }), el("div", { "class": "with-upload" }, [input, btnLabel]), thumb]);
    } else {
      var type = { url: "url", date: "date", time: "time", number: "number" }[kind] || "text";
      input = el("input", { type: type, value: b[key] || "", dir: type === "text" ? "auto" : null, oninput: update,
        placeholder: kind === "url" ? (b.type === "donate" && data.donate_url ? data.donate_url : "https://") : null });
      if (kind === "number") { input.min = "4"; input.max = "120"; }
    }
    var kids = [el("span", { "class": "label", text: L["f." + key] }), input];
    if (spec[4]) kids.push(el("small", { "class": "hint", text: L[spec[4]] }));
    return el("label", { "class": "field" + (spec[2] ? " " + spec[2] : "") }, kids);
  }

  function move(i, d) {
    var list = blocks(), j = i + d;
    if (j < 0 || j >= list.length) return;
    var t = list[i]; list[i] = list[j]; list[j] = t;
    renderBlocks(); changed(true);
  }

  function renderBlocks() {
    var box = document.getElementById("blocks");
    box.innerHTML = "";
    var list = blocks();
    if (!list.length) box.appendChild(el("p", { "class": "muted", text: L["editor.empty"] }));
    list.forEach(function (b, i) {
      var head = el("div", { "class": "block-head" }, [
        el("strong", { text: L["block." + b.type] || b.type }),
        el("button", { type: "button", title: L["editor.up"], "aria-label": L["editor.up"], onclick: function () { move(i, -1); }, disabled: i === 0 }, ["↑"]),
        el("button", { type: "button", title: L["editor.down"], "aria-label": L["editor.down"], onclick: function () { move(i, 1); }, disabled: i === list.length - 1 }, ["↓"]),
        el("button", { type: "button", title: L["editor.duplicate"], onclick: function () { list.splice(i + 1, 0, JSON.parse(JSON.stringify(b))); renderBlocks(); changed(true); } }, [L["editor.duplicate"]]),
        el("button", { type: "button", "class": "del", title: L["editor.remove"], onclick: function () { list.splice(i, 1); renderBlocks(); changed(true); } }, [L["editor.remove"]])
      ]);
      var body = el("div", { "class": "block-body" }, (FIELDS[b.type] || []).map(function (spec) { return control(b, spec); }));
      box.appendChild(el("section", { "class": "block", "aria-label": L["block." + b.type] }, [head, FIELDS[b.type] && FIELDS[b.type].length ? body : null]));
    });
  }

  function newBlock(type) {
    var b = { type: type };
    (FIELDS[type] || []).forEach(function (f) { b[f[0]] = ""; });
    if (type === "heading") b.level = "2";
    if (type === "spacer") b.size = "24";
    if (type === "donate") { b.url = data.donate_url || ""; b.label = L["editor.donate_default"]; }
    return b;
  }

  function renderAdd() {
    var box = document.getElementById("add-bar");
    box.innerHTML = "";
    box.appendChild(el("span", { text: L["editor.add"] }));
    BASIC.concat(CHURCH).forEach(function (t) {
      box.appendChild(el("button", { type: "button", "class": CHURCH.indexOf(t) >= 0 ? "church" : "", onclick: function () {
        blocks().push(newBlock(t));
        renderBlocks(); changed(true);
        var all = document.querySelectorAll("#blocks .block");
        var last = all[all.length - 1];
        if (last) { last.scrollIntoView({ behavior: "smooth", block: "center" }); var f = last.querySelector("input,textarea,select"); if (f) f.focus({ preventScroll: true }); }
      } }, ["+ " + (L["block." + t] || t)]));
    });
  }

  function renderAll() { renderTabs(); renderMeta(); renderBlocks(); preview(); }

  Object.keys(variants).forEach(function (k) { if (!Array.isArray(variants[k].blocks)) variants[k].blocks = []; });
  renderAll();
  renderAdd();
  state(L["editor.saved"]);
})();
