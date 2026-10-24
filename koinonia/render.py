"""Turns a list of content blocks into an email (HTML + plain text).

Everything is rendered with inline styles and tables so it survives Outlook,
Gmail and Apple Mail. User text is always escaped; links are limited to safe
schemes and pass through `ctx["link"]` so they can be tracked.
"""
import html
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

from . import i18n

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FONTS = {
    "serif": "Georgia, 'Times New Roman', Times, serif",
    "sans": "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif",
}
BLOCK_TYPES = ["heading", "text", "scripture", "image", "button", "event", "prayer", "donate", "video", "quote", "divider", "spacer"]
MERGE_RE = re.compile(r"\{\{\s*([a-z_]+)\s*(?:\|([^{}]*))?\}\}")


def esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def safe_url(url, base=""):
    """Return url if it uses an allowed scheme, else ''. Relative /uploads paths become absolute."""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("/") and not url.startswith("//"):
        return base.rstrip("/") + url
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https", "mailto", "tel"):
        return url
    return ""


def tint(hex_color, amount=0.9):
    """Mix a colour with white (amount 0..1 = how much white)."""
    if not HEX.match(hex_color or ""):
        hex_color = "#3d5a40"
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    mix = lambda c: int(c + (255 - c) * amount)
    return "#%02x%02x%02x" % (mix(r), mix(g), mix(b))


# ---------------------------------------------------------------- mini markdown
INLINE_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def _inline(text, link, color):
    """Escape and format one line: **bold**, *italic*, [label](url)."""
    out, holders = esc(text), []

    def keep(m):
        url = safe_url(html.unescape(m.group(2)))
        if not url:
            return m.group(1)
        holders.append('<a href="%s" style="color:%s;text-decoration:underline;">%s</a>' % (esc(link(url)), color, m.group(1)))
        return "\x00%d\x00" % (len(holders) - 1)

    out = INLINE_LINK.sub(keep, out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: holders[int(m.group(1))], out)


def markdown(text, link=lambda u: u, color="#3d5a40", p_style=""):
    blocks, out = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").strip()), []
    for block in blocks:
        if not block.strip():
            continue
        lines = block.split("\n")
        if all(re.match(r"^\s*[-*•]\s+", l) for l in lines):
            items = "".join("<li style=\"margin:0 0 6px;\">%s</li>" % _inline(re.sub(r"^\s*[-*•]\s+", "", l), link, color) for l in lines)
            out.append('<ul style="margin:0 0 16px;padding-left:22px;%s">%s</ul>' % (p_style, items))
        elif all(re.match(r"^\s*\d+[.)]\s+", l) for l in lines):
            items = "".join("<li style=\"margin:0 0 6px;\">%s</li>" % _inline(re.sub(r"^\s*\d+[.)]\s+", "", l), link, color) for l in lines)
            out.append('<ol style="margin:0 0 16px;padding-left:22px;%s">%s</ol>' % (p_style, items))
        else:
            out.append('<p style="margin:0 0 16px;%s">%s</p>' % (p_style, "<br>".join(_inline(l, link, color) for l in lines)))
    return "".join(out)


def markdown_text(text):
    t = INLINE_LINK.sub(lambda m: "%s (%s)" % (m.group(1), m.group(2)), text or "")
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", t).strip()


# ---------------------------------------------------------------- helpers
def youtube_thumb(url):
    try:
        u = urlparse(url)
    except ValueError:
        return ""
    vid = ""
    if u.hostname in ("youtu.be",):
        vid = u.path.strip("/")
    elif u.hostname and u.hostname.endswith("youtube.com"):
        vid = parse_qs(u.query).get("v", [""])[0] or (u.path.split("/")[-1] if "/embed/" in u.path or "/live/" in u.path or "/shorts/" in u.path else "")
    return "https://img.youtube.com/vi/%s/hqdefault.jpg" % vid if re.match(r"^[A-Za-z0-9_-]{6,20}$", vid or "") else ""


def format_date(value, lang):
    try:
        d = date.fromisoformat((value or "").strip())
    except ValueError:
        return value or ""
    months = i18n.t(lang, "pub.months").split(",")
    month = months[d.month - 1].strip() if len(months) == 12 else str(d.month)
    return "%d %s %d" % (d.day, month, d.year)


