"""Puts a campaign, a language variant and a recipient together into a finished email."""
from . import db, i18n, mailer, render


def variant(campaign, lang):
    row = db.one("SELECT * FROM variants WHERE campaign_id = ? AND lang = ?", (campaign["id"], lang))
    if row is None:
        row = db.one("SELECT * FROM variants WHERE campaign_id = ? AND lang = ?", (campaign["id"], campaign["default_lang"]))
    if row is None:
        row = db.one("SELECT * FROM variants WHERE campaign_id = ? ORDER BY rowid LIMIT 1", (campaign["id"],))
    return row


def blocks_of(v):
    b = db.jl(v["blocks"] if v else "[]")
    return [x for x in b if isinstance(x, dict)] if isinstance(b, list) else []


def link_id(campaign_id, url, cache):
    if url in cache:
        return cache[url]
    db.run("INSERT OR IGNORE INTO links(campaign_id, url) VALUES (?, ?)", (campaign_id, url))
    cache[url] = db.val("SELECT id FROM links WHERE campaign_id = ? AND url = ?", (campaign_id, url))
    return cache[url]


def build(campaign, lang, contact=None, delivery=None, cfg=None, blocks=None, subject=None, preheader=None,
          tracking=True, link_cache=None, public=False):
    """Returns dict(subject, html, text, headers, from_name, from_email, reply_to, lang)."""
    cfg = cfg or db.settings()
    base = cfg.get("base_url", "").rstrip("/")
    v = variant(campaign, lang)
    if blocks is None:
        lang = v["lang"] if v else (lang or campaign["default_lang"])
        blocks = blocks_of(v)
    # else: a live preview of unsaved content; keep the language that was asked for
    subject = subject if subject is not None else (v["subject"] if v else "")
    preheader = preheader if preheader is not None else (v["preheader"] if v else "")
    theme = db.jl(campaign["theme"], {}) if campaign["theme"] else {}
    if not isinstance(theme, dict):
        theme = {}
    tok = delivery["token"] if delivery else None
    cache = link_cache if link_cache is not None else {}

    def link(url):
        if not (tracking and tok and campaign["track_clicks"]) or not url.startswith(("http://", "https://")) or "{{" in url:
            return url
        return "%s/c/%s/%d" % (base, tok, link_id(campaign["id"], url, cache))

    contact_token = contact["token"] if contact else None
    urls = {
        "view": "%s/v/%s" % (base, tok) if tok else ("%s/archive/%s" % (base, campaign["public_id"]) if campaign["archive"] else ""),
        "preferences": "%s/p/%s" % (base, contact_token) if contact_token else "%s/p/preview" % base,
        "unsubscribe": "%s/u/%s" % (base, tok) if tok else "%s/u/preview" % base,
    }
    if public:  # archive page: nobody to unsubscribe
        urls = {}
    values = {"org_name": cfg.get("org_name", "")}
    if contact:
        values.update(first_name=contact["first_name"], last_name=contact["last_name"], email=contact["email"])
    ctx = {
        "lang": lang, "subject": subject, "preheader": preheader, "base_url": base,
        "accent": theme.get("accent") or cfg.get("accent_color"), "background": theme.get("background"), "font": theme.get("font", "sans"),
        "link": link, "merge": values, "donate_url": cfg.get("donate_url", ""),
        "org": {"name": cfg.get("org_name", ""), "address": cfg.get("org_address", ""), "logo_url": cfg.get("logo_url", "")},
        "urls": urls,
        "pixel": "%s/o/%s.gif" % (base, tok) if (tracking and tok and campaign["track_opens"]) else "",
        "ics_url": lambda i: "%s/ics/%s/%s/%d.ics" % (base, campaign["public_id"], lang, i),
    }
    html, text = render.render(blocks, ctx)
    headers = {}
    if tok:
        headers["List-Unsubscribe"] = "<%s/u/%s>" % (base, tok)
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        headers["X-Koinonia-Campaign"] = campaign["public_id"]
    return {
        "subject": render.merge(subject, values, False), "html": html, "text": text, "headers": headers, "lang": lang,
        "from_name": campaign["from_name"] or cfg.get("from_name") or cfg.get("org_name", ""),
        "from_email": campaign["from_email"] or cfg.get("from_email", ""),
        "reply_to": campaign["reply_to"] or cfg.get("reply_to", ""),
    }


def message(built, to):
    return mailer.build(built["from_name"], built["from_email"], to, built["subject"], built["html"], built["text"],
                        built["reply_to"], built["headers"], built["lang"])


def confirmation_email(form, contact, token, cfg=None):
    """The double opt-in email, in the language of the form/contact."""
    cfg = cfg or db.settings()
    lang = i18n.content_lang(contact["lang"] or form["lang"], form["lang"])
    org = cfg.get("org_name", "")
    base = cfg.get("base_url", "").rstrip("/")
    blocks = [
        {"type": "heading", "text": i18n.t(lang, "pub.confirm_subject", org=org), "level": "2"},
        {"type": "text", "text": i18n.t(lang, "pub.confirm_body")},
        {"type": "button", "label": i18n.t(lang, "pub.confirm_btn"), "url": "%s/confirm/%s" % (base, token)},
    ]
    ctx = {"lang": lang, "subject": i18n.t(lang, "pub.confirm_subject", org=org), "base_url": base, "accent": cfg.get("accent_color"),
           "org": {"name": org, "address": cfg.get("org_address", ""), "logo_url": cfg.get("logo_url", "")}, "urls": {},
           "merge": {"first_name": contact["first_name"]}}
    html, text = render.render(blocks, ctx)
    return mailer.build(cfg.get("from_name") or org, cfg.get("from_email", ""), contact["email"], ctx["subject"], html, text,
                        cfg.get("reply_to", ""), {}, lang)

