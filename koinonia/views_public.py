"""Pages anyone can reach: sign-up forms, confirmation, unsubscribe, preferences,
tracking endpoints, web version, calendar files and the public archive."""
import logging
import time

from . import audience, compose, db, i18n, mailer, render, security, ui
from .app import router
from .web import HTTPError, Response, e, redirect

log = logging.getLogger("koinonia.public")
PIXEL = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
         b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
CSP_PUBLIC = "default-src 'self'; img-src * data:; style-src 'self' 'unsafe-inline'; script-src 'none'; form-action 'self'; base-uri 'none'"
CSP_EMAIL = "default-src 'none'; img-src * data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


def P(lang, key, **kw):
    return i18n.t(lang, "pub." + key, **kw)


def public_page(req, lang, title, inner, status=200, frameable=False):
    cfg = db.settings()
    logo = render.safe_url(cfg.get("logo_url"), cfg.get("base_url", ""))
    head = '<img src="%s" alt="%s" class="pub-logo">' % (e(logo), e(cfg.get("org_name"))) if logo else '<p class="pub-org">%s</p>' % e(cfg.get("org_name"))
    resp = ui.bare(req, title, '<div class="pub">%s%s</div>' % (head, inner), status, lang)
    resp.headers.append(("Content-Security-Policy", CSP_PUBLIC + ("" if frameable else "; frame-ancestors 'none'")))
    return resp


def message(req, lang, title, text, status=200):
    return public_page(req, lang, title, '<h1>%s</h1><p>%s</p>' % (e(title), e(text)), status)


# ---------------------------------------------------------------- sign-up forms
def _form(pid):
    f = db.one("SELECT * FROM forms WHERE public_id = ?", (pid,))
    if not f:
        raise HTTPError(404)
    return f


def form_page(req, pid, error="", values=None):
    f = _form(pid)
    lang = f["lang"]
    v = values or {}
    lists = db.q("SELECT id, name, description FROM lists WHERE id IN (%s) ORDER BY name" % ",".join("?" * len(db.jl(f["list_ids"]))), db.jl(f["list_ids"])) if db.jl(f["list_ids"]) else []
    chosen = set(v.get("lists") or [str(l["id"]) for l in lists])
    parts = ['<form method="post" class="stack" accept-charset="utf-8"><input type="hidden" name="ts" value="%d">' % int(time.time())]
    if error:
        parts.append('<div class="flash flash-error" role="alert">%s</div>' % e(error))
    if f["ask_name"]:
        parts.append('<div class="grid2">%s%s</div>' % (
            ui.field(P(lang, "first_name"), ui.inp("first_name", v.get("first_name", ""), autocomplete="given-name")),
            ui.field(P(lang, "last_name"), ui.inp("last_name", v.get("last_name", ""), autocomplete="family-name"))))
    parts.append(ui.field(P(lang, "email"), ui.inp("email", v.get("email", ""), "email", required=True, autocomplete="email")))
    if f["ask_lang"]:
        parts.append(ui.field(P(lang, "language"), ui.select("lang", ui.lang_options(ui.content_langs()), v.get("lang") or lang)))
    if len(lists) > 1:
        parts.append('<fieldset class="stack"><legend>%s</legend>%s</fieldset>' % (e(P(lang, "interests")), "".join(
            '<label class="check"><input type="checkbox" name="lists" value="%d"%s> <span><strong>%s</strong>%s</span></label>' % (
                l["id"], " checked" if str(l["id"]) in chosen else "", e(l["name"]), "<br><small class=\"muted\">%s</small>" % e(l["description"]) if l["description"] else "")
            for l in lists)))
    if f["consent_text"]:
        parts.append('<label class="check"><input type="checkbox" name="consent" value="1" required%s> <span>%s</span></label>' % (
            " checked" if v.get("consent") else "", e(f["consent_text"])))
    parts.append('<div class="hp" aria-hidden="true"><label>Website <input name="website" tabindex="-1" autocomplete="off"></label></div>')
    parts.append('<button class="btn btn-primary btn-block">%s</button></form>' % e(P(lang, "subscribe")))
    intro = '<p>%s</p>' % e(f["intro"]).replace("\n", "<br>") if f["intro"] else ""
    return public_page(req, lang, f["title"] or P(lang, "form_title"), '<h1>%s</h1>%s%s' % (e(f["title"] or P(lang, "form_title")), intro, "".join(parts)),
                       400 if error else 200, frameable=True)