def lines(text):
    return [l.strip(" -•*\t") for l in (text or "").splitlines() if l.strip(" -•*\t")]


# ---------------------------------------------------------------- blocks
def _row(inner, pad="0 32px 20px"):
    return '<tr><td style="padding:%s;">%s</td></tr>' % (pad, inner)


def _button(label, href, color, font):
    return ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto;">'
            '<tr><td style="background:%s;border-radius:999px;">'
            '<a href="%s" style="display:inline-block;padding:13px 28px;font-family:%s;font-size:16px;font-weight:bold;'
            'color:#ffffff;text-decoration:none;border-radius:999px;">%s</a></td></tr></table>') % (color, esc(href), font, esc(label))


def render_block(b, ctx):
    t, c, F, lang = b.get("type"), ctx["accent"], ctx["font"], ctx["lang"]
    link, base = ctx["link"], ctx["base_url"]
    ink, body = "#1d2622", "#33403a"
    if t == "heading":
        size = "28px" if str(b.get("level", "1")) == "1" else "21px"
        txt = (b.get("text") or "").strip()
        return _row('<h%s style="margin:0;font-family:%s;font-size:%s;line-height:1.25;color:%s;">%s</h%s>' % (
            "1" if size == "28px" else "2", FONTS["serif"], size, ink, esc(txt), "1" if size == "28px" else "2"), "8px 32px 14px") if txt else ""
    if t == "text":
        h = markdown(b.get("text"), link, c, "font-family:%s;font-size:16px;line-height:1.65;color:%s;" % (F, body))
        return _row(h, "0 32px 6px") if h else ""
    if t == "scripture":
        txt = (b.get("text") or "").strip()
        if not txt:
            return ""
        ref = " ".join(x for x in [(b.get("reference") or "").strip(), "(%s)" % b["translation"].strip() if (b.get("translation") or "").strip() else ""] if x)
        return _row('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0"><tr>'
                    '<td style="border-%s:4px solid %s;background:%s;padding:18px 22px;border-radius:4px;">'
                    '<p style="margin:0 0 8px;font-family:%s;font-size:19px;line-height:1.55;font-style:italic;color:%s;">%s</p>'
                    '<p style="margin:0;font-family:%s;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:%s;">%s</p>'
                    '</td></tr></table>' % ("right" if ctx["rtl"] else "left", c, tint(c, .92), FONTS["serif"], ink,
                                            esc(txt).replace("\n", "<br>"), F, c, esc(ref)))
    if t == "image":
        src = safe_url(b.get("src"), base)
        if not src:
            return ""
        img = '<img src="%s" alt="%s" width="536" style="display:block;width:100%%;max-width:536px;height:auto;border:0;border-radius:6px;">' % (esc(src), esc(b.get("alt")))
        href = safe_url(b.get("href"), base)
        if href:
            img = '<a href="%s">%s</a>' % (esc(link(href)), img)
        cap = (b.get("caption") or "").strip()
        if cap:
            img += '<p style="margin:8px 0 0;font-family:%s;font-size:13px;color:#6b746f;text-align:center;">%s</p>' % (F, esc(cap))
        return _row(img)
    if t == "button":
        href, label = safe_url(b.get("url"), base), (b.get("label") or "").strip()
        return _row(_button(label, link(href), c, F), "6px 32px 24px") if href and label else ""
    if t == "event":
        title = (b.get("title") or "").strip()
        if not title:
            return ""
        when = format_date(b.get("date"), lang)
        tm = " – ".join(x for x in [(b.get("time") or "").strip(), (b.get("end_time") or "").strip()] if x)
        meta = "".join('<p style="margin:0 0 4px;font-family:%s;font-size:15px;color:%s;">%s</p>' % (F, body, esc(x))
                       for x in [", ".join(y for y in [when, tm] if y), (b.get("location") or "").strip()] if x)
        desc = markdown(b.get("description"), link, c, "font-family:%s;font-size:15px;line-height:1.6;color:%s;" % (F, body))
        cal = ""
        if ctx.get("ics_url") and b.get("date") and ctx.get("index") is not None:
            cal = '<p style="margin:12px 0 0;font-family:%s;font-size:14px;"><a href="%s" style="color:%s;font-weight:bold;">%s</a></p>' % (
                F, esc(ctx["ics_url"](ctx["index"])), c, esc(i18n.t(lang, "pub.add_calendar")))
        return _row('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0"><tr>'
                    '<td style="border:1px solid %s;border-radius:8px;padding:20px 22px;">'
                    '<p style="margin:0 0 4px;font-family:%s;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:%s;">%s</p>'
                    '<p style="margin:0 0 10px;font-family:%s;font-size:20px;font-weight:bold;color:%s;">%s</p>%s<div style="margin-top:10px;">%s</div>%s'
                    '</td></tr></table>' % (tint(c, .7), F, c, esc(i18n.t(lang, "pub.event")), FONTS["serif"], ink, esc(title), meta, desc, cal))
    if t == "prayer":
        items = lines(b.get("items"))
        if not items:
            return ""
        title = (b.get("title") or "").strip() or i18n.t(lang, "pub.prayer_title")
        lis = "".join('<tr><td valign="top" style="padding:0 10px 8px 0;font-family:%s;font-size:16px;color:%s;">&#10022;</td>'
                      '<td style="padding:0 0 8px;font-family:%s;font-size:16px;line-height:1.55;color:%s;">%s</td></tr>' % (
                          F, c, F, body, _inline(i, link, c)) for i in items)
        return _row('<h3 style="margin:0 0 12px;font-family:%s;font-size:19px;color:%s;">%s</h3>'
                    '<table role="presentation" cellpadding="0" cellspacing="0" border="0">%s</table>' % (FONTS["serif"], ink, esc(title), lis))
    if t == "donate":
        href = safe_url(b.get("url") or ctx.get("donate_url"), base)
        title, text = (b.get("title") or "").strip(), (b.get("text") or "").strip()
        if not (href or title or text):
            return ""
        inner = ""
        if title:
            inner += '<p style="margin:0 0 8px;font-family:%s;font-size:21px;font-weight:bold;color:%s;">%s</p>' % (FONTS["serif"], ink, esc(title))
        if text:
            inner += markdown(text, link, c, "font-family:%s;font-size:15px;line-height:1.6;color:%s;" % (F, body))
        if href:
            inner += _button((b.get("label") or "").strip() or i18n.t(lang, "pub.give"), link(href), c, F)
        return _row('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0"><tr>'
                    '<td align="center" style="background:%s;border-radius:10px;padding:26px 24px;text-align:center;">%s</td></tr></table>' % (tint(c, .88), inner))
    if t == "video":
        href = safe_url(b.get("url"), base)
        if not href:
            return ""
        thumb = safe_url(b.get("thumbnail"), base) or youtube_thumb(href)
        title = (b.get("title") or "").strip()
        out = ""
        if thumb:
            out += '<a href="%s"><img src="%s" alt="%s" width="536" style="display:block;width:100%%;max-width:536px;height:auto;border:0;border-radius:6px;"></a>' % (
                esc(link(href)), esc(thumb), esc(title))
        if title:
            out += '<p style="margin:10px 0 4px;font-family:%s;font-size:18px;font-weight:bold;color:%s;">%s</p>' % (FONTS["serif"], ink, esc(title))
        out += '<p style="margin:4px 0 0;font-family:%s;font-size:15px;"><a href="%s" style="color:%s;font-weight:bold;">&#9654; %s</a></p>' % (
            F, esc(link(href)), c, esc(i18n.t(lang, "pub.watch")))
        return _row(out)
    if t == "quote":
        txt = (b.get("text") or "").strip()
        if not txt:
            return ""
        who = (b.get("author") or "").strip()
        return _row('<p style="margin:0;font-family:%s;font-size:44px;line-height:1;color:%s;">&ldquo;</p>'
                    '<p style="margin:0 0 8px;font-family:%s;font-size:18px;line-height:1.6;font-style:italic;color:%s;">%s</p>%s' % (
                        FONTS["serif"], tint(c, .4), FONTS["serif"], ink, esc(txt).replace("\n", "<br>"),
                        '<p style="margin:0;font-family:%s;font-size:14px;color:#6b746f;">— %s</p>' % (F, esc(who)) if who else ""))
    if t == "divider":
        return _row('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0"><tr><td style="border-top:1px solid %s;font-size:0;line-height:0;">&nbsp;</td></tr></table>' % tint(c, .75), "6px 32px 22px")
    if t == "spacer":
        try:
            h = max(4, min(120, int(b.get("size") or 24)))
        except (TypeError, ValueError):
            h = 24
        return '<tr><td style="height:%dpx;font-size:0;line-height:0;">&nbsp;</td></tr>' % h
    return ""


