"""Translations. UI strings for the admin, `pub.*` strings for emails and public pages.

Each language lives in locales/<code>.json. To add a language, copy en.json,
translate the values, and add the code below.
"""
import json
import os

LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")

# Languages the admin interface is translated into.
UI_LANGS = ["nl", "en", "de", "fr", "es", "pt"]
# Languages a campaign / form / public page can be written in.
LANG_NAMES = {
    "nl": "Nederlands", "en": "English", "de": "Deutsch", "fr": "Français", "es": "Español",
    "pt": "Português", "it": "Italiano", "pl": "Polski", "ro": "Română", "af": "Afrikaans",
    "sw": "Kiswahili", "id": "Bahasa Indonesia", "ar": "العربية", "uk": "Українська",
}
CONTENT_LANGS = list(LANG_NAMES)
RTL = {"ar", "he", "fa", "ur"}

_data = {}


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def load():
    _data.clear()
    for name in os.listdir(LOCALE_DIR):
        if name.endswith(".json"):
            with open(os.path.join(LOCALE_DIR, name), encoding="utf-8") as f:
                _data[name[:-5]] = json.load(f)


def t(lang, key, **kw):
    if not _data:
        load()
    s = _data.get(lang, {}).get(key)
    if s is None:
        s = _data.get("en", {}).get(key, key)
    return s.format_map(_Safe(kw)) if kw else s


def ui_lang(lang):
    return lang if lang in UI_LANGS else "en"


def content_lang(lang, default="en"):
    lang = (lang or "").strip().lower()[:2]
    return lang if lang in LANG_NAMES else default


def direction(lang):
    return "rtl" if lang in RTL else "ltr"


def keys(lang):
    if not _data:
        load()
    return set(_data.get(lang, {}))