def form_submit(req, pid):
    f = _form(pid)
    lang = f["lang"]
    values = {k: req.get(k).strip() for k in ("email", "first_name", "last_name", "lang", "consent")}
    values["lists"] = req.getlist("lists")
    thanks = lambda pending: message(req, lang, P(lang, "thanks_title"), f["success_text"] or P(lang, "check_inbox" if pending else "thanks"))
    if req.get("website"):
        return thanks(True)  # honeypot filled in: a bot. Pretend all is well.
    try:
        if req.get("ts") and time.time() - int(req.get("ts")) < 2:
            return thanks(True)  # filled in faster than a human can
    except ValueError:
        pass
    if not security.form_limiter.allow(req.ip):
        raise HTTPError(429)
    if not security.valid_email(values["email"]):
        return form_page(req, pid, P(lang, "invalid_email"), values)
    if f["consent_text"] and not values["consent"]:
        return form_page(req, pid, P(lang, "consent_required"), values)
    allowed = db.jl(f["list_ids"])
    list_ids = [int(x) for x in values["lists"] if x.isdigit()]
    if len(allowed) > 1 and not [i for i in list_ids if i in allowed]:
        return form_page(req, pid, P(lang, "choose_one"), values)
    contact_lang = values["lang"] if values["lang"] in i18n.LANG_NAMES else lang
    status, token, cid = audience.subscribe_form(f, values["email"], values["first_name"] or None, values["last_name"] or None,
                                                 contact_lang, list_ids, req.ip)
    db.commit()
    if status == "pending":
        contact = db.one("SELECT * FROM contacts WHERE id = ?", (cid,))
        try:
            with mailer.Sender() as s:
                s.send(compose.confirmation_email(f, contact, token))
        except Exception:
            log.exception("could not send confirmation email to contact %s", cid)
    return thanks(status == "pending")


def confirm(req, token):
    cid = audience.confirm(token)
    if not cid:
        return message(req, "en" if req.lang not in i18n.LANG_NAMES else req.lang, P(req.lang, "invalid_title"), P(req.lang, "invalid_link"), 404)
    lang = i18n.content_lang(db.val("SELECT lang FROM contacts WHERE id = ?", (cid,)), db.setting("default_lang"))
    return message(req, lang, P(lang, "confirmed_title"), P(lang, "confirmed"))


# ---------------------------------------------------------------- unsubscribe & preferences
def _delivery(token):
    if not token or token == "preview":
        return None, None
    d = db.one("SELECT * FROM deliveries WHERE token = ?", (token,))
    c = db.one("SELECT * FROM contacts WHERE id = ?", (d["contact_id"],)) if d and d["contact_id"] else None
    return d, c


def unsubscribe(req, token):
    d, c = _delivery(token)
    lang = i18n.content_lang((c["lang"] if c else "") or (d["lang"] if d else "") or req.lang, db.setting("default_lang") or "en")
    org = db.setting("org_name")
    if token == "preview":
        return message(req, lang, P(lang, "unsubscribe"), P(lang, "preview_note"))
    if not c:
        return message(req, lang, P(lang, "invalid_title"), P(lang, "invalid_link"), 404)
    if req.method == "POST":
        if c["status"] == "active":
            audience.unsubscribe_all(c["id"], d["id"])
        if req.get("List-Unsubscribe") == "One-Click":
            return Response("OK", 200, "text/plain; charset=utf-8")
        c = db.one("SELECT * FROM contacts WHERE id = ?", (c["id"],))
    if c["status"] != "active":
        inner = '<h1>%s</h1><p>%s</p><p><a href="/p/%s">%s</a></p>' % (
            e(P(lang, "unsub_done_title")), e(P(lang, "unsub_done")), e(c["token"]), e(P(lang, "resubscribe")))
        return public_page(req, lang, P(lang, "unsub_done_title"), inner)
    inner = '<h1>%s</h1><p>%s</p><p class="muted">%s</p><form method="post"><button class="btn btn-primary btn-block">%s</button></form><p><a href="/p/%s">%s</a></p>' % (
        e(P(lang, "unsubscribe")), e(P(lang, "unsub_q", org=org)), e(c["email"]), e(P(lang, "unsub_btn")), e(c["token"]), e(P(lang, "unsub_prefs_instead")))
    return public_page(req, lang, P(lang, "unsubscribe"), inner)


