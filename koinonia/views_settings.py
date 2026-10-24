"""Organisation settings, sending, languages, privacy and team members."""
from . import db, i18n, mailer, render, security, ui
from .app import router
from .ui import T, checkbox, checks, field, inp, select, textarea
from .web import HTTPError, e, redirect

TZ_SUGGESTIONS = ["Europe/Amsterdam", "Europe/Brussels", "Europe/Berlin", "Europe/Paris", "Europe/London", "Europe/Madrid", "Europe/Lisbon",
                  "Europe/Rome", "Europe/Warsaw", "Europe/Bucharest", "Europe/Kyiv", "Africa/Johannesburg", "Africa/Nairobi", "Africa/Lagos",
                  "Asia/Jakarta", "America/New_York", "America/Chicago", "America/Los_Angeles", "America/Sao_Paulo", "America/Paramaribo",
                  "America/Curacao", "Australia/Sydney", "UTC"]


def _tabs(req, active):
    items = [("general", "/settings"), ("sending", "/settings/sending"), ("team", "/settings/team"), ("deliverability", "/settings/deliverability")]
    return '<nav class="tabs">%s</nav>' % "".join('<a href="%s" class="%s">%s</a>' % (h, "active" if k == active else "", e(T(req, "settings.tab_" + k))) for k, h in items)


def _valid_tz(name):
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name)
        return True
    except Exception:
        return name == "UTC"


