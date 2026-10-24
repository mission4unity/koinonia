"""Starter templates. Texts come from the locale files (tpl.*) so every template
starts in the language the campaign is written in."""
from . import i18n

TEMPLATES = ["blank", "newsletter", "prayer", "mission", "event", "welcome"]


def _verse(t):
    return {"type": "scripture", "reference": t("tpl.verse.ref"), "translation": t("tpl.verse.translation"), "text": t("tpl.verse.text")}


def blocks(name, lang, donate_url=""):
    t = lambda k: i18n.t(lang, k)
    donate = {"type": "donate", "title": t("tpl.donate.title"), "text": t("tpl.donate.text"), "label": t("tpl.donate.label"), "url": donate_url}
    if name == "newsletter":
        return [
            {"type": "heading", "text": t("tpl.newsletter.heading"), "level": "1"},
            {"type": "text", "text": t("tpl.newsletter.intro")},
            _verse(t),
            {"type": "event", "title": t("tpl.event.title"), "date": "", "time": "10:00", "end_time": "11:30", "location": "", "description": ""},
            {"type": "prayer", "title": "", "items": t("tpl.prayer.items")},
            {"type": "divider"},
            donate,
        ]
    if name == "prayer":
        return [
            {"type": "heading", "text": t("tpl.prayer.heading"), "level": "1"},
            {"type": "text", "text": t("tpl.prayer.intro")},
            {"type": "prayer", "title": "", "items": t("tpl.prayer.items")},
            {"type": "prayer", "title": t("tpl.prayer.thanks_title"), "items": t("tpl.prayer.thanks_items")},
            _verse(t),
        ]
    if name == "mission":
        return [
            {"type": "image", "src": "", "alt": "", "href": "", "caption": ""},
            {"type": "heading", "text": t("tpl.mission.heading"), "level": "1"},
            {"type": "text", "text": t("tpl.mission.intro")},
            {"type": "quote", "text": t("tpl.mission.quote"), "author": ""},
            {"type": "prayer", "title": "", "items": t("tpl.prayer.items")},
            donate,
        ]
    if name == "event":
        return [
            {"type": "heading", "text": t("tpl.event.heading"), "level": "1"},
            {"type": "text", "text": t("tpl.event.intro")},
            {"type": "event", "title": t("tpl.event.title"), "date": "", "time": "19:30", "end_time": "21:00", "location": "", "description": ""},
            {"type": "button", "label": t("tpl.event.button"), "url": ""},
        ]
    if name == "welcome":
        return [
            {"type": "heading", "text": t("tpl.welcome.heading"), "level": "1"},
            {"type": "text", "text": t("tpl.welcome.intro")},
            _verse(t),
            {"type": "button", "label": t("tpl.welcome.button"), "url": ""},
        ]
    return [{"type": "heading", "text": "", "level": "1"}, {"type": "text", "text": ""}]


def subject(name, lang):
    return "" if name == "blank" else i18n.t(lang, "tpl.%s.subject" % name)