def preferences(req, token):
    lang0 = db.setting("default_lang") or "en"
    if token == "preview":
        return message(req, lang0, P(lang0, "pref_title"), P(lang0, "preview_note"))
    c = db.one("SELECT * FROM contacts WHERE token = ?", (token,))
    if not c:
        return message(req, lang0, P(lang0, "invalid_title"), P(lang0, "invalid_link"), 404)
    lang = i18n.content_lang(c["lang"], lang0)
    lists = db.q("""SELECT l.id, l.name, l.description, m.status FROM lists l JOIN list_members m ON m.list_id = l.id
                    WHERE m.contact_id = ? ORDER BY l.name""", (c["id"],))
    saved = ""
    if req.method == "POST":
        wanted = {int(x) for x in req.getlist("lists") if x.isdigit()}
        new_lang = req.get("lang") if req.get("lang") in i18n.LANG_NAMES else c["lang"]
        db.run("UPDATE contacts SET first_name = ?, last_name = ?, lang = ?, updated_at = datetime('now') WHERE id = ?",
               (req.get("first_name").strip()[:120], req.get("last_name").strip()[:120], new_lang, c["id"]))
        if req.get("all_off") or not wanted:
            if c["status"] == "active":
                audience.unsubscribe_all(c["id"])
        else:
            if c["status"] != "active":
                db.run("UPDATE contacts SET status = 'active', updated_at = datetime('now') WHERE id = ?", (c["id"],))
                audience.record_consent(c["id"], P(new_lang, "pref_title"), req.ip)
                audience.log(c["id"], "resubscribed")
            for l in lists:
                if l["id"] in wanted and l["status"] != "subscribed":
                    audience.set_membership(c["id"], l["id"], "subscribed")
                elif l["id"] not in wanted and l["status"] != "unsubscribed":
                    db.run("UPDATE list_members SET status = 'unsubscribed', updated_at = datetime('now') WHERE list_id = ? AND contact_id = ?", (l["id"], c["id"]))
        audience.log(c["id"], "preferences")
        db.commit()
        c = db.one("SELECT * FROM contacts WHERE id = ?", (c["id"],))
        lang = i18n.content_lang(c["lang"], lang0)
        lists = db.q("""SELECT l.id, l.name, l.description, m.status FROM lists l JOIN list_members m ON m.list_id = l.id
                        WHERE m.contact_id = ? ORDER BY l.name""", (c["id"],))
        saved = '<div class="flash flash-ok" role="status">%s</div>' % e(P(lang, "saved"))
    active = c["status"] == "active"
    boxes = "".join('<label class="check"><input type="checkbox" name="lists" value="%d"%s> <span><strong>%s</strong>%s</span></label>' % (
        l["id"], " checked" if active and l["status"] == "subscribed" else "", e(l["name"]),
        "<br><small class=\"muted\">%s</small>" % e(l["description"]) if l["description"] else "") for l in lists)
    inner = ('<h1>%s</h1>%s<p>%s</p><form method="post" class="stack"><p class="muted">%s</p><div class="grid2">%s%s</div>%s'
             '<fieldset class="stack"><legend>%s</legend>%s</fieldset><label class="check"><input type="checkbox" name="all_off" value="1"> <span>%s</span></label>'
             '<button class="btn btn-primary btn-block">%s</button></form>') % (
        e(P(lang, "pref_title")), saved, e(P(lang, "pref_intro")), e(c["email"]),
        ui.field(P(lang, "first_name"), ui.inp("first_name", c["first_name"], autocomplete="given-name")),
        ui.field(P(lang, "last_name"), ui.inp("last_name", c["last_name"], autocomplete="family-name")),
        ui.field(P(lang, "language"), ui.select("lang", ui.lang_options(ui.content_langs() + ([c["lang"]] if c["lang"] and c["lang"] not in ui.content_langs() else [])), c["lang"] or lang)),
        e(P(lang, "interests")), boxes, e(P(lang, "all_off")), e(P(lang, "save")))
    return public_page(req, lang, P(lang, "pref_title"), inner)


# ---------------------------------------------------------------- tracking
def open_pixel(req, token):
    d = db.one("SELECT d.id, d.contact_id, d.opened_at FROM deliveries d JOIN campaigns c ON c.id = d.campaign_id WHERE d.token = ? AND c.track_opens = 1", (token,))
    if d:
        db.run("UPDATE deliveries SET open_count = open_count + 1, opened_at = COALESCE(opened_at, datetime('now')) WHERE id = ?", (d["id"],))
        if not d["opened_at"] and d["contact_id"]:
            audience.log(d["contact_id"], "opened")
    return Response(PIXEL, 200, "image/gif", [("Cache-Control", "no-store, max-age=0")])