def general(req):
    cfg = db.settings()
    if req.method == "POST":
        langs = [l for l in req.getlist("content_langs") if l in i18n.LANG_NAMES]
        default = req.get("default_lang") if req.get("default_lang") in i18n.LANG_NAMES else "nl"
        if default not in langs:
            langs.insert(0, default)
        tz = req.get("timezone").strip() or "UTC"
        base = req.get("base_url").strip().rstrip("/")
        errors = []
        if not _valid_tz(tz):
            errors.append(T(req, "settings.bad_timezone"))
        if not (base.startswith("http://") or base.startswith("https://")):
            errors.append(T(req, "settings.bad_base_url"))
        for k in ("logo_url", "donate_url", "org_website"):
            if req.get(k).strip() and not render.safe_url(req.get(k).strip(), base):
                errors.append(T(req, "settings.bad_url", field=T(req, "settings." + k)))
        if errors:
            ui.flash(req, " ".join(errors), "error")
            return redirect("/settings")
        accent = req.get("accent_color") if render.HEX.match(req.get("accent_color")) else cfg.get("accent_color")
        try:
            retention = str(max(0, min(3650, int(req.get("retention_days") or 0))))
        except ValueError:
            retention = cfg.get("retention_days")
        db.set_settings({
            "org_name": req.get("org_name").strip()[:200], "org_address": req.get("org_address").strip()[:500],
            "org_website": req.get("org_website").strip(), "logo_url": req.get("logo_url").strip(), "donate_url": req.get("donate_url").strip(),
            "accent_color": accent, "base_url": base, "default_lang": default, "content_langs": ",".join(langs), "timezone": tz,
            "track_opens": "1" if req.get("track_opens") else "0", "track_clicks": "1" if req.get("track_clicks") else "0",
            "retention_days": retention, "archive_enabled": "1" if req.get("archive_enabled") else "0",
        })
        ui.flash(req, T(req, "common.saved"))
        return redirect("/settings")
    org = '<fieldset class="card stack"><legend>%s</legend>%s%s<div class="grid2">%s%s</div>%s</fieldset>' % (
        e(T(req, "settings.organisation")),
        field(T(req, "settings.org_name"), inp("org_name", cfg.get("org_name"), required=True)),
        field(T(req, "settings.org_address"), textarea("org_address", cfg.get("org_address"), 3), T(req, "settings.org_address_help")),
        field(T(req, "settings.org_website"), inp("org_website", cfg.get("org_website"), "url", placeholder="https://")),
        field(T(req, "settings.donate_url"), inp("donate_url", cfg.get("donate_url"), "url", placeholder="https://"), T(req, "settings.donate_url_help")),
        field(T(req, "settings.logo_url"), '<div class="with-upload">%s<label class="btn btn-ghost">%s<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-upload-into="logo_url" hidden></label></div>' % (
            inp("logo_url", cfg.get("logo_url"), id="logo_url", placeholder="https://"), e(T(req, "editor.upload"))), T(req, "settings.logo_help")))
    look = '<fieldset class="card stack"><legend>%s</legend>%s</fieldset>' % (
        e(T(req, "settings.brand")), field(T(req, "settings.accent_color"), inp("accent_color", cfg.get("accent_color") or "#3d5a40", "color")))
    tz_list = '<datalist id="tzs">%s</datalist>' % "".join('<option value="%s">' % e(t) for t in TZ_SUGGESTIONS)
    langs = '<fieldset class="card stack"><legend>%s</legend><div class="grid2">%s%s</div>%s</fieldset>' % (
        e(T(req, "settings.languages")),
        field(T(req, "settings.default_lang"), select("default_lang", ui.lang_options(), cfg.get("default_lang"))),
        field(T(req, "settings.timezone"), inp("timezone", cfg.get("timezone"), list="tzs") + tz_list),
        field(T(req, "settings.content_langs"), checks("content_langs", ui.lang_options(), ui.content_langs()), T(req, "settings.content_langs_help")))
    privacy = '<fieldset class="card stack"><legend>%s</legend>%s%s%s%s<small class="hint">%s</small></fieldset>' % (
        e(T(req, "settings.privacy")),
        checkbox("track_opens", cfg.get("track_opens") == "1", T(req, "campaigns.track_opens")),
        checkbox("track_clicks", cfg.get("track_clicks") == "1", T(req, "campaigns.track_clicks")),
        checkbox("archive_enabled", cfg.get("archive_enabled") == "1", T(req, "settings.archive_enabled")),
        field(T(req, "settings.retention_days"), inp("retention_days", cfg.get("retention_days"), "number", min="0", max="3650"), T(req, "settings.retention_help")),
        e(T(req, "settings.privacy_help")))
    tech = '<fieldset class="card stack"><legend>%s</legend>%s</fieldset>' % (
        e(T(req, "settings.technical")), field(T(req, "settings.base_url"), inp("base_url", cfg.get("base_url"), "url", required=True), T(req, "settings.base_url_help")))
    body = _tabs(req, "general") + '<form method="post" class="stack">%s%s%s%s%s%s<div class="form-actions"><button class="btn btn-primary">%s</button></div></form>' % (
        ui.csrf(req), org, look, langs, privacy, tech, e(T(req, "common.save")))
    return ui.page(req, T(req, "nav.settings"), body, "settings")


