"""First-run setup, login/logout, own account and the dashboard."""
from . import db, i18n, security, ui
from .app import end_session, needs_setup, router, start_session
from .ui import T, field, inp, select
from .web import HTTPError, Response, e, redirect


def _auth_card(req, title, intro, form, error=""):
    err = '<div class="flash flash-error" role="alert">%s</div>' % e(error) if error else ""
    langs = "".join('<a href="?ui=%s" class="%s">%s</a>' % (c, "active" if c == req.lang else "", c.upper()) for c in i18n.UI_LANGS)
    body = ('<div class="bare-brand">%s<div><strong>Koinonia</strong><small>%s</small></div></div><h1>%s</h1><p class="muted">%s</p>%s%s'
            '<nav class="bare-langs">%s</nav>') % (ui.LOGO, e(T(req, "app.tagline")), e(title), e(intro), err, form, langs)
    return ui.bare(req, title, body)


def _with_ui_lang(req, resp):
    lang = req.query.get("ui", [""])[0]
    if lang in i18n.UI_LANGS:
        resp.set_cookie("kn_lang", lang, max_age=365 * 86400)
    return resp


def _apply_ui_param(req):
    lang = req.query.get("ui", [""])[0]
    if lang in i18n.UI_LANGS:
        req.lang = lang


def setup(req):
    if not needs_setup():
        return redirect("/login")
    _apply_ui_param(req)
    error, f = "", {}
    if req.method == "POST":
        f = {k: req.get(k).strip() for k in ("org_name", "name", "email", "password", "lang")}
        if not f["org_name"] or not f["name"]:
            error = T(req, "setup.err_required")
        elif not security.valid_email(f["email"]):
            error = T(req, "err.email")
        elif len(f["password"]) < 10:
            error = T(req, "err.password_short")
        else:
            lang = i18n.ui_lang(f["lang"] or req.lang)
            cur = db.run("INSERT INTO users(email, name, pw_hash, role, lang) VALUES (?, ?, ?, 'admin', ?)",
                         (f["email"], f["name"], security.hash_password(f["password"]), lang))
            db.set_settings({"org_name": f["org_name"], "from_name": f["org_name"], "from_email": f["email"], "reply_to": f["email"],
                             "default_lang": lang if lang in i18n.LANG_NAMES else "nl",
                             "content_langs": ",".join(dict.fromkeys([lang, "en"]))})
            base = "%s://%s" % (req.environ.get("wsgi.url_scheme", "http"), req.environ.get("HTTP_HOST", "localhost:8080"))
            db.set_settings({"base_url": base})
            db.run("INSERT INTO lists(name, description, double_optin) VALUES (?, ?, 1)", (T(req, "setup.first_list"), ""))
            resp = redirect("/")
            return start_session(req, cur.lastrowid, resp)
    form = ('<form method="post" class="stack">%s%s%s%s%s<button class="btn btn-primary btn-block">%s</button></form>' % (
        field(T(req, "setup.org_name"), inp("org_name", f.get("org_name", ""), required=True, autofocus=True), T(req, "setup.org_hint")),
        field(T(req, "common.your_name"), inp("name", f.get("name", ""), required=True, autocomplete="name")),
        field(T(req, "common.email"), inp("email", f.get("email", ""), "email", required=True, autocomplete="email")),
        field(T(req, "common.password"), inp("password", "", "password", required=True, minlength="10", autocomplete="new-password"), T(req, "setup.password_hint")),
        '<input type="hidden" name="lang" value="%s">' % e(req.lang), e(T(req, "setup.start"))))
    return _with_ui_lang(req, _auth_card(req, T(req, "setup.title"), T(req, "setup.intro"), form, error))


def login(req):
    if needs_setup():
        return redirect("/setup")
    _apply_ui_param(req)
    error = ""
    nxt = req.get("next")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if req.method == "POST":
        if not security.login_limiter.allow(req.ip):
            error = T(req, "login.too_many")
        else:
            user = db.one("SELECT * FROM users WHERE email = ?", (req.get("email").strip(),))
            if user and security.check_password(req.get("password"), user["pw_hash"]):
                return start_session(req, user["id"], redirect(nxt))
            error = T(req, "login.failed")
    form = ('<form method="post" class="stack"><input type="hidden" name="next" value="%s">%s%s<button class="btn btn-primary btn-block">%s</button></form>' % (
        e(nxt), field(T(req, "common.email"), inp("email", req.get("email"), "email", required=True, autofocus=True, autocomplete="username")),
        field(T(req, "common.password"), inp("password", "", "password", required=True, autocomplete="current-password")), e(T(req, "login.submit"))))
    return _with_ui_lang(req, _auth_card(req, T(req, "login.title"), T(req, "login.intro"), form, error))


def logout(req):
    return end_session(req, redirect("/login"))


def set_lang(req):
    lang = req.get("lang")
    if lang in i18n.UI_LANGS:
        db.run("UPDATE users SET lang = ? WHERE id = ?", (lang, req.user["id"]))
    back = req.header("Referer") or "/"
    from urllib.parse import urlparse
    p = urlparse(back)
    return redirect((p.path or "/") + ("?" + p.query if p.query else ""))