def click(req, token, lid):
    d = db.one("SELECT * FROM deliveries WHERE token = ?", (token,))
    if not d or not lid.isdigit():
        raise HTTPError(404)
    link = db.one("SELECT * FROM links WHERE id = ? AND campaign_id = ?", (int(lid), d["campaign_id"]))
    if not link:
        raise HTTPError(404)
    db.run("INSERT INTO clicks(delivery_id, link_id) VALUES (?, ?)", (d["id"], link["id"]))
    db.run("""UPDATE deliveries SET click_count = click_count + 1, clicked_at = COALESCE(clicked_at, datetime('now')),
              opened_at = COALESCE(opened_at, datetime('now')) WHERE id = ?""", (d["id"],))
    if not d["clicked_at"] and d["contact_id"]:
        audience.log(d["contact_id"], "clicked", link["url"][:200])
    return redirect(link["url"], 302)


# ---------------------------------------------------------------- web version, calendar, archive
def _email_page(html):
    return Response(html, 200, "text/html; charset=utf-8", [("Content-Security-Policy", CSP_EMAIL)])


def view_online(req, token):
    d, c = _delivery(token)
    if not d:
        raise HTTPError(404)
    camp = db.one("SELECT * FROM campaigns WHERE id = ?", (d["campaign_id"],))
    return _email_page(compose.build(camp, d["lang"], c, d, tracking=False)["html"])


def calendar(req, pid, lang, idx):
    camp = db.one("SELECT * FROM campaigns WHERE public_id = ?", (pid,))
    if not camp or not idx.endswith(".ics") or not idx[:-4].isdigit():
        raise HTTPError(404)
    v = compose.variant(camp, lang)
    blocks = compose.blocks_of(v)
    i = int(idx[:-4])
    if i >= len(blocks) or blocks[i].get("type") != "event" or not blocks[i].get("date"):
        raise HTTPError(404)
    try:
        data = render.ics(blocks[i], "%s-%d@koinonia" % (pid, i), db.setting("timezone") or "UTC", db.setting("org_name") or "Koinonia")
    except ValueError:
        raise HTTPError(404)
    return Response(data, 200, "text/calendar; charset=utf-8", [("Content-Disposition", 'attachment; filename="event.ics"')])


def archive(req):
    if db.setting("archive_enabled") != "1":
        raise HTTPError(404)
    lang = db.setting("default_lang") or "en"
    rows = db.q("SELECT * FROM campaigns WHERE kind = 'campaign' AND archive = 1 AND status = 'sent' ORDER BY sent_at DESC LIMIT 200")
    items = "".join('<li><a href="/archive/%s">%s</a> <small class="muted">%s</small></li>' % (
        e(r["public_id"]), e((compose.variant(r, lang) or {"subject": r["name"]})["subject"] or r["name"]), e(render.format_date((r["sent_at"] or "")[:10], lang)))
        for r in rows)
    inner = '<h1>%s</h1>%s' % (e(P(lang, "archive")), '<ul class="archive">%s</ul>' % items if items else '<p class="muted">—</p>')
    return public_page(req, lang, P(lang, "archive"), inner)


def archive_item(req, pid):
    if db.setting("archive_enabled") != "1":
        raise HTTPError(404)
    camp = db.one("SELECT * FROM campaigns WHERE public_id = ? AND archive = 1 AND status = 'sent' AND kind = 'campaign'", (pid,))
    if not camp:
        raise HTTPError(404)
    lang = req.query.get("lang", [""])[0] or camp["default_lang"]
    return _email_page(compose.build(camp, lang, None, None, tracking=False, public=True)["html"])


def health(req):
    db.val("SELECT 1")
    return Response("ok", 200, "text/plain; charset=utf-8")


router.add("GET", "/f/<pid>", form_page, "public")
router.add("POST", "/f/<pid>", form_submit, "public")
router.add("GET", "/confirm/<token>", confirm, "public")
router.add("GET", "/u/<token>", unsubscribe, "public")
router.add("POST", "/u/<token>", unsubscribe, "public")
router.add("GET", "/p/<token>", preferences, "public")
router.add("POST", "/p/<token>", preferences, "public")
router.add("GET", r"/o/<token>\.gif", open_pixel, "public")
router.add("GET", "/c/<token>/<lid>", click, "public")
router.add("GET", "/v/<token>", view_online, "public")
router.add("GET", "/ics/<pid>/<lang>/<idx>", calendar, "public")
router.add("GET", "/archive", archive, "public")
router.add("GET", "/archive/<pid>", archive_item, "public")
router.add("GET", "/health", health, "public")
