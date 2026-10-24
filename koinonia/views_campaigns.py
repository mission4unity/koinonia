"""Campaigns: create, edit (block editor), test, schedule, send, report. Plus automations."""
import json
import os
import re
from datetime import datetime, timezone

from . import audience, compose, db, i18n, mailer, render, security, templates, ui, worker
from .app import UPLOADS, router
from .ui import T, checkbox, checks, field, inp, select
from .web import HTTPError, e, json_response, redirect

TEXT_FIELDS = {"text", "level", "reference", "translation", "src", "alt", "href", "caption", "label", "url", "title",
               "date", "time", "end_time", "location", "description", "items", "author", "size", "thumbnail"}
EDITOR_FIELDS = {
    "heading": ["text", "level"], "text": ["text"], "scripture": ["reference", "translation", "text"],
    "image": ["src", "alt", "href", "caption"], "button": ["label", "url"],
    "event": ["title", "date", "time", "end_time", "location", "description"], "prayer": ["title", "items"],
    "donate": ["title", "text", "label", "url"], "video": ["url", "title", "thumbnail"], "quote": ["text", "author"],
    "divider": [], "spacer": ["size"],
}


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_campaign(cid):
    c = db.one("SELECT * FROM campaigns WHERE id = ?", (_int(cid),))
    if not c:
        raise HTTPError(404)
    return c


def automation_of(c):
    return db.one("SELECT a.* FROM automations a JOIN automation_steps s ON s.automation_id = a.id WHERE s.campaign_id = ?", (c["id"],))


def clean_blocks(blocks):
    out = []
    for b in blocks if isinstance(blocks, list) else []:
        if not isinstance(b, dict) or b.get("type") not in EDITOR_FIELDS:
            continue
        nb = {"type": b["type"]}
        for k in EDITOR_FIELDS[b["type"]]:
            v = b.get(k, "")
            nb[k] = str(v)[:20000] if v is not None else ""
        out.append(nb)
    return out[:200]