def sending(req):
    cfg = db.settings()
    if req.method == "POST":
        from_email, reply_to = req.get("from_email").strip(), req.get("reply_to").strip()
        if not security.valid_email(from_email) or (reply_to and not security.valid_email(reply_to)):
            ui.flash(req, T(req, "err.email"), "error")
            return redirect("/settings/sending")
        try:
            rate = str(max(1, min(10000, int(req.get("rate_per_minute") or 60))))
            port = str(max(1, min(65535, int(req.get("smtp_port") or 587))))
        except ValueError:
            ui.flash(req, T(req, "settings.bad_number"), "error")
            return redirect("/settings/sending")
        new = {
            "from_name": req.get("from_name").strip()[:120], "from_email": from_email, "reply_to": reply_to,
            "transport": "smtp" if req.get("transport") == "smtp" else "file", "smtp_host": req.get("smtp_host").strip(),
            "smtp_port": port, "smtp_security": req.get("smtp_security") if req.get("smtp_security") in ("starttls", "ssl", "none") else "starttls",
            "smtp_user": req.get("smtp_user").strip(), "rate_per_minute": rate,
        }
        if req.get("smtp_password"):
            new["smtp_password"] = req.get("smtp_password")
        db.set_settings(new)
        if req.get("action") == "test":
            err = mailer.test_connection(db.settings())
            ui.flash(req, T(req, "settings.smtp_ok") if not err else T(req, "settings.smtp_failed", error=err), "error" if err else "ok")
        else:
            ui.flash(req, T(req, "common.saved"))
        return redirect("/settings/sending")
    sender = '<fieldset class="card stack"><legend>%s</legend><div class="grid2">%s%s</div>%s</fieldset>' % (
        e(T(req, "campaigns.sender")),
        field(T(req, "settings.from_name"), inp("from_name", cfg.get("from_name"))),
        field(T(req, "settings.from_email"), inp("from_email", cfg.get("from_email"), "email", required=True), T(req, "settings.from_email_help")),
        field(T(req, "settings.reply_to"), inp("reply_to", cfg.get("reply_to"), "email")))
    smtp = ('<fieldset class="card stack"><legend>%s</legend>%s<div class="grid3">%s%s%s</div><div class="grid2">%s%s</div>%s'
            '<details class="help"><summary>%s</summary><p>%s</p></details></fieldset>') % (
        e(T(req, "settings.smtp")),
        field(T(req, "settings.transport"), select("transport", [("smtp", T(req, "settings.transport_smtp")), ("file", T(req, "settings.transport_file"))], cfg.get("transport"))),
        field(T(req, "settings.smtp_host"), inp("smtp_host", cfg.get("smtp_host"), placeholder="smtp.example.org")),
        field(T(req, "settings.smtp_port"), inp("smtp_port", cfg.get("smtp_port"), "number", min="1", max="65535")),
        field(T(req, "settings.smtp_security"), select("smtp_security", [("starttls", "STARTTLS (587)"), ("ssl", "SSL/TLS (465)"), ("none", T(req, "settings.none"))], cfg.get("smtp_security"))),
        field(T(req, "settings.smtp_user"), inp("smtp_user", cfg.get("smtp_user"), autocomplete="off")),
        field(T(req, "settings.smtp_password"), inp("smtp_password", "", "password", autocomplete="new-password",
                                                     placeholder=T(req, "settings.password_kept") if cfg.get("smtp_password") else "")),
        field(T(req, "settings.rate"), inp("rate_per_minute", cfg.get("rate_per_minute"), "number", min="1", max="10000"), T(req, "settings.rate_help")),
        e(T(req, "settings.smtp_which")), e(T(req, "settings.smtp_which_help")))
    body = _tabs(req, "sending") + '<form method="post" class="stack">%s%s%s<div class="form-actions"><button class="btn btn-primary" name="action" value="save">%s</button><button class="btn" name="action" value="test">%s</button></div></form>' % (
        ui.csrf(req), sender, smtp, e(T(req, "common.save")), e(T(req, "settings.smtp_test")))
    return ui.page(req, T(req, "nav.settings"), body, "settings")


