"""End-to-end: the whole journey of a church, through the real WSGI app."""
import base64
import json
import re
import unittest
from urllib.parse import parse_qs, urlparse

from helpers import Client, FakeSMTP, clear_outbox, fresh_app, html_of, outbox, setup_admin, text_of

from koinonia import db, i18n, worker


def csrf_of(text):
    return re.search(r'name="_csrf" value="([^"]+)"', text).group(1)


class Journey(unittest.TestCase):
    def setUp(self):
        self.app = fresh_app("e2e-" + self._testMethodName)
        self.c = Client(self.app)
        clear_outbox()

    def tick(self, n=1):
        w = worker.Worker()
        for _ in range(n):
            w.tick()
        return w

    def new_list(self, name, double=False):
        self.c.get("/lists/new")
        data = {"name": name, "description": "over " + name}
        if double:
            data["double_optin"] = "1"
        r = self.c.post("/lists/new", data)
        self.assertEqual(r.status, 303)
        return db.val("SELECT id FROM lists WHERE name = ?", (name,))

    # ------------------------------------------------------------------ basics
    def test_setup_login_and_every_page(self):
        r = self.c.get("/")
        self.assertEqual((r.status, r.header("Location")), (303, "/setup"))
        setup_admin(self.c)
        r = self.c.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("Vrede zij met je, Anna", r.text)
        self.assertIn("Content-Security-Policy", [k for k, _ in r.headers])
        # setup cannot be run twice
        self.assertEqual(self.c.get("/setup").status, 303)
        for path in ["/contacts", "/contacts/new", "/contacts/import", "/lists", "/lists/new", "/forms", "/forms/new", "/campaigns",
                     "/campaigns/new", "/automations", "/automations/new", "/settings", "/settings/sending", "/settings/team",
                     "/settings/deliverability", "/account", "/contacts/export.csv", "/archive", "/health", "/static/app.css", "/static/editor.js"]:
            self.assertEqual(self.c.get(path).status, 200, path)
        self.assertEqual(self.c.get("/nope").status, 404)
        self.assertEqual(self.c.get("/static/../koinonia/db.py").status, 404)
        # every UI language renders
        for lang in i18n.UI_LANGS:
            self.c.post("/account/lang", {"lang": lang})
            r = self.c.get("/campaigns/new")
            self.assertEqual(r.status, 200, lang)
            self.assertIn('lang="%s"' % lang, r.text)
        # logout / login
        self.c.post("/logout", {})
        self.assertEqual(self.c.get("/contacts").status, 303)
        r = self.c.post("/login", {"email": "anna@deark.example", "password": "fout"}, csrf=False)
        self.assertEqual(r.status, 200)
        r = self.c.post("/login", {"email": "ANNA@deark.example", "password": "lang genoeg wachtwoord", "next": "//evil.example"}, csrf=False)
        self.assertEqual((r.status, r.header("Location")), (303, "/"))

    def test_csrf_and_roles(self):
        setup_admin(self.c)
        r = self.c.request("POST", "/lists/new", data={"name": "X"})
        self.assertEqual(r.status, 403)
        r = self.c.post_json("/upload", {"data": base64.b64encode(b"<svg onload=alert(1)>").decode()})
        self.assertEqual(r.status, 400)
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 20).decode()
        r = self.c.post_json("/upload", {"data": "data:image/png;base64," + png})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.c.get(r.json()["url"]).status, 200)
        # an editor cannot reach settings
        self.c.get("/settings/team")
        self.c.post("/settings/team", {"action": "add", "email": "ed@deark.example", "name": "Ed", "role": "editor", "password": "nog een lang wachtwoord"})
        ed = Client(self.app)
        ed.post("/login", {"email": "ed@deark.example", "password": "nog een lang wachtwoord"}, csrf=False)
        self.assertEqual(ed.get("/contacts").status, 200)
        self.assertEqual(ed.get("/settings").status, 403)
        self.assertNotIn('href="/settings"', ed.get("/").text)

    def test_contacts_crud_and_xss(self):
        setup_admin(self.c)
        lid = self.new_list("Gemeente")
        self.c.get("/contacts/new")
        r = self.c.post("/contacts/new", {"email": "x@deark.example", "first_name": "<script>alert(1)</script>", "lists": [str(lid)], "tags": "jeugd, koor", "consent": ""})
        self.assertEqual(r.status, 200)  # consent missing → form again
        self.assertIn('value="x@deark.example"', r.text)
        r = self.c.post("/contacts/new", {"email": "x@deark.example", "first_name": "<script>alert(1)</script>", "lists": [str(lid)], "tags": "jeugd, koor", "consent": "Kaartje"})
        self.assertEqual(r.status, 303)
        page = self.c.get("/contacts").text
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        cid = db.val("SELECT id FROM contacts")
        self.assertEqual(self.c.get("/contacts?list=%d&tag=1&status=active&q=x" % lid).status, 200)
        data = json.loads(self.c.get("/contacts/%d/data.json" % cid).text)
        self.assertEqual(data["tags"], ["jeugd", "koor"])
        self.assertEqual(data["consent_text"], "Kaartje")
        self.c.get("/contacts/%d" % cid)
        r = self.c.post("/contacts/%d" % cid, {"email": "x@deark.example", "first_name": "X", "status": "active", "lists": [], "tags": ""})
        self.assertEqual(r.status, 303)
        self.assertEqual(db.val("SELECT status FROM list_members WHERE contact_id = ?", (cid,)), "unsubscribed")
        csv = self.c.get("/contacts/export.csv").text
        self.assertIn("x@deark.example", csv)
        self.c.post("/contacts/%d/delete" % cid, {})
        self.assertEqual(db.val("SELECT COUNT(*) FROM contacts"), 0)

    # ------------------------------------------------------------------ the full journey
    def test_signup_campaign_tracking_unsubscribe(self):
        setup_admin(self.c)
        db.set_settings({"content_langs": "nl,en,ar"})
        news = self.new_list("Nieuwsbrief-gemeente", double=True)
        prayer = self.new_list("Gebedsbrief")
        # import
        self.c.get("/contacts/import")
        csv = "email;voornaam;taal;labels\nnl@x.example;Kees;nl;kerkenraad\nen@x.example;John;en;\nar@x.example;Amal;ar;\nbounce@x.example;B;nl;\n"
        r = self.c.post("/contacts/import", {"csv": csv, "list_id": str(prayer), "tags": "", "update": "1", "confirm_consent": "1", "consent_note": "kaartjes"})
        self.assertEqual(r.status, 303)
        self.assertEqual(db.val("SELECT COUNT(*) FROM list_members WHERE list_id = ? AND status = 'subscribed'", (prayer,)), 4)
        # form with two lists → double opt-in for one
        self.c.get("/forms/new")
        r = self.c.post("/forms/new", {"name": "Website", "lists": [str(news), str(prayer)], "lang": "nl", "title": "Blijf op de hoogte",
                                       "intro": "", "ask_name": "1", "consent_text": "Ja graag", "success_text": ""})
        fid = int(r.header("Location").rsplit("/", 1)[1])
        pid = db.val("SELECT public_id FROM forms WHERE id = ?", (fid,))
        form_page = self.c.get("/forms/%d" % fid).text
        self.assertIn("/f/%s" % pid, form_page)
        visitor = Client(self.app, ip="10.0.0.9")
        r = visitor.get("/f/" + pid)
        self.assertEqual(r.status, 200)
        self.assertIn("Gebedsbrief", r.text)
        r = visitor.post("/f/" + pid, {"email": "nieuw@x.example", "first_name": "Nina", "lists": [str(news)], "consent": "1"}, csrf=False)
        self.assertEqual(r.status, 200)
        self.assertIn("Kijk in je inbox", r.text)
        mails = outbox()
        self.assertEqual(len(mails), 1)
        self.assertIn("Bevestig je aanmelding bij Gemeente De Ark", mails[0]["Subject"])
        link = re.search(r"http://localhost:8080(/confirm/[\w-]+)", text_of(mails[0])).group(1)
        self.assertEqual(db.val("SELECT status FROM list_members WHERE list_id = ? AND contact_id = (SELECT id FROM contacts WHERE email='nieuw@x.example')", (news,)), "pending")
        r = visitor.get(link)
        self.assertIn("bevestigd", r.text)
        self.assertEqual(db.val("SELECT status FROM list_members WHERE list_id = ? AND contact_id = (SELECT id FROM contacts WHERE email='nieuw@x.example')", (news,)), "subscribed")
        # spam protections
        self.assertIn("Kijk in je inbox", visitor.post("/f/" + pid, {"email": "bot@x.example", "website": "spam", "lists": [str(news)], "consent": "1"}, csrf=False).text)
        self.assertIsNone(db.val("SELECT id FROM contacts WHERE email = 'bot@x.example'"))
        self.assertEqual(visitor.post("/f/" + pid, {"email": "nope", "consent": "1", "lists": [str(news)]}, csrf=False).status, 400)
        self.assertEqual(visitor.post("/f/" + pid, {"email": "a@x.example", "lists": [str(news)]}, csrf=False).status, 400)  # no consent
        self.assertEqual(visitor.post("/f/" + pid, {"email": "a@x.example", "consent": "1"}, csrf=False).status, 400)  # no list chosen
        clear_outbox()

        # campaign: newsletter template, Dutch + English
        self.c.get("/campaigns/new")
        r = self.c.post("/campaigns/new", {"name": "November", "template": "newsletter", "lang": "nl"})
        cid = int(r.header("Location").split("/")[2])
        r = self.c.get("/campaigns/%d/edit" % cid)
        self.assertEqual(r.status, 200)
        data = json.loads(re.search(r'<script type="application/json" id="editor-data">(.*?)</script>', r.text, re.S).group(1))
        self.assertIn("nl", data["variants"])
        self.assertEqual(data["variants"]["nl"]["subject"], "Nieuws uit de gemeente")
        nl_blocks = [{"type": "heading", "text": "Hallo {{first_name|vriend}}", "level": "1"},
                     {"type": "text", "text": "Lees [meer](https://deark.example/nieuws) en [mail](mailto:info@deark.example)"},
                     {"type": "event", "title": "Kerstnachtdienst", "date": "2026-12-24", "time": "22:00", "end_time": "23:00", "location": "Kerk", "description": ""},
                     {"type": "button", "label": "Kijk", "url": "javascript:alert(1)"}, {"type": "evil", "x": 1}]
        en_blocks = [{"type": "heading", "text": "Hello {{first_name|friend}}", "level": "1"}, {"type": "text", "text": "Read [more](https://deark.example/news)"}]
        r = self.c.post_json("/campaigns/%d/content" % cid, {"default_lang": "nl", "variants": {
            "nl": {"subject": "Nieuws voor {{first_name}}", "preheader": "pre", "blocks": nl_blocks},
            "en": {"subject": "News for {{first_name}}", "preheader": "", "blocks": en_blocks},
            "xx": {"subject": "ignored"}}})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(db.val("SELECT COUNT(*) FROM variants WHERE campaign_id = ?", (cid,)), 2)
        stored = json.loads(db.val("SELECT blocks FROM variants WHERE campaign_id = ? AND lang = 'nl'", (cid,)))
        self.assertEqual(len(stored), 4)  # unknown block type removed
        r = self.c.post_json("/campaigns/%d/preview" % cid, {"lang": "en", "subject": "S", "blocks": en_blocks})
        self.assertIn("Hello Anna", r.json()["html"])
        # settings: both lists, but only tag "kerkenraad"? no: whole lists
        self.c.get("/campaigns/%d/settings" % cid)
        r = self.c.post("/campaigns/%d/settings" % cid, {"name": "November", "lists": [str(news), str(prayer)], "track_opens": "1", "track_clicks": "1",
                                                          "archive": "1", "accent": "#7a1f2b", "background": "#ffffff", "font": "serif"})
        self.assertEqual(r.status, 303)
        page = self.c.get("/campaigns/%d/send" % cid).text
        self.assertIn("5 mensen", page)  # 4 imported + Nina
        # test email
        r = self.c.post("/campaigns/%d/test" % cid, {"to": "anna@deark.example"})
        self.assertEqual(r.status, 303)
        tests = outbox()
        self.assertEqual(sorted(m["Subject"] for m in tests), ["[TEST EN] News for Anna", "[TEST NL] Nieuws voor Anna"])
        self.assertIsNone(tests[0]["List-Unsubscribe"])
        clear_outbox()
        # send now
        r = self.c.post("/campaigns/%d/send" % cid, {"when": "now"})
        self.assertEqual(r.status, 303)
        self.assertEqual(db.val("SELECT status FROM campaigns WHERE id = ?", (cid,)), "sending")
        self.assertEqual(self.c.get("/campaigns/%d/report" % cid).status, 200)
        self.tick()
        self.assertEqual(db.val("SELECT status FROM campaigns WHERE id = ?", (cid,)), "sent")
        mails = {m["To"]: m for m in outbox()}
        self.assertEqual(set(mails), {"nl@x.example", "en@x.example", "ar@x.example", "bounce@x.example", "nieuw@x.example"})
        self.assertEqual(mails["nl@x.example"]["Subject"], "Nieuws voor Kees")
        self.assertEqual(mails["en@x.example"]["Subject"], "News for John")
        self.assertEqual(mails["ar@x.example"]["Subject"], "Nieuws voor Amal")  # no Arabic version → default language
        m = mails["nl@x.example"]
        self.assertEqual(m["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertEqual(m["Content-Language"], "nl")
        h = html_of(m)
        self.assertIn("Hallo Kees", h)
        self.assertNotIn("javascript:", h)
        self.assertIn("mailto:info@deark.example", h)  # mailto links are not tracked
        self.assertIn("#7a1f2b", h)
        self.assertIn("Kerstnachtdienst", text_of(m))
        token = re.search(r"/o/([0-9a-f]+)\.gif", h).group(1)
        click = re.search(r"http://localhost:8080(/c/[0-9a-f]+/\d+)", h).group(1)
        # open + click
        anon = Client(self.app)
        r = anon.get("/o/%s.gif" % token)
        self.assertEqual((r.status, r.header("Content-Type")), (200, "image/gif"))
        r = anon.get(click)
        self.assertEqual((r.status, r.header("Location")), (302, "https://deark.example/nieuws"))
        other = db.run("INSERT INTO links(campaign_id, url) VALUES (?, 'https://elsewhere.example')", (cid,)).lastrowid
        db.commit()
        self.assertEqual(anon.get("/c/%s/%d" % (token, other)).status, 302)  # same campaign: fine
        self.assertEqual(anon.get("/c/%s/99999" % token).status, 404)  # unknown link: no open redirect
        rep = self.c.get("/campaigns/%d/report" % cid).text
        self.assertIn("https://deark.example/nieuws", rep)
        self.assertIn("Per taal", rep)
        # web version, calendar, archive
        r = anon.get("/v/" + token)
        self.assertIn("Hallo Kees", r.text)
        self.assertIn("default-src 'none'", r.header("Content-Security-Policy"))
        pubid = db.val("SELECT public_id FROM campaigns WHERE id = ?", (cid,))
        ics = anon.get("/ics/%s/nl/2.ics" % pubid)
        self.assertEqual(ics.status, 200)
        self.assertIn("SUMMARY:Kerstnachtdienst", ics.text)
        self.assertIn("DTSTART:20261224T210000Z", ics.text)
        self.assertEqual(anon.get("/ics/%s/nl/0.ics" % pubid).status, 404)
        self.assertIn("/archive/" + pubid, anon.get("/archive").text)
        arch = anon.get("/archive/" + pubid).text
        self.assertIn("Hallo vriend", arch)
        self.assertNotIn("/u/", arch)
        # editing a sent campaign is refused
        self.assertEqual(self.c.post_json("/campaigns/%d/content" % cid, {"variants": {"nl": {"subject": "x", "blocks": []}}}).status, 409)

        # unsubscribe: GET only asks, POST (one-click) does it
        unsub = urlparse(m["List-Unsubscribe"].strip("<>")).path
        r = anon.get(unsub)
        self.assertIn("Ja, meld mij af", r.text)
        self.assertEqual(db.val("SELECT status FROM contacts WHERE email = 'nl@x.example'"), "active")
        r = anon.request("POST", unsub, data={"List-Unsubscribe": "One-Click"})
        self.assertEqual((r.status, r.text), (200, "OK"))
        self.assertEqual(db.val("SELECT status FROM contacts WHERE email = 'nl@x.example'"), "unsubscribed")
        self.assertIn("afgemeld", anon.get(unsub).text)
        # preferences: come back, but only for the prayer letter, in English
        ctoken = db.val("SELECT token FROM contacts WHERE email = 'nl@x.example'")
        r = anon.get("/p/" + ctoken)
        self.assertEqual(r.status, 200)
        r = anon.post("/p/" + ctoken, {"first_name": "Kees", "last_name": "", "lang": "en", "lists": [str(prayer)]}, csrf=False)
        self.assertIn("Your preferences have been saved", r.text)
        self.assertEqual(db.val("SELECT status FROM contacts WHERE email = 'nl@x.example'"), "active")
        self.assertEqual(db.val("SELECT lang FROM contacts WHERE email = 'nl@x.example'"), "en")
        self.assertEqual(anon.get("/u/doesnotexist").status, 404)

        # duplicate and send to the prayer list only; the duplicate keeps both languages
        r = self.c.post("/campaigns/%d/duplicate" % cid, {})
        cid2 = int(r.header("Location").split("/")[2])
        self.c.post("/campaigns/%d/settings" % cid2, {"name": "Kopie", "lists": [str(news)], "track_opens": "1", "track_clicks": "1"})
        clear_outbox()
        self.c.post("/campaigns/%d/send" % cid2, {"when": "now"})
        self.tick()
        self.assertEqual([m["To"] for m in outbox()], ["nieuw@x.example"])

    def test_smtp_bounce_and_schedule(self):
        setup_admin(self.c)
        smtp = FakeSMTP()
        try:
            db.set_settings({"transport": "smtp", "smtp_host": "127.0.0.1", "smtp_port": str(smtp.port), "smtp_security": "none", "smtp_user": ""})
            db.commit()
            self.c.get("/settings/sending")
            r = self.c.post("/settings/sending", {"action": "test", "from_email": "anna@deark.example", "transport": "smtp", "smtp_host": "127.0.0.1",
                                                  "smtp_port": str(smtp.port), "smtp_security": "none", "rate_per_minute": "1000"})
            self.assertIn("werkt", self.c.get("/settings/sending").text)
            lid = self.new_list("L")
            from koinonia import audience
            audience.import_rows([{"email": "ok@x.example"}, {"email": "bounce@x.example"}], lid)
            db.commit()
            self.c.post("/campaigns/new", {"name": "Plan", "template": "welcome", "lang": "nl"})
            cid = db.val("SELECT MAX(id) FROM campaigns")
            self.c.post("/campaigns/%d/settings" % cid, {"name": "Plan", "lists": [str(lid)], "track_opens": "1", "track_clicks": "1"})
            r = self.c.post("/campaigns/%d/send" % cid, {"when": "later", "at": "2020-01-01T10:00"})
            self.assertIn("/send", r.header("Location"))  # in the past → refused
            r = self.c.post("/campaigns/%d/send" % cid, {"when": "later", "at": "2099-01-01T10:00"})
            self.assertEqual(db.val("SELECT status FROM campaigns WHERE id = ?", (cid,)), "scheduled")
            self.assertEqual(db.val("SELECT scheduled_at FROM campaigns WHERE id = ?", (cid,)), "2099-01-01 09:00:00")
            self.tick()
            self.assertEqual(db.val("SELECT COUNT(*) FROM deliveries"), 0)
            db.run("UPDATE campaigns SET scheduled_at = '2000-01-01 00:00:00' WHERE id = ?", (cid,))
            db.commit()
            self.tick()
            self.assertEqual(db.val("SELECT status FROM campaigns WHERE id = ?", (cid,)), "sent")
            self.assertEqual(len(smtp.messages), 1)
            self.assertIn("ok@x.example", smtp.messages[0][0][0])
            self.assertEqual(db.val("SELECT status FROM contacts WHERE email = 'bounce@x.example'"), "bounced")
            self.assertIn("550", db.val("SELECT error FROM deliveries WHERE status = 'failed'"))
            self.assertIn("550", self.c.get("/campaigns/%d/report" % cid).text)
        finally:
            smtp.close()

    def test_smtp_down_keeps_queue(self):
        setup_admin(self.c)
        db.set_settings({"transport": "smtp", "smtp_host": "127.0.0.1", "smtp_port": "1", "smtp_security": "none"})
        lid = self.new_list("L")
        from koinonia import audience
        audience.import_rows([{"email": "ok@x.example"}], lid)
        db.commit()
        self.c.post("/campaigns/new", {"name": "X", "template": "welcome", "lang": "nl"})
        cid = db.val("SELECT MAX(id) FROM campaigns")
        self.c.post("/campaigns/%d/settings" % cid, {"name": "X", "lists": [str(lid)]})
        self.c.post("/campaigns/%d/send" % cid, {"when": "now"})
        w = self.tick()
        self.assertEqual(db.val("SELECT status FROM deliveries"), "queued")
        self.assertEqual(db.val("SELECT attempts FROM deliveries"), 1)
        self.assertGreater(w.pause_until, 0)
        self.assertEqual(db.val("SELECT status FROM campaigns WHERE id = ?", (cid,)), "sending")

    def test_automation_welcome_series(self):
        setup_admin(self.c)
        lid = self.new_list("Nieuwe bezoekers")
        self.c.get("/automations/new")
        r = self.c.post("/automations/new", {"name": "Welkom", "list_id": str(lid)})
        aid = int(r.header("Location").split("/")[2])
        page = self.c.get("/automations/%d" % aid).text
        step1 = db.one("SELECT * FROM automation_steps WHERE automation_id = ?", (aid,))
        self.assertEqual(self.c.get("/campaigns/%d/edit" % step1["campaign_id"]).status, 200)
        self.assertEqual(self.c.get("/campaigns/%d/send" % step1["campaign_id"]).status, 200)
        r = self.c.post("/automations/%d" % aid, {"action": "add"})
        step2 = db.one("SELECT * FROM automation_steps WHERE automation_id = ? AND position = 1", (aid,))
        self.c.post_json("/campaigns/%d/content" % step2["campaign_id"], {"variants": {"nl": {"subject": "Koffie?", "blocks": [{"type": "text", "text": "Kom je koffie drinken?"}]}}})
        self.c.get("/automations/%d" % aid)
        self.c.post("/automations/%d" % aid, {"action": "save", "name": "Welkom", "list_id": str(lid), "active": "1",
                                              "delay_%d" % step1["id"]: "0", "delay_%d" % step2["id"]: "3"})
        # someone joins via a form (single opt-in)
        self.c.post("/forms/new", {"name": "Bezoekers", "lists": [str(lid)], "lang": "nl", "title": "Welkom", "consent_text": ""})
        pid = db.val("SELECT public_id FROM forms")
        Client(self.app, ip="10.1.1.1").post("/f/" + pid, {"email": "gast@x.example", "first_name": "Gerrit"}, csrf=False)
        self.assertEqual(db.val("SELECT COUNT(*) FROM enrollments"), 1)
        self.tick(2)
        mails = outbox()
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["Subject"], "Welkom!")
        self.assertIn("Gerrit", html_of(mails[0]))
        self.assertEqual(db.val("SELECT next_position FROM enrollments"), 1)
        # fast-forward three days
        db.run("UPDATE enrollments SET next_at = '2000-01-01 00:00:00'")
        db.commit()
        self.tick(2)
        self.assertEqual(sorted(m["Subject"] for m in outbox()), ["Koffie?", "Welkom!"])
        self.assertEqual(db.val("SELECT done FROM enrollments"), 1)
        self.assertIn("1×", self.c.get("/automations/%d" % aid).text)
        # remove a step, then delete the automation
        self.c.post("/automations/%d" % aid, {"action": "remove-%d" % step2["id"]})
        self.assertEqual(db.val("SELECT COUNT(*) FROM automation_steps"), 1)
        self.c.post("/automations/%d" % aid, {"action": "delete"})
        self.assertEqual(db.val("SELECT COUNT(*) FROM automations"), 0)
        self.assertEqual(db.val("SELECT COUNT(*) FROM campaigns"), 0)

    def test_preview_of_unsaved_language_uses_that_language(self):
        setup_admin(self.c)
        self.c.post("/campaigns/new", {"name": "X", "template": "blank", "lang": "nl"})
        cid = db.val("SELECT MAX(id) FROM campaigns")
        self.c.get("/campaigns/%d/edit" % cid)
        r = self.c.post_json("/campaigns/%d/preview" % cid, {"lang": "en", "subject": "S", "blocks": [{"type": "event", "title": "Service", "date": "2026-12-24"}]})
        html = r.json()["html"]
        self.assertIn('lang="en"', html)
        self.assertIn("24 December 2026", html)
        self.assertIn("Unsubscribe", html)

    def test_retention_anonymises(self):
        setup_admin(self.c)
        lid = self.new_list("L")
        from koinonia import audience
        audience.import_rows([{"email": "a@x.example"}], lid)
        db.commit()
        self.c.post("/campaigns/new", {"name": "X", "template": "welcome", "lang": "nl"})
        cid = db.val("SELECT MAX(id) FROM campaigns")
        self.c.post("/campaigns/%d/settings" % cid, {"name": "X", "lists": [str(lid)], "track_opens": "1"})
        self.c.post("/campaigns/%d/send" % cid, {"when": "now"})
        w = self.tick()
        db.run("UPDATE deliveries SET sent_at = '2000-01-01 00:00:00', opened_at = '2000-01-01 00:00:00'")
        db.commit()
        w.cleanup()
        self.assertIsNone(db.val("SELECT contact_id FROM deliveries"))
        self.assertIn("100%", self.c.get("/campaigns/%d/report" % cid).text)


if __name__ == "__main__":
    unittest.main()