def block_text(b, lang):
    t = b.get("type")
    if t == "heading":
        s = (b.get("text") or "").strip()
        return s.upper() if str(b.get("level", "1")) == "1" and s else s
    if t == "text":
        return markdown_text(b.get("text"))
    if t == "scripture" and (b.get("text") or "").strip():
        ref = " ".join(x for x in [(b.get("reference") or "").strip(), "(%s)" % b["translation"].strip() if (b.get("translation") or "").strip() else ""] if x)
        return '"%s"\n— %s' % (b["text"].strip(), ref) if ref else '"%s"' % b["text"].strip()
    if t == "image":
        return (b.get("caption") or "").strip()
    if t == "button" and b.get("url") and b.get("label"):
        return "%s: %s" % (b["label"].strip(), b["url"].strip())
    if t == "event" and (b.get("title") or "").strip():
        tm = " – ".join(x for x in [(b.get("time") or "").strip(), (b.get("end_time") or "").strip()] if x)
        parts = [b["title"].strip(), ", ".join(y for y in [format_date(b.get("date"), lang), tm] if y), (b.get("location") or "").strip(), markdown_text(b.get("description"))]
        return "\n".join(p for p in parts if p)
    if t == "prayer" and lines(b.get("items")):
        return "\n".join([(b.get("title") or "").strip() or i18n.t(lang, "pub.prayer_title")] + ["* " + markdown_text(i) for i in lines(b.get("items"))])
    if t == "donate":
        parts = [(b.get("title") or "").strip(), markdown_text(b.get("text")), (b.get("url") or "").strip()]
        return "\n".join(p for p in parts if p)
    if t == "video" and b.get("url"):
        return "\n".join(p for p in [(b.get("title") or "").strip(), b["url"].strip()] if p)
    if t == "quote" and (b.get("text") or "").strip():
        return '"%s"%s' % (b["text"].strip(), "\n— " + b["author"].strip() if (b.get("author") or "").strip() else "")
    if t == "divider":
        return "———"
    return ""


