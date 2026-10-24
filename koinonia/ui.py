"""HTML building blocks for the admin interface."""
import os
from datetime import datetime, timezone

from . import db, i18n
from .web import Response, e

ICONS = {
    "home": '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 14.2c2.9.3 5 2.3 5 5.8"/>',
    "list": '<path d="M9 6h12M9 12h12M9 18h12"/><circle cx="4.5" cy="6" r="1.2"/><circle cx="4.5" cy="12" r="1.2"/><circle cx="4.5" cy="18" r="1.2"/>',
    "form": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.5 7l8.5 6 8.5-6"/>',
    "repeat": '<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/><path d="M18 2.5v4.2h-4.2M6 21.5v-4.2h4.2"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "logout": '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 16l-4-4 4-4M6 12h10"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/>',
}
NAV = [("dashboard", "/", "home"), ("contacts", "/contacts", "users"), ("lists", "/lists", "list"), ("forms", "/forms", "form"),
       ("campaigns", "/campaigns", "mail"), ("automations", "/automations", "repeat"), ("settings", "/settings", "sliders")]
LOGO = ('<svg class="logo" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="currentColor"/>'
        '<path d="M5 21.5C10.5 8 20 7.5 27 16 20 24.5 10.5 24 5 10.5" fill="none" stroke="var(--logo-ink)" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/><circle cx="21.6" cy="14.2" r="1.1" fill="var(--logo-ink)"/></svg>')


def _static_version():
    """Changes whenever a static file changes, so browsers never keep stale CSS/JS after an update."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    return "%x" % int(max(os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d)))


V = _static_version()


def icon(name):
    return '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">%s</svg>' % ICONS[name]


def T(req, key, **kw):
    return i18n.t(req.lang, key, **kw)


def csrf(req):
    return '<input type="hidden" name="_csrf" value="%s">' % e(req.session["csrf"]) if req.session else ""


def local_time(value, req, with_time=True):
    if not value:
        return ""
    try:
        dt = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return e(value)
    try:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo(db.setting("timezone") or "UTC"))
    except Exception:
        pass
    fmt = ("%d %b %Y" if req.lang == "en" else "%d-%m-%Y") + (", %H:%M" if with_time else "")
    return dt.strftime(fmt)


def badge(req, status):
    return '<span class="badge badge-%s">%s</span>' % (e(status), e(T(req, "status." + status)))


def pct(part, whole):
    return "%d%%" % round(100.0 * part / whole) if whole else "–"


def field(label, control, hint="", cls=""):
    h = '<small class="hint">%s</small>' % hint if hint else ""
    return '<label class="field %s"><span class="label">%s</span>%s%s</label>' % (cls, e(label), control, h)


def inp(name, value="", type_="text", **attrs):
    extra = "".join(' %s="%s"' % (k.rstrip("_").replace("_", "-"), e(v)) for k, v in attrs.items() if v is not None and v is not False)
    return '<input type="%s" name="%s" value="%s"%s>' % (type_, e(name), e(value), extra)


def textarea(name, value="", rows=4, **attrs):
    extra = "".join(' %s="%s"' % (k.rstrip("_").replace("_", "-"), e(v)) for k, v in attrs.items() if v is not None)
    return '<textarea name="%s" rows="%d"%s>%s</textarea>' % (e(name), rows, extra, e(value))


def select(name, options, selected=None, multiple=False, **attrs):
    sel = set(str(s) for s in (selected if isinstance(selected, (list, tuple, set)) else [selected]))
    opts = "".join('<option value="%s"%s>%s</option>' % (e(v), " selected" if str(v) in sel else "", e(l)) for v, l in options)
    extra = "".join(' %s="%s"' % (k.rstrip("_").replace("_", "-"), e(v)) for k, v in attrs.items() if v is not None)
    return '<select name="%s"%s%s>%s</select>' % (e(name), " multiple" if multiple else "", extra, opts)


def checks(name, options, selected):
    sel = set(str(s) for s in selected)
    return '<div class="checks">%s</div>' % "".join(
        '<label class="check"><input type="checkbox" name="%s" value="%s"%s> <span>%s</span></label>' % (e(name), e(v), " checked" if str(v) in sel else "", e(l))
        for v, l in options)


def checkbox(name, checked, label):
    return '<label class="check"><input type="checkbox" name="%s" value="1"%s> <span>%s</span></label>' % (e(name), " checked" if checked else "", e(label))


def lang_options(langs=None):
    return [(c, i18n.LANG_NAMES[c]) for c in (langs or i18n.CONTENT_LANGS) if c in i18n.LANG_NAMES]


def content_langs():
    langs = [x.strip() for x in (db.setting("content_langs") or "").split(",") if x.strip() in i18n.LANG_NAMES]
    default = db.setting("default_lang") or "nl"
    if default not in langs:
        langs.insert(0, default)
    return langs


def empty(req, text, action=""):
    return ('<div class="empty">%s<p>%s</p>%s</div>' % (
        '<svg viewBox="0 0 64 40" aria-hidden="true"><path d="M6 31C17 6 38 5 58 20 38 35 17 34 6 9" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>',
        e(text), action))


def pager(req, total, page, per, base):
    pages = max(1, (total + per - 1) // per)
    if pages <= 1:
        return ""
    sep = "&" if "?" in base else "?"
    prev = '<a class="btn btn-ghost" href="%s%spage=%d">&larr;</a>' % (e(base), sep, page - 1) if page > 1 else ""
    nxt = '<a class="btn btn-ghost" href="%s%spage=%d">&rarr;</a>' % (e(base), sep, page + 1) if page < pages else ""
    return '<nav class="pager">%s<span>%s</span>%s</nav>' % (prev, e(T(req, "common.page_of", page=page, pages=pages)), nxt)


def flash(req, message, kind="ok"):
    if req.session:
        db.run("UPDATE sessions SET flash = ? WHERE token = ?", ("%s|%s" % (kind, message), req.session["token"]))


def _pop_flash(req):
    if not req.session or not req.session["flash"]:
        return ""
    db.run("UPDATE sessions SET flash = NULL WHERE token = ?", (req.session["token"],))
    kind, _, msg = req.session["flash"].partition("|")
    return '<div class="flash flash-%s" role="status">%s</div>' % (e(kind), e(msg))


def page(req, title, body, active="", actions="", status=200):
    org = db.setting("org_name") or "Koinonia"
    nav = "".join('<a href="%s" class="%s">%s<span>%s</span></a>' % (href, "active" if key == active else "", icon(ic), e(T(req, "nav." + key)))
                  for key, href, ic in NAV if key != "settings" or req.user["role"] == "admin")
    langs = "".join('<button name="lang" value="%s" class="%s" title="%s">%s</button>' % (c, "active" if c == req.lang else "", e(i18n.LANG_NAMES[c]), c.upper())
                    for c in i18n.UI_LANGS)
    html = """<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · {org}</title><meta name="csrf-token" content="{csrf_token}"><link rel="stylesheet" href="/static/app.css?v={v}"><link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<script src="/static/app.js?v={v}" defer></script></head><body>