def new_campaign(name, template, lang, kind="campaign"):
    cfg = db.settings()
    theme = json.dumps({"accent": cfg.get("accent_color") or "#3d5a40", "background": "#f4f1ea", "font": "sans"})
    first_list = db.val("SELECT id FROM lists ORDER BY id LIMIT 1")
    cid = db.run("""INSERT INTO campaigns(public_id, kind, name, list_ids, default_lang, track_opens, track_clicks, archive, theme)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (security.token(9), kind, name[:200], json.dumps([first_list] if first_list and kind == "campaign" else []), lang,
                  1 if cfg.get("track_opens") == "1" else 0, 1 if cfg.get("track_clicks") == "1" else 0,
                  1 if kind == "campaign" and cfg.get("archive_enabled") == "1" else 0, theme)).lastrowid
    db.run("INSERT INTO variants(campaign_id, lang, subject, preheader, blocks) VALUES (?, ?, ?, '', ?)",
           (cid, lang, templates.subject(template, lang), json.dumps(templates.blocks(template, lang, cfg.get("donate_url", "")))))
    return cid


def stats(cid):
    r = db.one("""SELECT COUNT(*) AS total, SUM(status = 'sent') AS sent, SUM(status = 'failed') AS failed, SUM(status = 'queued') AS queued,
                  SUM(status = 'skipped') AS skipped, SUM(opened_at IS NOT NULL) AS opened, SUM(clicked_at IS NOT NULL) AS clicked,
                  SUM(unsubscribed_at IS NOT NULL) AS unsubscribed FROM deliveries WHERE campaign_id = ?""", (cid,))
    return {k: (r[k] or 0) for k in r.keys()}


# ---------------------------------------------------------------- list & create
def campaigns(req):
    tab = req.get("tab") if req.get("tab") in ("draft", "scheduled", "sent") else ""
    where = "kind = 'campaign'"
    if tab == "draft":
        where += " AND status = 'draft'"
    elif tab == "scheduled":
        where += " AND status IN ('scheduled', 'sending', 'paused')"
    elif tab == "sent":
        where += " AND status = 'sent'"
    rows = db.q("SELECT * FROM campaigns WHERE %s ORDER BY COALESCE(sent_at, scheduled_at, updated_at) DESC LIMIT 200" % where)
    tabs = '<nav class="tabs">%s</nav>' % "".join('<a href="/campaigns%s" class="%s">%s</a>' % ("?tab=" + k if k else "", "active" if k == tab else "", e(T(req, "campaigns.tab_" + (k or "all")))) for k in ("", "draft", "scheduled", "sent"))
    if rows:
        trs = []
        for r in rows:
            s = stats(r["id"])
            when = ui.local_time(r["sent_at"] or r["scheduled_at"] or r["updated_at"], req)
            langs = ", ".join(x["lang"].upper() for x in db.q("SELECT lang FROM variants WHERE campaign_id = ? ORDER BY lang", (r["id"],)))
            href = "/campaigns/%d/edit" % r["id"] if r["status"] == "draft" else "/campaigns/%d/report" % r["id"]
            trs.append('<tr><td><a href="%s"><strong>%s</strong></a><br><small class="muted">%s</small></td><td>%s</td><td><small>%s</small></td>'
                       '<td class="num">%d</td><td class="num">%s</td><td class="num">%s</td></tr>' % (
                           href, e(r["name"]), e(langs), ui.badge(req, r["status"]), when, s["sent"],
                           ui.pct(s["opened"], s["sent"]) if r["track_opens"] else "–", ui.pct(s["clicked"], s["sent"]) if r["track_clicks"] else "–"))
        body = tabs + '<div class="card flush"><table class="table"><thead><tr><th>%s</th><th>%s</th><th>%s</th><th class="num">%s</th><th class="num">%s</th><th class="num">%s</th></tr></thead><tbody>%s</tbody></table></div>' % (
            e(T(req, "common.name")), e(T(req, "common.status")), e(T(req, "common.date")), e(T(req, "report.sent")), e(T(req, "report.opened")), e(T(req, "report.clicked")), "".join(trs))
    else:
        body = tabs + ui.empty(req, T(req, "campaigns.empty"), '<a class="btn btn-primary" href="/campaigns/new">%s</a>' % e(T(req, "campaigns.new")))
    return ui.page(req, T(req, "nav.campaigns"), body, "campaigns", '<a class="btn btn-primary" href="/campaigns/new">%s</a>' % e(T(req, "campaigns.new")))


def campaign_new(req):
    langs = ui.content_langs()
    if req.method == "POST":
        tpl = req.get("template") if req.get("template") in templates.TEMPLATES else "blank"
        lang = req.get("lang") if req.get("lang") in i18n.LANG_NAMES else langs[0]
        name = req.get("name").strip() or T(req, "tpl.%s.name" % tpl)
        cid = new_campaign(name, tpl, lang)
        return redirect("/campaigns/%d/edit" % cid)
    cards = "".join('<label class="tpl"><input type="radio" name="template" value="%s"%s><span class="tpl-card"><span class="tpl-art tpl-%s" aria-hidden="true"></span>'
                    '<strong>%s</strong><small>%s</small></span></label>' % (
                        t, " checked" if t == "newsletter" else "", t, e(T(req, "tpl.%s.name" % t)), e(T(req, "tpl.%s.desc" % t))) for t in templates.TEMPLATES)
    body = '<form method="post" class="stack">%s<div class="card stack"><div class="grid2">%s%s</div></div><h2>%s</h2><div class="tpl-grid">%s</div><div class="form-actions"><button class="btn btn-primary">%s</button></div></form>' % (
        ui.csrf(req), field(T(req, "common.name"), inp("name", "", placeholder=T(req, "campaigns.name_placeholder"), autofocus=True)),
        field(T(req, "campaigns.main_language"), select("lang", ui.lang_options(langs), langs[0]), T(req, "campaigns.main_language_help")),
        e(T(req, "campaigns.choose_template")), cards, e(T(req, "campaigns.create")))
    return ui.page(req, T(req, "campaigns.new"), body, "campaigns")


def campaign_show(req, cid):
    c = get_campaign(cid)
    return redirect("/campaigns/%d/%s" % (c["id"], "edit" if c["status"] == "draft" or c["kind"] == "automation" else "report"))


# ---------------------------------------------------------------- editor
def editor_labels(req):
    keys = ["block." + k for k in EDITOR_FIELDS] + ["f." + k for k in TEXT_FIELDS] + [
        "editor.add", "editor.up", "editor.down", "editor.duplicate", "editor.remove", "editor.saved", "editor.saving", "editor.unsaved",
        "editor.error", "editor.upload", "editor.uploading", "editor.subject", "editor.preheader", "editor.preheader_help",
        "editor.add_language", "editor.remove_language", "editor.confirm_remove_language", "editor.text_help", "editor.items_help",
        "editor.level1", "editor.level2", "editor.donate_default", "editor.empty", "editor.merge_help", "editor.desktop", "editor.mobile",
        "editor.copy_from", "editor.thumbnail_help"]
    return {k: T(req, k) for k in keys}


def campaign_edit(req, cid):
    c = get_campaign(cid)
    auto = automation_of(c) if c["kind"] == "automation" else None
    if c["status"] not in ("draft",) and c["kind"] == "campaign":
        return redirect("/campaigns/%d/report" % c["id"])
    variants = {v["lang"]: {"subject": v["subject"], "preheader": v["preheader"], "blocks": compose.blocks_of(v)}
                for v in db.q("SELECT * FROM variants WHERE campaign_id = ?", (c["id"],))}
    data = {
        "id": c["id"], "csrf": req.session["csrf"], "default_lang": c["default_lang"], "variants": variants,
        "langs": {k: i18n.LANG_NAMES[k] for k in ui.content_langs() + [l for l in variants if l not in ui.content_langs()] if k in i18n.LANG_NAMES},
        "labels": editor_labels(req), "donate_url": db.setting("donate_url"),
    }
    tabs = _tabs(req, c, "content")
    editor = ('<div class="editor" id="editor"><div class="editor-main"><div class="lang-tabs" id="lang-tabs" role="tablist"></div>'
              '<div class="card stack" id="meta"></div><div id="blocks" class="blocks"></div><div class="add-bar" id="add-bar"></div></div>'
              '<div class="editor-preview"><div class="preview-bar"><span id="save-state" class="muted small" aria-live="polite"></span>'
              '<span class="seg"><button type="button" data-width="100%%" class="active">%s</button><button type="button" data-width="390px">%s</button></span></div>'
              '<iframe id="preview" title="%s" sandbox=""></iframe></div></div>'
              '<script type="application/json" id="editor-data">%s</script><script src="/static/editor.js?v=%s" defer></script>') % (
        e(T(req, "editor.desktop")), e(T(req, "editor.mobile")), e(T(req, "editor.preview")),
        json.dumps(data).replace("</", "<\\/"), ui.V)
    back = '<a class="btn btn-ghost" href="/automations/%d">&larr; %s</a>' % (auto["id"], e(auto["name"])) if auto else ""
    return ui.page(req, c["name"], tabs + editor, "automations" if auto else "campaigns", back)


def _tabs(req, c, active):
    items = [("content", "/campaigns/%d/edit" % c["id"]), ("settings", "/campaigns/%d/settings" % c["id"]), ("send", "/campaigns/%d/send" % c["id"])]
    return '<nav class="tabs">%s</nav>' % "".join('<a href="%s" class="%s">%s</a>' % (h, "active" if k == active else "", e(T(req, "campaigns.tab_" + k)))
                                                  for k, h in items)


def campaign_content(req, cid):
    c = get_campaign(cid)
    if c["kind"] == "campaign" and c["status"] != "draft":
        return json_response({"error": T(req, "campaigns.locked")}, 409)
    data = req.json()
    if not isinstance(data, dict) or not isinstance(data.get("variants"), dict):
        raise HTTPError(400)
    variants = {k: v for k, v in data["variants"].items() if k in i18n.LANG_NAMES and isinstance(v, dict)}
    if not variants:
        raise HTTPError(400)
    default = data.get("default_lang") if data.get("default_lang") in variants else (c["default_lang"] if c["default_lang"] in variants else next(iter(variants)))
    db.run("DELETE FROM variants WHERE campaign_id = ? AND lang NOT IN (%s)" % ",".join("?" * len(variants)), [c["id"]] + list(variants))
    for lang, v in variants.items():
        db.run("""INSERT INTO variants(campaign_id, lang, subject, preheader, blocks) VALUES (?, ?, ?, ?, ?)
                  ON CONFLICT(campaign_id, lang) DO UPDATE SET subject = excluded.subject, preheader = excluded.preheader, blocks = excluded.blocks""",
               (c["id"], lang, str(v.get("subject", ""))[:300], str(v.get("preheader", ""))[:300], json.dumps(clean_blocks(v.get("blocks")))))
    db.run("UPDATE campaigns SET default_lang = ?, updated_at = datetime('now') WHERE id = ?", (default, c["id"]))
    return json_response({"ok": True})


def campaign_preview(req, cid):
    c = get_campaign(cid)
    data = req.json() or {}
    lang = data.get("lang") if data.get("lang") in i18n.LANG_NAMES else c["default_lang"]
    sample = {"first_name": (req.user["name"] or "").split(" ")[0], "last_name": " ".join((req.user["name"] or "").split(" ")[1:]),
              "email": req.user["email"], "token": "preview", "lang": lang}
    camp = dict(c, default_lang=lang)
    built = compose.build(camp, lang, sample, None, blocks=clean_blocks(data.get("blocks")), subject=str(data.get("subject", "")),
                          preheader=str(data.get("preheader", "")), tracking=False)
    # The preview sits in a sandboxed iframe; make sure links never navigate the frame.
    html = built["html"].replace("<head>", '<head><base target="_blank">', 1)
    return json_response({"html": html, "subject": built["subject"]})


def upload(req):
    data = req.json() or {}
    import base64
    try:
        raw = base64.b64decode(str(data.get("data", "")).split(",")[-1], validate=False)
    except (ValueError, TypeError):
        raise HTTPError(400)
    kinds = [(b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif")]
    ext = next((x for sig, x in kinds if raw.startswith(sig)), None)
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        ext = "webp"
    if not ext:
        return json_response({"error": T(req, "editor.bad_image")}, 400)
    if len(raw) > 5 * 1024 * 1024:
        return json_response({"error": T(req, "editor.too_big")}, 413)
    name = "%s.%s" % (security.token(12).replace("-", "x").replace("_", "y"), ext)
    os.makedirs(UPLOADS, exist_ok=True)
    with open(os.path.join(UPLOADS, name), "wb") as f:
        f.write(raw)
    return json_response({"url": "/uploads/" + name})


# ---------------------------------------------------------------- settings tab
def campaign_settings(req, cid):
    c = get_campaign(cid)
    if c["kind"] == "campaign" and c["status"] != "draft":
        return redirect("/campaigns/%d/report" % c["id"])
    theme = db.jl(c["theme"], {}) or {}
    if req.method == "POST":
        name = req.get("name").strip()[:200] or c["name"]
        from_email = req.get("from_email").strip()
        reply_to = req.get("reply_to").strip()
        if (from_email and not security.valid_email(from_email)) or (reply_to and not security.valid_email(reply_to)):
            ui.flash(req, T(req, "err.email"), "error")
            return redirect(req.path)
        hexok = lambda v, d: v if render.HEX.match(v or "") else d
        new_theme = {"accent": hexok(req.get("accent"), theme.get("accent") or "#3d5a40"),
                     "background": hexok(req.get("background"), theme.get("background") or "#f4f1ea"),
                     "font": req.get("font") if req.get("font") in render.FONTS else "sans"}
        db.run("""UPDATE campaigns SET name = ?, list_ids = ?, tag_ids = ?, from_name = ?, from_email = ?, reply_to = ?,
                  track_opens = ?, track_clicks = ?, archive = ?, theme = ?, updated_at = datetime('now') WHERE id = ?""",
               (name, json.dumps([int(x) for x in req.getlist("lists") if x.isdigit()]), json.dumps([int(x) for x in req.getlist("tags") if x.isdigit()]),
                req.get("from_name").strip()[:120], from_email, reply_to, 1 if req.get("track_opens") else 0, 1 if req.get("track_clicks") else 0,
                1 if req.get("archive") else 0, json.dumps(new_theme), c["id"]))
        ui.flash(req, T(req, "common.saved"))
        return redirect(req.path)
    cfg = db.settings()
    lists = db.q("SELECT * FROM lists ORDER BY name")
    tags = db.q("SELECT * FROM tags ORDER BY name")
    audience_html = ""
    if c["kind"] == "campaign":
        audience_html = '<fieldset class="card stack"><legend>%s</legend>%s%s<p class="muted" id="aud-count">%s</p></fieldset>' % (
            e(T(req, "campaigns.audience")),
            field(T(req, "nav.lists"), checks("lists", [(l["id"], l["name"]) for l in lists], db.jl(c["list_ids"])) if lists else '<p class="muted">%s</p>' % e(T(req, "lists.empty"))),
            field(T(req, "campaigns.only_tags"), checks("tags", [(t["id"], t["name"]) for t in tags], db.jl(c["tag_ids"])) if tags else '<p class="muted small">%s</p>' % e(T(req, "campaigns.no_tags")), T(req, "campaigns.only_tags_help")),
            e(T(req, "campaigns.audience_count", n=audience.audience_count(db.jl(c["list_ids"]), db.jl(c["tag_ids"])))))
    sender = '<fieldset class="card stack"><legend>%s</legend><div class="grid2">%s%s</div>%s</fieldset>' % (
        e(T(req, "campaigns.sender")),
        field(T(req, "settings.from_name"), inp("from_name", c["from_name"], placeholder=cfg.get("from_name") or cfg.get("org_name"))),
        field(T(req, "settings.from_email"), inp("from_email", c["from_email"], "email", placeholder=cfg.get("from_email"))),
        field(T(req, "settings.reply_to"), inp("reply_to", c["reply_to"], "email", placeholder=cfg.get("reply_to")), T(req, "campaigns.sender_help")))
    look = '<fieldset class="card stack"><legend>%s</legend><div class="grid3">%s%s%s</div></fieldset>' % (
        e(T(req, "campaigns.look")),
        field(T(req, "campaigns.accent"), inp("accent", theme.get("accent") or "#3d5a40", "color")),
        field(T(req, "campaigns.background"), inp("background", theme.get("background") or "#f4f1ea", "color")),
        field(T(req, "campaigns.font"), select("font", [("sans", T(req, "campaigns.font_sans")), ("serif", T(req, "campaigns.font_serif"))], theme.get("font", "sans"))))
    privacy = '<fieldset class="card stack"><legend>%s</legend>%s%s%s<small class="hint">%s</small></fieldset>' % (
        e(T(req, "campaigns.privacy")), checkbox("track_opens", c["track_opens"], T(req, "campaigns.track_opens")),
        checkbox("track_clicks", c["track_clicks"], T(req, "campaigns.track_clicks")),
        checkbox("archive", c["archive"], T(req, "campaigns.archive")) if c["kind"] == "campaign" else "", e(T(req, "campaigns.privacy_help")))
    body = _tabs(req, c, "settings") + '<form method="post" class="stack">%s<div class="card">%s</div>%s%s%s%s<div class="form-actions"><button class="btn btn-primary">%s</button></div></form>' % (
        ui.csrf(req), field(T(req, "campaigns.internal_name"), inp("name", c["name"], required=True)), audience_html, sender, look, privacy, e(T(req, "common.save")))
    return ui.page(req, c["name"], body, "campaigns" if c["kind"] == "campaign" else "automations")


# ---------------------------------------------------------------- send tab
def problems(req, c):
    out = []
    cfg = db.settings()
    variants = db.q("SELECT * FROM variants WHERE campaign_id = ?", (c["id"],))
    for v in variants:
        name = i18n.LANG_NAMES.get(v["lang"], v["lang"])
        if not v["subject"].strip():
            out.append(T(req, "check.no_subject", lang=name))
        if not compose.blocks_of(v):
            out.append(T(req, "check.no_content", lang=name))
    if not security.valid_email(c["from_email"] or cfg.get("from_email", "")):
        out.append(T(req, "check.no_sender"))
    if c["kind"] == "campaign":
        if not db.jl(c["list_ids"]):
            out.append(T(req, "check.no_lists"))
        elif audience.audience_count(db.jl(c["list_ids"]), db.jl(c["tag_ids"])) == 0:
            out.append(T(req, "check.no_recipients"))
    if not cfg.get("org_address", "").strip():
        out.append(T(req, "check.no_address"))
    return out


def campaign_send_page(req, cid):
    c = get_campaign(cid)
    if c["kind"] == "campaign" and c["status"] != "draft":
        return redirect("/campaigns/%d/report" % c["id"])
    issues = problems(req, c)
    cfg = db.settings()
    variants = db.q("SELECT lang, subject FROM variants WHERE campaign_id = ? ORDER BY lang", (c["id"],))
    summary = '<dl class="meta">%s</dl>' % "".join('<dt>%s</dt><dd>%s</dd>' % (e(k), v) for k, v in [
        (T(req, "campaigns.languages"), e(", ".join("%s: “%s”" % (i18n.LANG_NAMES.get(v["lang"], v["lang"]), v["subject"]) for v in variants))),
        (T(req, "campaigns.sender"), e("%s <%s>" % (c["from_name"] or cfg.get("from_name") or cfg.get("org_name"), c["from_email"] or cfg.get("from_email")))),
    ] + ([(T(req, "campaigns.audience"), e(T(req, "campaigns.audience_count", n=audience.audience_count(db.jl(c["list_ids"]), db.jl(c["tag_ids"])))))] if c["kind"] == "campaign" else []))
    check = ('<div class="flash flash-error"><strong>%s</strong><ul>%s</ul></div>' % (e(T(req, "check.title")), "".join("<li>%s</li>" % e(i) for i in issues))
             if issues else '<div class="flash flash-ok">%s</div>' % e(T(req, "check.ok")))
    dev = '<p class="flash flash-warn">%s</p>' % e(T(req, "check.file_transport")) if cfg.get("transport") != "smtp" else ""
    test = ('<form method="post" action="/campaigns/%d/test" class="card stack">%s<h2>%s</h2>%s<div class="form-actions"><button class="btn">%s</button></div></form>') % (
        c["id"], ui.csrf(req), e(T(req, "send.test_title")),
        field(T(req, "send.test_to"), inp("to", req.user["email"], required=True), T(req, "send.test_help")), e(T(req, "send.test_button")))
    go = ""
    if c["kind"] == "campaign":
        go = ('<form method="post" action="/campaigns/%d/send" class="card stack">%s<h2>%s</h2>'
              '<div class="radios"><label class="check"><input type="radio" name="when" value="now" checked> <span>%s</span></label>'
              '<label class="check"><input type="radio" name="when" value="later"> <span>%s</span></label></div>%s'
              '<div class="form-actions"><button class="btn btn-primary"%s data-confirm="%s">%s</button></div></form>') % (
            c["id"], ui.csrf(req), e(T(req, "send.title")), e(T(req, "send.now")), e(T(req, "send.later")),
            field(T(req, "send.at"), inp("at", "", "datetime-local"), T(req, "send.timezone", tz=cfg.get("timezone"))),
            " disabled" if issues else "", e(T(req, "send.confirm")), e(T(req, "send.button")))
    else:
        auto = automation_of(c)
        go = '<p class="card muted">%s <a href="/automations/%d">%s</a></p>' % (e(T(req, "send.automation_note")), auto["id"], e(auto["name"])) if auto else ""
    body = _tabs(req, c, "send") + '<div class="split"><div class="stack">%s%s%s</div><div class="stack"><section class="card"><h2>%s</h2>%s</section>%s</div></div>' % (
        check, dev, go, e(T(req, "send.summary")), summary, test)
    return ui.page(req, c["name"], body, "campaigns" if c["kind"] == "campaign" else "automations")


def campaign_test(req, cid):
    c = get_campaign(cid)
    to = [x.strip() for x in req.get("to").replace(";", ",").split(",") if x.strip()][:5]
    if not to or not all(security.valid_email(x) for x in to):
        ui.flash(req, T(req, "err.email"), "error")
        return redirect("/campaigns/%d/send" % c["id"])
    cfg = db.settings()
    if not security.valid_email(c["from_email"] or cfg.get("from_email", "")):
        ui.flash(req, T(req, "check.no_sender"), "error")
        return redirect("/campaigns/%d/send" % c["id"])
    sample = {"first_name": (req.user["name"] or "").split(" ")[0], "last_name": "", "email": req.user["email"], "token": None, "lang": ""}
    try:
        with mailer.Sender(cfg) as sender:
            for v in db.q("SELECT lang FROM variants WHERE campaign_id = ?", (c["id"],)):
                built = compose.build(c, v["lang"], sample, None, cfg, tracking=False)
                built["subject"] = "[TEST %s] %s" % (v["lang"].upper(), built["subject"])
                for addr in to:
                    sender.send(compose.message(built, addr))
    except (mailer.TemporaryError, mailer.PermanentError, mailer.MessageError) as ex:
        ui.flash(req, T(req, "send.test_failed", error=str(ex)), "error")
        return redirect("/campaigns/%d/send" % c["id"])
    ui.flash(req, T(req, "send.test_sent", to=", ".join(to)))
    return redirect("/campaigns/%d/send" % c["id"])


def parse_local(value):
    """datetime-local string in the organisation's time zone -> UTC 'YYYY-MM-DD HH:MM:SS'."""
    dt = datetime.strptime(value.strip()[:16], "%Y-%m-%dT%H:%M")
    try:
        from zoneinfo import ZoneInfo
        dt = dt.replace(tzinfo=ZoneInfo(db.setting("timezone") or "UTC"))
    except Exception:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def campaign_send(req, cid):
    c = get_campaign(cid)
    if c["kind"] != "campaign" or c["status"] != "draft":
        raise HTTPError(400)
    if problems(req, c):
        ui.flash(req, T(req, "check.title"), "error")
        return redirect("/campaigns/%d/send" % c["id"])
    if req.get("when") == "later":
        try:
            at = parse_local(req.get("at"))
        except ValueError:
            ui.flash(req, T(req, "send.bad_date"), "error")
            return redirect("/campaigns/%d/send" % c["id"])
        if at <= worker.utcnow():
            ui.flash(req, T(req, "send.past_date"), "error")
            return redirect("/campaigns/%d/send" % c["id"])
        db.run("UPDATE campaigns SET status = 'scheduled', scheduled_at = ?, updated_at = datetime('now') WHERE id = ?", (at, c["id"]))
        ui.flash(req, T(req, "send.scheduled"))
    else:
        db.run("UPDATE campaigns SET status = 'sending', scheduled_at = datetime('now'), updated_at = datetime('now') WHERE id = ?", (c["id"],))
        n = worker.enqueue(c["id"])
        ui.flash(req, T(req, "send.started", n=n))
    return redirect("/campaigns/%d/report" % c["id"])


def campaign_action(req, cid, action):
    c = get_campaign(cid)
    transitions = {"cancel": ("scheduled", "draft"), "pause": ("sending", "paused"), "resume": ("paused", "sending")}
    if action in transitions:
        frm, to = transitions[action]
        db.run("UPDATE campaigns SET status = ?, updated_at = datetime('now') WHERE id = ? AND status = ?", (to, c["id"], frm))
        if action == "cancel":
            db.run("UPDATE campaigns SET scheduled_at = NULL WHERE id = ?", (c["id"],))
        return redirect("/campaigns/%d" % c["id"])
    if action == "duplicate":
        nid = db.run("""INSERT INTO campaigns(public_id, kind, name, list_ids, tag_ids, default_lang, from_name, from_email, reply_to, track_opens, track_clicks, archive, theme)
                        SELECT ?, 'campaign', ?, list_ids, tag_ids, default_lang, from_name, from_email, reply_to, track_opens, track_clicks, archive, theme
                        FROM campaigns WHERE id = ?""", (security.token(9), (T(req, "campaigns.copy_of", name=c["name"]))[:200], c["id"])).lastrowid
        db.run("INSERT INTO variants(campaign_id, lang, subject, preheader, blocks) SELECT ?, lang, subject, preheader, blocks FROM variants WHERE campaign_id = ?", (nid, c["id"]))
        ui.flash(req, T(req, "campaigns.duplicated"))
        return redirect("/campaigns/%d/edit" % nid)
    if action == "delete":
        if c["kind"] != "campaign" or c["status"] in ("sending",):
            raise HTTPError(400)
        db.run("DELETE FROM campaigns WHERE id = ?", (c["id"],))
        ui.flash(req, T(req, "common.deleted"))
        return redirect("/campaigns")
    raise HTTPError(404)


# ---------------------------------------------------------------- report
def report(req, cid):
    c = get_campaign(cid)
    if c["status"] == "draft" and c["kind"] == "campaign":
        return redirect("/campaigns/%d/edit" % c["id"])
    s = stats(c["id"])
    tiles = [("report.recipients", s["total"]), ("report.sent", s["sent"])]
    if c["track_opens"]:
        tiles.append(("report.opened", "%s <small>%d</small>" % (ui.pct(s["opened"], s["sent"]), s["opened"])))
    if c["track_clicks"]:
        tiles.append(("report.clicked", "%s <small>%d</small>" % (ui.pct(s["clicked"], s["sent"]), s["clicked"])))
    tiles += [("report.unsubscribed", s["unsubscribed"]), ("report.failed", s["failed"])]
    tiles_html = '<div class="stats">%s</div>' % "".join('<div class="stat"><span>%s</span><strong>%s</strong></div>' % (e(T(req, k)), v) for k, v in tiles)
    progress = ""
    if c["status"] in ("sending", "paused") and s["total"]:
        done = s["total"] - s["queued"]
        progress = '<div class="card"><p>%s</p><progress max="%d" value="%d"></progress></div>' % (e(T(req, "report.progress", done=done, total=s["total"])), s["total"], done)
    by_lang = db.q("""SELECT lang, COUNT(*) AS n, SUM(opened_at IS NOT NULL) AS o, SUM(clicked_at IS NOT NULL) AS k FROM deliveries
                      WHERE campaign_id = ? AND status = 'sent' GROUP BY lang ORDER BY n DESC""", (c["id"],))
    lang_table = ""
    if by_lang:
        lang_table = '<section class="card"><h2>%s</h2><table class="table"><thead><tr><th>%s</th><th class="num">%s</th><th class="num">%s</th><th class="num">%s</th></tr></thead><tbody>%s</tbody></table></section>' % (
            e(T(req, "report.by_language")), e(T(req, "common.language")), e(T(req, "report.sent")), e(T(req, "report.opened")), e(T(req, "report.clicked")),
            "".join('<tr><td>%s</td><td class="num">%d</td><td class="num">%s</td><td class="num">%s</td></tr>' % (
                e(i18n.LANG_NAMES.get(r["lang"], r["lang"])), r["n"], ui.pct(r["o"] or 0, r["n"]) if c["track_opens"] else "–", ui.pct(r["k"] or 0, r["n"]) if c["track_clicks"] else "–") for r in by_lang))
    links = db.q("""SELECT l.url, COUNT(k.delivery_id) AS total, COUNT(DISTINCT k.delivery_id) AS people FROM links l LEFT JOIN clicks k ON k.link_id = l.id
                    WHERE l.campaign_id = ? GROUP BY l.id ORDER BY people DESC, total DESC""", (c["id"],))
    link_table = ""
    if links and c["track_clicks"]:
        link_table = '<section class="card"><h2>%s</h2><table class="table"><thead><tr><th>%s</th><th class="num">%s</th><th class="num">%s</th></tr></thead><tbody>%s</tbody></table></section>' % (
            e(T(req, "report.links")), e(T(req, "report.link")), e(T(req, "report.people")), e(T(req, "report.total_clicks")),
            "".join('<tr><td class="break"><a href="%s" target="_blank" rel="noopener">%s</a></td><td class="num">%d</td><td class="num">%d</td></tr>' % (
                e(l["url"]), e(l["url"]), l["people"], l["total"]) for l in links))
    failed = db.q("""SELECT d.error, c.email FROM deliveries d LEFT JOIN contacts c ON c.id = d.contact_id WHERE d.campaign_id = ? AND d.status = 'failed' LIMIT 50""", (c["id"],))
    fail_table = ""
    if failed:
        fail_table = '<section class="card"><h2>%s</h2><table class="table"><tbody>%s</tbody></table></section>' % (
            e(T(req, "report.failures")), "".join('<tr><td>%s</td><td><small class="muted">%s</small></td></tr>' % (e(f["email"] or "—"), e(f["error"])) for f in failed))
    meta = '<p class="muted">%s %s</p>' % (ui.badge(req, c["status"]), e(
        T(req, "report.sent_at", at=ui.local_time(c["sent_at"], req)) if c["sent_at"] else
        T(req, "report.scheduled_for", at=ui.local_time(c["scheduled_at"], req)) if c["scheduled_at"] else ""))
    btn = lambda action, label, cls="btn", confirm="": '<form method="post" action="/campaigns/%d/%s" class="inline">%s<button class="%s"%s>%s</button></form>' % (
        c["id"], action, ui.csrf(req), cls, ' data-confirm="%s"' % e(confirm) if confirm else "", e(T(req, label)))
    actions = ""
    if c["kind"] == "campaign":
        if c["status"] == "scheduled":
            actions += btn("cancel", "report.cancel", "btn")
        if c["status"] == "sending":
            actions += btn("pause", "report.pause")
        if c["status"] == "paused":
            actions += btn("resume", "report.resume", "btn btn-primary")
        actions += btn("duplicate", "campaigns.duplicate")
        if c["status"] != "sending":
            actions += btn("delete", "common.delete", "btn btn-danger", T(req, "campaigns.confirm_delete"))
        if c["archive"] and c["status"] == "sent":
            actions = '<a class="btn btn-ghost" href="/archive/%s" target="_blank" rel="noopener">%s</a>' % (e(c["public_id"]), e(T(req, "report.public_page"))) + actions
    privacy = '<p class="muted small">%s</p>' % e(T(req, "report.privacy_note"))
    refresh = '<meta http-equiv="refresh" content="10">' if c["status"] == "sending" else ""
    body = refresh + meta + progress + tiles_html + '<div class="split even">%s%s</div>%s%s' % (lang_table, link_table, fail_table, privacy)
    return ui.page(req, c["name"], body, "campaigns" if c["kind"] == "campaign" else "automations", actions)


# ---------------------------------------------------------------- automations
def automations(req):
    rows = db.q("""SELECT a.*, l.name AS list_name, (SELECT COUNT(*) FROM automation_steps s WHERE s.automation_id = a.id) AS steps,
                   (SELECT COUNT(*) FROM enrollments n WHERE n.automation_id = a.id) AS enrolled FROM automations a LEFT JOIN lists l ON l.id = a.list_id ORDER BY a.name""")
    if rows:
        body = '<div class="card flush"><table class="table"><thead><tr><th>%s</th><th>%s</th><th>%s</th><th class="num">%s</th><th class="num">%s</th></tr></thead><tbody>%s</tbody></table></div>' % (
            e(T(req, "common.name")), e(T(req, "auto.trigger")), e(T(req, "common.status")), e(T(req, "auto.steps")), e(T(req, "auto.enrolled")),
            "".join('<tr><td><a href="/automations/%d">%s</a></td><td>%s</td><td>%s</td><td class="num">%d</td><td class="num">%d</td></tr>' % (
                r["id"], e(r["name"]), e(T(req, "auto.when_joins", list=r["list_name"] or "—")), ui.badge(req, "active" if r["active"] else "inactive"), r["steps"], r["enrolled"]) for r in rows))
    else:
        body = ui.empty(req, T(req, "auto.empty"), '<a class="btn btn-primary" href="/automations/new">%s</a>' % e(T(req, "auto.new")))
    intro = '<p class="muted narrow">%s</p>' % e(T(req, "auto.intro"))
    return ui.page(req, T(req, "nav.automations"), intro + body, "automations", '<a class="btn btn-primary" href="/automations/new">%s</a>' % e(T(req, "auto.new")))


def automation_new(req):
    lists = db.q("SELECT * FROM lists ORDER BY name")
    if req.method == "POST":
        name = req.get("name").strip()[:120] or T(req, "auto.default_name")
        list_id = _int(req.get("list_id")) or None
        if not list_id or not db.val("SELECT 1 FROM lists WHERE id = ?", (list_id,)):
            ui.flash(req, T(req, "auto.need_list"), "error")
            return redirect("/automations/new")
        aid = db.run("INSERT INTO automations(name, list_id, active) VALUES (?, ?, 0)", (name, list_id)).lastrowid
        lang = ui.content_langs()[0]
        cid = new_campaign(T(req, "auto.step_name", n=1), "welcome", lang, "automation")
        db.run("INSERT INTO automation_steps(automation_id, position, delay_days, campaign_id) VALUES (?, 0, 0, ?)", (aid, cid))
        return redirect("/automations/%d" % aid)
    body = '<form method="post" class="card stack narrow">%s%s%s<div class="form-actions"><button class="btn btn-primary">%s</button></div></form>' % (
        ui.csrf(req), field(T(req, "common.name"), inp("name", "", placeholder=T(req, "auto.default_name"))),
        field(T(req, "auto.trigger"), select("list_id", [(l["id"], T(req, "auto.when_joins", list=l["name"])) for l in lists]) if lists else '<p class="muted">%s</p>' % e(T(req, "lists.empty"))),
        e(T(req, "common.create")))
    return ui.page(req, T(req, "auto.new"), body, "automations")


def automation_edit(req, aid):
    a = db.one("SELECT * FROM automations WHERE id = ?", (_int(aid),))
    if not a:
        raise HTTPError(404)
    if req.method == "POST":
        action = req.get("action")
        if action == "save":
            list_id = _int(req.get("list_id")) or a["list_id"]
            db.run("UPDATE automations SET name = ?, list_id = ?, active = ? WHERE id = ?",
                   (req.get("name").strip()[:120] or a["name"], list_id, 1 if req.get("active") else 0, a["id"]))
            for s in db.q("SELECT id FROM automation_steps WHERE automation_id = ?", (a["id"],)):
                d = max(0, min(365, _int(req.get("delay_%d" % s["id"]), 0)))
                db.run("UPDATE automation_steps SET delay_days = ? WHERE id = ?", (d, s["id"]))
            if req.get("active") and not a["active"]:
                ui.flash(req, T(req, "auto.activated"))
            else:
                ui.flash(req, T(req, "common.saved"))
        elif action == "add":
            n = db.val("SELECT COUNT(*) FROM automation_steps WHERE automation_id = ?", (a["id"],), 0)
            cid = new_campaign(T(req, "auto.step_name", n=n + 1), "blank", ui.content_langs()[0], "automation")
            db.run("INSERT INTO automation_steps(automation_id, position, delay_days, campaign_id) VALUES (?, ?, 7, ?)", (a["id"], n, cid))
            return redirect("/campaigns/%d/edit" % cid)
        elif action.startswith("remove-"):
            s = db.one("SELECT * FROM automation_steps WHERE id = ? AND automation_id = ?", (_int(action[7:]), a["id"]))
            if s:
                db.run("DELETE FROM campaigns WHERE id = ?", (s["campaign_id"],))
                for i, r in enumerate(db.q("SELECT id FROM automation_steps WHERE automation_id = ? ORDER BY position, id", (a["id"],))):
                    db.run("UPDATE automation_steps SET position = ? WHERE id = ?", (i, r["id"]))
                ui.flash(req, T(req, "common.deleted"))
        elif action == "delete":
            for s in db.q("SELECT campaign_id FROM automation_steps WHERE automation_id = ?", (a["id"],)):
                db.run("DELETE FROM campaigns WHERE id = ?", (s["campaign_id"],))
            db.run("DELETE FROM automations WHERE id = ?", (a["id"],))
            ui.flash(req, T(req, "common.deleted"))
            return redirect("/automations")
        return redirect("/automations/%d" % a["id"])
    lists = db.q("SELECT * FROM lists ORDER BY name")
    steps = db.q("""SELECT s.*, c.name, (SELECT subject FROM variants v WHERE v.campaign_id = c.id AND v.lang = c.default_lang) AS subject,
                    (SELECT COUNT(*) FROM deliveries d WHERE d.campaign_id = c.id AND d.status = 'sent') AS sent
                    FROM automation_steps s JOIN campaigns c ON c.id = s.campaign_id WHERE s.automation_id = ? ORDER BY s.position, s.id""", (a["id"],))
    step_html = "".join(
        '<li class="step"><div class="step-delay">%s</div><div class="step-body"><strong>%s</strong><span class="muted">%s</span>'
        '<span class="muted small">%s</span></div><div class="step-actions"><a class="btn" href="/campaigns/%d/edit">%s</a>'
        '<a class="btn btn-ghost" href="/campaigns/%d/report">%s</a><button class="btn btn-ghost" name="action" value="remove-%d" formnovalidate '
        'data-confirm="%s">%s</button></div></li>' % (
            field(T(req, "auto.wait_days") if i else T(req, "auto.wait_days_first"), inp("delay_%d" % s["id"], s["delay_days"], "number", min="0", max="365")),
            e(s["name"]), e(s["subject"] or T(req, "auto.no_subject")), e(T(req, "auto.sent_n", n=s["sent"])), s["campaign_id"], e(T(req, "auto.edit_email")),
            s["campaign_id"], e(T(req, "auto.stats")), s["id"], e(T(req, "auto.confirm_remove")), e(T(req, "common.remove")))
        for i, s in enumerate(steps))
    body = ('<form method="post" class="stack">%s<button class="sr-only" name="action" value="save" tabindex="-1" aria-hidden="true"></button><div class="card stack"><div class="grid2">%s%s</div>%s<small class="hint">%s</small></div>'
            '<h2>%s</h2><ol class="steps">%s</ol><div class="form-actions"><button class="btn btn-primary" name="action" value="save">%s</button>'
            '<button class="btn" name="action" value="add">%s</button></div>'
            '<div class="danger-zone"><button class="btn btn-danger" name="action" value="delete" data-confirm="%s">%s</button></div></form>') % (
        ui.csrf(req), field(T(req, "common.name"), inp("name", a["name"], required=True)),
        field(T(req, "auto.trigger"), select("list_id", [(l["id"], T(req, "auto.when_joins", list=l["name"])) for l in lists], a["list_id"])),
        checkbox("active", a["active"], T(req, "auto.active")), e(T(req, "auto.active_help")),
        e(T(req, "auto.steps")), step_html, e(T(req, "common.save")), e(T(req, "auto.add_step")), e(T(req, "auto.confirm_delete")), e(T(req, "common.delete")))
    return ui.page(req, a["name"], body, "automations")


router.add("GET", "/campaigns", campaigns)
router.add("GET", "/campaigns/new", campaign_new)
router.add("POST", "/campaigns/new", campaign_new)
router.add("POST", "/upload", upload)
router.add("GET", "/campaigns/<cid>", campaign_show)
router.add("GET", "/campaigns/<cid>/edit", campaign_edit)
router.add("POST", "/campaigns/<cid>/content", campaign_content)
router.add("POST", "/campaigns/<cid>/preview", campaign_preview)
router.add("GET", "/campaigns/<cid>/settings", campaign_settings)
router.add("POST", "/campaigns/<cid>/settings", campaign_settings)
router.add("GET", "/campaigns/<cid>/send", campaign_send_page)
router.add("POST", "/campaigns/<cid>/send", campaign_send)
router.add("POST", "/campaigns/<cid>/test", campaign_test)
router.add("GET", "/campaigns/<cid>/report", report)
router.add("POST", "/campaigns/<cid>/<action>", campaign_action)
router.add("GET", "/automations", automations)
router.add("GET", "/automations/new", automation_new)
router.add("POST", "/automations/new", automation_new)
router.add("GET", "/automations/<aid>", automation_edit)
router.add("POST", "/automations/<aid>", automation_edit)