def team(req):
    if req.method == "POST":
        action = req.get("action")
        if action == "add":
            email, name, pw = req.get("email").strip(), req.get("name").strip(), req.get("password")
            role = "admin" if req.get("role") == "admin" else "editor"
            if not security.valid_email(email):
                ui.flash(req, T(req, "err.email"), "error")
            elif len(pw) < 10:
                ui.flash(req, T(req, "err.password_short"), "error")
            elif db.val("SELECT 1 FROM users WHERE email = ?", (email,)):
                ui.flash(req, T(req, "team.exists"), "error")
            else:
                db.run("INSERT INTO users(email, name, pw_hash, role, lang) VALUES (?, ?, ?, ?, ?)",
                       (email, name[:120], security.hash_password(pw), role, req.lang))
                ui.flash(req, T(req, "team.added", email=email))
        elif action and action.startswith(("remove-", "role-")):
            kind, _, uid = action.partition("-")
            uid = int(uid) if uid.isdigit() else 0
            if uid == req.user["id"]:
                ui.flash(req, T(req, "team.not_self"), "error")
            elif kind == "remove":
                db.run("DELETE FROM users WHERE id = ?", (uid,))
                ui.flash(req, T(req, "common.deleted"))
            else:
                db.run("UPDATE users SET role = CASE role WHEN 'admin' THEN 'editor' ELSE 'admin' END WHERE id = ?", (uid,))
                ui.flash(req, T(req, "common.saved"))
        return redirect("/settings/team")
    users = db.q("SELECT * FROM users ORDER BY name, email")
    rows = "".join('<tr><td><strong>%s</strong><br><small class="muted">%s</small></td><td>%s</td><td class="right">%s</td></tr>' % (
        e(u["name"]), e(u["email"]), e(T(req, "team.role_" + u["role"])),
        "" if u["id"] == req.user["id"] else '<button class="btn btn-ghost" name="action" value="role-%d">%s</button><button class="btn btn-ghost" name="action" value="remove-%d" data-confirm="%s">%s</button>' % (
            u["id"], e(T(req, "team.toggle_role")), u["id"], e(T(req, "team.confirm_remove")), e(T(req, "common.remove")))) for u in users)
    listing = '<form method="post" class="card flush">%s<table class="table"><thead><tr><th>%s</th><th>%s</th><th></th></tr></thead><tbody>%s</tbody></table></form>' % (
        ui.csrf(req), e(T(req, "common.name")), e(T(req, "team.role")), rows)
    add = '<form method="post" class="card stack">%s<h2>%s</h2><div class="grid2">%s%s</div><div class="grid2">%s%s</div><small class="hint">%s</small><div class="form-actions"><button class="btn btn-primary" name="action" value="add">%s</button></div></form>' % (
        ui.csrf(req), e(T(req, "team.add")), field(T(req, "common.name"), inp("name", "")), field(T(req, "common.email"), inp("email", "", "email", required=True)),
        field(T(req, "team.role"), select("role", [("editor", T(req, "team.role_editor")), ("admin", T(req, "team.role_admin"))], "editor")),
        field(T(req, "team.initial_password"), inp("password", "", "text", required=True, minlength="10", autocomplete="off")),
        e(T(req, "team.roles_help")), e(T(req, "team.add_button")))
    return ui.page(req, T(req, "nav.settings"), _tabs(req, "team") + listing + add, "settings")


def deliverability(req):
    cfg = db.settings()
    domain = (cfg.get("from_email") or "jouwkerk.nl").rpartition("@")[2]
    items = [("spf", "v=spf1 include:<%s> ~all" % T(req, "deliv.your_provider")),
             ("dkim", T(req, "deliv.dkim_value")),
             ("dmarc", "v=DMARC1; p=none; rua=mailto:dmarc@%s" % domain)]
    cards = "".join('<section class="card"><h2>%s</h2><p>%s</p><pre class="code">%s</pre></section>' % (
        e(T(req, "deliv.%s_title" % k)), e(T(req, "deliv.%s_text" % k, domain=domain)), e(v)) for k, v in items)
    built_in = '<section class="card"><h2>%s</h2><ul class="ticks">%s</ul></section>' % (
        e(T(req, "deliv.builtin_title")), "".join("<li>%s</li>" % e(T(req, "deliv.builtin_%d" % i)) for i in range(1, 6)))
    body = _tabs(req, "deliverability") + '<p class="muted narrow">%s</p><div class="stack">%s%s</div>' % (e(T(req, "deliv.intro", domain=domain)), built_in, cards)
    return ui.page(req, T(req, "nav.settings"), body, "settings")


router.add("GET", "/settings", general, "admin")
router.add("POST", "/settings", general, "admin")
router.add("GET", "/settings/sending", sending, "admin")
router.add("POST", "/settings/sending", sending, "admin")
router.add("GET", "/settings/team", team, "admin")
router.add("POST", "/settings/team", team, "admin")
router.add("GET", "/settings/deliverability", deliverability, "admin")
