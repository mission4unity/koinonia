import json
import os
import re
import unittest

from helpers import fresh_app  # noqa: F401  (sets up isolated paths first)

from koinonia import audience, db, i18n, mailer, render, security, templates


def ctx(**kw):
    base = {"lang": "nl", "subject": "S", "preheader": "P", "base_url": "https://k.example", "org": {"name": "De Ark", "address": "Straat 1"},
            "urls": {"unsubscribe": "https://k.example/u/x", "preferences": "https://k.example/p/y", "view": "https://k.example/v/x"},
            "merge": {"first_name": "Piet"}}
    base.update(kw)
    return base


class RenderTests(unittest.TestCase):
    def test_markdown_escapes_and_formats(self):
        h = render.markdown("Hallo <script>x</script> **vet** en *schuin*\n\n- een\n- twee\n\n[site](https://a.example/?a=1&b=2)")
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;script&gt;", h)
        self.assertIn("<strong>vet</strong>", h)
        self.assertIn("<em>schuin</em>", h)
        self.assertIn("<ul", h)
        self.assertIn('href="https://a.example/?a=1&amp;b=2"', h)

    def test_unsafe_links_are_dropped(self):
        h = render.markdown("[klik](javascript:alert(1))")
        self.assertNotIn("javascript:", h)
        html, _ = render.render([{"type": "button", "label": "x", "url": "javascript:alert(1)"},
                                 {"type": "image", "src": "data:text/html,boo"}], ctx())
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data:text/html", html)

    def test_attribute_injection_is_escaped(self):
        html, _ = render.render([{"type": "image", "src": 'https://x.example/a.png" onerror="alert(1)', "alt": '"><b>'}], ctx())
        self.assertNotIn('onerror="alert', html)
        self.assertNotIn("<b>", html)

    def test_merge_tags(self):
        html, text = render.render([{"type": "text", "text": "Beste {{first_name|vriend}}, {{last_name|}}!"}], ctx(merge={"first_name": "<Jan>"}))
        self.assertIn("Beste &lt;Jan&gt;,", html)
        self.assertIn("Beste <Jan>,", text)
        html, _ = render.render([{"type": "text", "text": "Beste {{first_name|vriend}}"}], ctx(merge={}))
        self.assertIn("Beste vriend", html)

    def test_every_block_renders(self):
        blocks = [
            {"type": "heading", "text": "Kop", "level": "1"}, {"type": "text", "text": "Tekst"},
            {"type": "scripture", "reference": "Psalm 23:1", "translation": "SV", "text": "De HEERE is mijn Herder"},
            {"type": "image", "src": "/uploads/a.png", "alt": "a", "href": "https://x.example", "caption": "c"},
            {"type": "button", "label": "Knop", "url": "https://x.example"},
            {"type": "event", "title": "Dienst", "date": "2026-11-01", "time": "10:00", "end_time": "11:30", "location": "Kerk", "description": "Welkom"},
            {"type": "prayer", "title": "", "items": "Een\nTwee"}, {"type": "donate", "title": "Geef", "text": "Dank", "label": "", "url": "https://geef.example"},
            {"type": "video", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Preek"}, {"type": "quote", "text": "Q", "author": "A"},
            {"type": "divider"}, {"type": "spacer", "size": "30"}, {"type": "bogus"}, "not a dict",
        ]
        html, text = render.render(blocks, ctx(ics_url=lambda i: "https://k.example/ics/%d.ics" % i))
        for needle in ["Kop", "De HEERE is mijn Herder", "https://k.example/uploads/a.png", "Knop", "1 november 2026", "Zet in agenda",
                       "Gebedspunten", "https://geef.example", "img.youtube.com/vi/dQw4w9WgXcQ", "Afmelden", "Straat 1"]:
            self.assertIn(needle, html, needle)
        self.assertIn("Psalm 23:1 (SV)", text)
        self.assertIn("Afmelden: https://k.example/u/x", text)
        self.assertNotIn("<", text.replace("<Jan>", ""))

    def test_rtl(self):
        html, _ = render.render([{"type": "text", "text": "مرحبا"}], ctx(lang="ar"))
        self.assertIn('dir="rtl"', html)

    def test_bad_colours_fall_back(self):
        html, _ = render.render([], ctx(accent="red;background:url(x)", background="#zzzzzz"))
        self.assertNotIn("url(x)", html)

    def test_ics(self):
        data = render.ics({"title": "Dienst, met komma", "date": "2026-07-05", "time": "10:00", "end_time": "11:00", "location": "Kerk"}, "u1", "Europe/Amsterdam")
        self.assertIn("DTSTART:20260705T080000Z", data)  # summer time: UTC+2
        self.assertIn("SUMMARY:Dienst\\, met komma", data)
        allday = render.ics({"title": "Dag", "date": "2026-12-25"}, "u2")
        self.assertIn("DTSTART;VALUE=DATE:20261225", allday)
        self.assertIn("DTEND;VALUE=DATE:20261226", allday)

    def test_youtube(self):
        self.assertIn("abcdefghijk", render.youtube_thumb("https://youtu.be/abcdefghijk"))
        self.assertEqual(render.youtube_thumb("https://example.com/watch?v=x"), "")


class CsvTests(unittest.TestCase):
    def setUp(self):
        fresh_app("units")

    def test_dutch_headers_semicolon_bom(self):
        rows, unknown = audience.parse_csv("﻿E-mailadres;Voornaam;Achternaam;Taal;Woonplaats\nA@x.example;Ann;B;EN;Zwolle\n")
        self.assertEqual(rows, [{"email": "A@x.example", "first_name": "Ann", "last_name": "B", "lang": "EN"}])
        self.assertEqual(unknown, ["Woonplaats"])

    def test_no_header(self):
        rows, _ = audience.parse_csv("a@x.example,Ann\nb@x.example,Bob\n")
        self.assertEqual([r["email"] for r in rows], ["a@x.example", "b@x.example"])

    def test_import_rules(self):
        lid = db.run("INSERT INTO lists(name) VALUES ('L')").lastrowid
        stats = audience.import_rows([{"email": "a@x.example", "lang": "de"}, {"email": "A@x.example"}, {"email": "nope"}], lid, ["t1"])
        self.assertEqual(stats, {"added": 1, "updated": 0, "invalid": 1, "skipped": 1})
        cid = db.val("SELECT id FROM contacts WHERE email = 'a@x.example'")
        self.assertEqual(db.val("SELECT lang FROM contacts WHERE id = ?", (cid,)), "de")
        audience.unsubscribe_all(cid)
        stats = audience.import_rows([{"email": "a@x.example"}], lid)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(db.val("SELECT status FROM contacts WHERE id = ?", (cid,)), "unsubscribed")

    def test_audience_with_tags(self):
        lid = db.run("INSERT INTO lists(name) VALUES ('L')").lastrowid
        audience.import_rows([{"email": "a@x.example", "tags": "jeugd"}, {"email": "b@x.example"}], lid)
        tid = db.val("SELECT id FROM tags WHERE name = 'jeugd'")
        self.assertEqual(audience.audience_count([lid], []), 2)
        self.assertEqual(audience.audience_count([lid], [tid]), 1)
        self.assertEqual(audience.audience_count([], []), 0)


class SecurityTests(unittest.TestCase):
    def test_passwords(self):
        h = security.hash_password("geheim wachtwoord")
        self.assertTrue(security.check_password("geheim wachtwoord", h))
        self.assertFalse(security.check_password("fout", h))
        self.assertFalse(security.check_password("x", "garbage"))

    def test_emails(self):
        self.assertTrue(security.valid_email("a.b+c@sub.example.org"))
        for bad in ["", "a@b", "a b@x.org", "a@x.org\nBcc: y@z.org", "@x.org"]:
            self.assertFalse(security.valid_email(bad), bad)

    def test_rate_limiter(self):
        rl = security.RateLimiter(2, 60)
        self.assertTrue(rl.allow("k") and rl.allow("k"))
        self.assertFalse(rl.allow("k"))
        self.assertTrue(rl.allow("other"))

    def test_header_injection_is_neutralised(self):
        msg = mailer.build("Naam\r\nBcc: evil@x.org", "a@x.org", "b@x.org", "Onderwerp\nBcc: evil@x.org", "<p>h</p>", "t")
        self.assertIsNone(msg["Bcc"])
        self.assertNotIn("\n", msg["Subject"])


class I18nTests(unittest.TestCase):
    def test_ui_languages_are_complete(self):
        en = i18n.keys("en")
        for lang in i18n.UI_LANGS:
            missing = en - i18n.keys(lang)
            self.assertFalse(missing, "%s is missing %s" % (lang, sorted(missing)[:10]))

    def test_public_strings_exist_for_every_content_language(self):
        pub = {k for k in i18n.keys("en") if k.startswith("pub.")}
        for lang in i18n.CONTENT_LANGS:
            missing = pub - i18n.keys(lang)
            self.assertFalse(missing, "%s is missing %s" % (lang, sorted(missing)))
            self.assertEqual(len(i18n.t(lang, "pub.months").split(",")), 12, lang)

    def test_placeholders_match(self):
        for lang in i18n.CONTENT_LANGS:
            for k in i18n.keys(lang):
                want = set(re.findall(r"(?<!\{)\{(\w+)\}(?!\})", i18n.t("en", k)))
                got = set(re.findall(r"(?<!\{)\{(\w+)\}(?!\})", i18n.t(lang, k)))
                self.assertEqual(want, got, "%s %s" % (lang, k))

    def test_no_unknown_keys(self):
        en = i18n.keys("en")
        for lang in i18n.CONTENT_LANGS:
            self.assertFalse(i18n.keys(lang) - en, lang)

    def test_templates_build_in_every_language(self):
        for lang in i18n.CONTENT_LANGS:
            for t in templates.TEMPLATES:
                blocks = templates.blocks(t, lang)
                html, text = render.render(blocks, ctx(lang=lang))
                self.assertIn("<html", html)
                json.dumps(blocks)


if __name__ == "__main__":
    unittest.main()