def account(req):
    u = req.user
    if req.method == "POST":
        name = req.get("name").strip()
        db.run("UPDATE users SET name = ? WHERE id = ?", (name[:120], u["id"]))
        new = req.get("new_password")
        if new:
            if not security.check_password(req.get("current_password"), u["pw_hash"]):
                ui.flash(req, T(req, "account.wrong_password"), "error")
                return redirect("/account")
            if len(new) < 10:
                ui.flash(req, T(req, "err.password_short"), "error")
                return redirect("/account")
            db.run("UPDATE users SET pw_hash = ? WHERE id = ?", (security.hash_password(new), u["id"]))
            db.run("DELETE FROM sessions WHERE user_id = ? AND token != ?", (u["id"], req.session["token"]))
        ui.flash(req, T(req, "common.saved"))
        return redirect("/account")
    body = ('<form method="post" class="card stack narrow">%s%s%s<h2>%s</h2>%s%s<div class="form-actions"><button class="btn btn-primary">%s</button></div></form>' % (
        ui.csrf(req), field(T(req, "common.your_name"), inp("name", u["name"])),
        field(T(req, "common.email"), inp("email", u["email"], "email", disabled=True)), e(T(req, "account.change_password")),
        field(T(req, "account.current_password"), inp("current_password", "", "password", autocomplete="current-password")),
        field(T(req, "account.new_password"), inp("new_password", "", "password", minlength="10", autocomplete="new-password"), T(req, "setup.password_hint")),
        e(T(req, "common.save"))))
    return ui.page(req, T(req, "account.title"), body)


def dashboard(req):
    stats = {
        "contacts": db.val("SELECT COUNT(*) FROM contacts WHERE status = 'active'", (), 0),
        "new30": db.val("SELECT COUNT(*) FROM contacts WHERE status = 'active' AND created_at > datetime('now', '-30 days')", (), 0),
        "sent30": db.val("SELECT COUNT(*) FROM deliveries WHERE status = 'sent' AND sent_at > datetime('now', '-30 days')", (), 0),
        "unsub30": db.val("SELECT COUNT(*) FROM events WHERE type = 'unsubscribed' AND at > datetime('now', '-30 days')", (), 0),
    }
    queued = db.val("SELECT COUNT(*) FROM deliveries WHERE status = 'queued'", (), 0)
    tiles = "".join('<div class="stat"><span>%s</span><strong>%s</strong></div>' % (e(T(req, "dash." + k)), v) for k, v in stats.items())
    rows = db.q("""SELECT c.*, (SELECT COUNT(*) FROM deliveries d WHERE d.campaign_id = c.id AND d.status = 'sent') AS sent,
                   (SELECT COUNT(*) FROM deliveries d WHERE d.campaign_id = c.id AND d.opened_at IS NOT NULL) AS opened,
                   (SELECT COUNT(*) FROM deliveries d WHERE d.campaign_id = c.id AND d.clicked_at IS NOT NULL) AS clicked
                   FROM campaigns c WHERE c.kind = 'campaign' ORDER BY c.updated_at DESC LIMIT 6""")
    if rows:
        recent = '<table class="table"><thead><tr><th>%s</th><th>%s</th><th class="num">%s</th><th class="num">%s</th><th class="num">%s</th></tr></thead><tbody>%s</tbody></table>' % (
            e(T(req, "common.name")), e(T(req, "common.status")), e(T(req, "report.sent")), e(T(req, "report.opened")), e(T(req, "report.clicked")),
            "".join('<tr><td><a href="/campaigns/%d">%s</a></td><td>%s</td><td class="num">%d</td><td class="num">%s</td><td class="num">%s</td></tr>' % (
                r["id"], e(r["name"]), ui.badge(req, r["status"]), r["sent"],
                ui.pct(r["opened"], r["sent"]) if r["track_opens"] else "–", ui.pct(r["clicked"], r["sent"]) if r["track_clicks"] else "–") for r in rows))
    else:
        recent = ui.empty(req, T(req, "dash.no_campaigns"), '<a class="btn btn-primary" href="/campaigns/new">%s</a>' % e(T(req, "campaigns.new")))
    setup_tips = []
    cfg = db.settings()
    if cfg.get("transport") != "smtp":
        setup_tips.append(T(req, "dash.tip_smtp"))
    if not cfg.get("org_address"):
        setup_tips.append(T(req, "dash.tip_address"))
    if not db.val("SELECT 1 FROM forms LIMIT 1"):
        setup_tips.append(T(req, "dash.tip_form"))
    tips = ""
    if setup_tips and req.user["role"] == "admin":
        tips = '<section class="card tips"><h2>%s</h2><ul>%s</ul><a href="/settings" class="btn btn-ghost">%s</a></section>' % (
            e(T(req, "dash.getting_started")), "".join("<li>%s</li>" % e(t) for t in setup_tips), e(T(req, "nav.settings")))
    q = '<p class="queue">%s</p>' % e(T(req, "dash.queued", n=queued)) if queued else ""
    verse = '<blockquote class="verse"><p>%s</p><cite>%s</cite></blockquote>' % (e(T(req, "dash.verse")), e(T(req, "dash.verse_ref")))
    body = '%s<div class="stats">%s</div>%s%s<section class="card"><div class="card-head"><h2>%s</h2><a href="/campaigns">%s &rarr;</a></div>%s</section>' % (
        verse, tiles, q, tips, e(T(req, "dash.recent")), e(T(req, "common.view_all")), recent)
    actions = '<a class="btn btn-primary" href="/campaigns/new">%s</a>' % e(T(req, "campaigns.new"))
    hello = T(req, "dash.hello", name=(req.user["name"] or "").split(" ")[0])
    return ui.page(req, hello, body, "dashboard", actions)


router.add("GET", "/setup", setup, "public")
router.add("POST", "/setup", setup, "public")
router.add("GET", "/login", login, "public")
router.add("POST", "/login", login, "public")
router.add("POST", "/logout", logout)
router.add("POST", "/account/lang", set_lang)
router.add("GET", "/account", account)
router.add("POST", "/account", account)
router.add("GET", "/", dashboard)