def merge(text, values, escape):
    def sub(m):
        v = values.get(m.group(1))
        if v:
            return esc(v) if escape else str(v)
        return m.group(2).strip() if m.group(2) is not None else ""
    return MERGE_RE.sub(sub, text)


def render(blocks, ctx):
    """ctx keys: lang, subject, preheader, accent, background, font(key), base_url, link(fn),
    merge(dict), org(dict), urls(dict: unsubscribe, preferences, view), pixel, ics_url(fn), donate_url."""
    lang = ctx.get("lang") or "en"
    accent = ctx.get("accent") if HEX.match(ctx.get("accent") or "") else "#3d5a40"
    bg = ctx.get("background") if HEX.match(ctx.get("background") or "") else "#f4f1ea"
    font = FONTS.get(ctx.get("font"), FONTS["sans"])
    rctx = dict(ctx, accent=accent, font=font, lang=lang, rtl=lang in i18n.RTL,
                link=ctx.get("link") or (lambda u: u), base_url=ctx.get("base_url", ""))
    rows = []
    for i, b in enumerate(blocks or []):
        if isinstance(b, dict) and b.get("type") in BLOCK_TYPES:
            rctx["index"] = i
            rows.append(render_block(b, rctx))
    org, urls = ctx.get("org") or {}, ctx.get("urls") or {}
    d = i18n.direction(lang)
    logo = safe_url(org.get("logo_url"), rctx["base_url"])
    header = ""
    if logo:
        header = '<tr><td align="center" style="padding:28px 32px 8px;"><img src="%s" alt="%s" height="56" style="display:block;height:56px;width:auto;border:0;"></td></tr>' % (esc(logo), esc(org.get("name")))
    elif org.get("name"):
        header = '<tr><td align="center" style="padding:28px 32px 8px;font-family:%s;font-size:15px;letter-spacing:.12em;text-transform:uppercase;color:%s;">%s</td></tr>' % (FONTS["serif"], accent, esc(org["name"]))
    foot_links = " &middot; ".join('<a href="%s" style="color:#5f6b65;text-decoration:underline;">%s</a>' % (esc(u), esc(i18n.t(lang, k)))
                                   for k, u in (("pub.view_online", urls.get("view")), ("pub.preferences", urls.get("preferences")), ("pub.unsubscribe", urls.get("unsubscribe"))) if u)
    address = esc(org.get("address")).replace("\n", "<br>")
    footer = ('<tr><td style="padding:22px 32px 30px;font-family:%s;font-size:12px;line-height:1.6;color:#5f6b65;text-align:center;">'
              '<p style="margin:0 0 6px;"><strong>%s</strong>%s</p><p style="margin:0 0 6px;">%s</p><p style="margin:0;">%s</p></td></tr>') % (
        font, esc(org.get("name")), "<br>" + address if address else "", esc(i18n.t(lang, "pub.why", org=org.get("name") or "")), foot_links)
    pre = esc(ctx.get("preheader"))
    pixel = '<img src="%s" width="1" height="1" alt="" style="display:block;width:1px;height:1px;border:0;">' % esc(ctx["pixel"]) if ctx.get("pixel") else ""
    doc = ('<!DOCTYPE html><html lang="%s" dir="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<meta name="color-scheme" content="light"><title>%s</title></head>'
           '<body style="margin:0;padding:0;background:%s;" dir="%s">'
           '<div style="display:none;max-height:0;overflow:hidden;opacity:0;">%s&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;</div>'
           '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" style="background:%s;"><tr><td align="center" style="padding:24px 12px;">'
           '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%%;max-width:600px;background:#ffffff;border-radius:12px;border-top:6px solid %s;">'
           '%s<tr><td style="height:12px;font-size:0;line-height:0;">&nbsp;</td></tr>%s</table>'
           '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%%;max-width:600px;">%s</table>'
           '%s</td></tr></table></body></html>') % (
        esc(lang), d, esc(ctx.get("subject")), bg, d, pre, bg, accent, header, "".join(rows), footer, pixel)
    values = ctx.get("merge") or {}
    text_parts = [block_text(b, lang) for b in blocks or [] if isinstance(b, dict)]
    text = "\n\n".join(p for p in text_parts if p)
    tail = [org.get("name") or "", org.get("address") or "", i18n.t(lang, "pub.why", org=org.get("name") or "")]
    for k, u in (("pub.view_online", urls.get("view")), ("pub.preferences", urls.get("preferences")), ("pub.unsubscribe", urls.get("unsubscribe"))):
        if u:
            tail.append("%s: %s" % (i18n.t(lang, k), u))
    text += "\n\n--\n" + "\n".join(x for x in tail if x)
    return merge(doc, values, True), merge(text, values, False)