<a class="skip" href="#main">{skip}</a>
<div class="shell"><aside class="sidebar"><a class="brand" href="/">{logo}<span><strong>Koinonia</strong><small>{orgname}</small></span></a>
<nav class="nav">{nav}</nav>
<div class="side-foot"><a href="/account" class="me">{user}</a>
<form method="post" action="/account/lang" class="langs">{csrf}{langs}</form>
<form method="post" action="/logout">{csrf}<button class="link-btn">{logout_icon}<span>{logout}</span></button></form></div></aside>
<main id="main" class="main"><header class="page-head"><h1>{title}</h1><div class="actions">{actions}</div></header>{flash}{body}</main></div></body></html>""".format(
        lang=e(req.lang), title=e(title), org=e(org), skip=e(T(req, "common.skip")), logo=LOGO, orgname=e(org), nav=nav,
        user=e(req.user["name"] or req.user["email"]), csrf=csrf(req), csrf_token=e(req.session["csrf"]), langs=langs, logout_icon=icon("logout"),
        logout=e(T(req, "nav.logout")), actions=actions, flash=_pop_flash(req), body=body, v=V)
    return Response(html, status)


def bare(req, title, body, status=200, lang=None):
    """A centred card page (login, setup, public pages)."""
    lang = lang or req.lang
    html = """<!DOCTYPE html><html lang="{lang}" dir="{dir}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><link rel="stylesheet" href="/static/app.css?v={v}"><link rel="icon" href="/static/favicon.svg" type="image/svg+xml"></head>
<body class="bare"><main class="bare-card">{body}</main></body></html>""".format(lang=e(lang), dir=i18n.direction(lang), title=e(title), body=body, v=V)
    return Response(html, status)