def ics(block, uid, tzname="UTC", prodid="Koinonia"):
    """A minimal iCalendar file for an event block."""
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tzname)
    except Exception:
        tz = timezone.utc
    d = date.fromisoformat((block.get("date") or "").strip())

    def at(hhmm):
        h, m = (int(x) for x in hhmm.strip().split(":")[:2])
        return datetime(d.year, d.month, d.day, h, m, tzinfo=tz).astimezone(timezone.utc)

    def fold(s):
        s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")
        return s

    lines_ = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//%s//NL" % prodid, "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT",
              "UID:%s" % uid, "DTSTAMP:%s" % datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")]
    start = (block.get("time") or "").strip()
    try:
        s = at(start) if start else None
        e_ = at(block["end_time"]) if s and (block.get("end_time") or "").strip() else (s + timedelta(hours=1) if s else None)
        if e_ is not None and s is not None and e_ <= s:
            e_ = s + timedelta(hours=1)
    except (ValueError, IndexError):
        s = e_ = None
    if s:
        lines_ += ["DTSTART:" + s.strftime("%Y%m%dT%H%M%SZ"), "DTEND:" + e_.strftime("%Y%m%dT%H%M%SZ")]
    else:
        lines_ += ["DTSTART;VALUE=DATE:" + d.strftime("%Y%m%d"), "DTEND;VALUE=DATE:" + (d + timedelta(days=1)).strftime("%Y%m%d")]
    lines_.append("SUMMARY:" + fold(block.get("title") or ""))
    if (block.get("location") or "").strip():
        lines_.append("LOCATION:" + fold(block["location"]))
    if (block.get("description") or "").strip():
        lines_.append("DESCRIPTION:" + fold(markdown_text(block["description"])))
    lines_ += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines_) + "\r\n"
