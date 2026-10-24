"""Contacts, lists, import/export and sign-up forms."""
import json

from . import audience, db, i18n, security, ui
from .app import router
from .ui import T, checkbox, checks, field, inp, select, textarea
from .web import HTTPError, Response, e, redirect, url

PER_PAGE = 50
STATUSES = ["active", "unsubscribed", "bounced"]


def _lists():
    return db.q("SELECT * FROM lists ORDER BY name")


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _filters(req):
    f = {k: req.get(k).strip() for k in ("q", "list", "tag", "status", "lang")}
    where, args = ["1"], []
    if f["q"]:
        where.append("(c.email LIKE ? OR c.first_name LIKE ? OR c.last_name LIKE ? OR (c.first_name || ' ' || c.last_name) LIKE ?)")
        args += ["%" + f["q"] + "%"] * 4
    if f["list"].isdigit():
        where.append("EXISTS (SELECT 1 FROM list_members m WHERE m.contact_id = c.id AND m.list_id = ? AND m.status = 'subscribed')")
        args.append(int(f["list"]))
    if f["tag"].isdigit():
        where.append("EXISTS (SELECT 1 FROM contact_tags ct WHERE ct.contact_id = c.id AND ct.tag_id = ?)")
        args.append(int(f["tag"]))
    if f["status"] in STATUSES:
        where.append("c.status = ?")
        args.append(f["status"])
    if f["lang"]:
        where.append("c.lang = ?")
        args.append(f["lang"])
    return f, " AND ".join(where), args


# ---------------------------------------------------------------- contacts
def contacts(req):
    f, where, args = _filters(req)
    page = max(1, _int(req.get("page"), 1))
    total = db.val("SELECT COUNT(*) FROM contacts c WHERE " + where, args, 0)
    rows = db.q("SELECT c.* FROM contacts c WHERE %s ORDER BY c.created_at DESC, c.id DESC LIMIT ? OFFSET ?" % where, args + [PER_PAGE, (page - 1) * PER_PAGE])
    lists, tags = _lists(), db.q("SELECT * FROM tags ORDER BY name")
    filters = ('<form method="get" class="filters">%s%s%s%s%s<button class="btn">%s</button>%s</form>' % (
        inp("q", f["q"], "search", placeholder=T(req, "contacts.search"), aria_label=T(req, "contacts.search")),
        select("list", [("", T(req, "contacts.all_lists"))] + [(l["id"], l["name"]) for l in lists], f["list"], aria_label=T(req, "nav.lists")),
        select("tag", [("", T(req, "contacts.all_tags"))] + [(t["id"], t["name"]) for t in tags], f["tag"], aria_label=T(req, "common.tags")) if tags else "",
        select("status", [("", T(req, "contacts.all_statuses"))] + [(s, T(req, "status." + s)) for s in STATUSES], f["status"], aria_label=T(req, "common.status")),
        select("lang", [("", T(req, "contacts.all_langs"))] + ui.lang_options(), f["lang"], aria_label=T(req, "common.language")),
        e(T(req, "common.filter")),
        ' <a class="btn btn-ghost" href="/contacts">%s</a>' % e(T(req, "common.reset")) if any(f.values()) else ""))
    if rows:
        trs = "".join('<tr><td class="sel"><input type="checkbox" name="ids" value="%d" form="bulk" aria-label="%s"></td>'
                      '<td><a href="/contacts/%d"><strong>%s</strong></a><br><small class="muted">%s</small></td>'
                      '<td>%s</td><td>%s</td><td><small>%s</small></td><td><small class="muted">%s</small></td></tr>' % (
                          r["id"], e(r["email"]), r["id"], e(r["email"]), e((r["first_name"] + " " + r["last_name"]).strip()),
                          e(r["lang"].upper()), ui.badge(req, r["status"]), e(", ".join(audience.contact_tags(r["id"]))), ui.local_time(r["created_at"], req, False))
                      for r in rows)
        table = '<table class="table"><thead><tr><th class="sel"><input type="checkbox" data-check-all="ids" aria-label="%s"></th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table>' % (
            e(T(req, "common.select_all")), e(T(req, "common.contact")), e(T(req, "common.language")), e(T(req, "common.status")),
            e(T(req, "common.tags")), e(T(req, "common.added")), trs)
        bulk = ('<form method="post" action="/contacts/bulk" id="bulk" class="bulk">%s<span class="muted">%s</span>%s%s%s<button class="btn" data-confirm-if="delete" data-confirm="%s">%s</button></form>' % (
            ui.csrf(req), e(T(req, "contacts.with_selected")),
            select("action", [("tag", T(req, "contacts.bulk_tag")), ("list", T(req, "contacts.bulk_list")), ("unlist", T(req, "contacts.bulk_unlist")), ("delete", T(req, "contacts.bulk_delete"))], "", aria_label=T(req, "common.action")),
            inp("tag", "", placeholder=T(req, "common.tag"), aria_label=T(req, "common.tag")),
            select("list_id", [(l["id"], l["name"]) for l in lists], "", aria_label=T(req, "common.list")) if lists else "",
            e(T(req, "contacts.confirm_bulk_delete")), e(T(req, "common.apply"))))
        body = filters + '<div class="card flush">%s<p class="count">%s</p>%s</div>%s' % (bulk, e(T(req, "contacts.count", n=total)), table,
                                                                                     ui.pager(req, total, page, PER_PAGE, url("/contacts", **f)))
    else:
        body = filters + ui.empty(req, T(req, "contacts.empty"), '<a class="btn btn-primary" href="/contacts/import">%s</a>' % e(T(req, "contacts.import")))
    actions = '<a class="btn btn-ghost" href="%s">%s</a><a class="btn" href="/contacts/import">%s</a><a class="btn btn-primary" href="/contacts/new">%s</a>' % (
        e(url("/contacts/export.csv", **f)), e(T(req, "contacts.export")), e(T(req, "contacts.import")), e(T(req, "contacts.new")))
    return ui.page(req, T(req, "nav.contacts"), body, "contacts", actions)


def bulk(req):
    ids = [int(x) for x in req.getlist("ids") if x.isdigit()]
    action = req.get("action")
    if not ids:
        ui.flash(req, T(req, "contacts.none_selected"), "error")
        return redirect("/contacts")
    if action == "delete":
        db.run("DELETE FROM contacts WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    elif action == "tag" and req.get("tag").strip():
        for i in ids:
            audience.add_tags(i, audience.split_tags(req.get("tag")))
    elif action in ("list", "unlist") and req.get("list_id").isdigit():
        lid = int(req.get("list_id"))
        for i in ids:
            if action == "list":
                if db.val("SELECT status FROM contacts WHERE id = ?", (i,)) == "active":
                    audience.set_membership(i, lid, "subscribed")
            else:
                db.run("UPDATE list_members SET status = 'unsubscribed', updated_at = datetime('now') WHERE list_id = ? AND contact_id = ?", (lid, i))
    else:
        ui.flash(req, T(req, "contacts.bulk_missing"), "error")
        return redirect(req.header("Referer") or "/contacts")
    ui.flash(req, T(req, "contacts.bulk_done", n=len(ids)))
    return redirect("/contacts")


def _contact_form(req, c, member_ids, tags, error="", new=False):
    lists = _lists()
    c = c or {}
    status_opts = [(s, T(req, "status." + s)) for s in STATUSES]
    parts = [
        '<div class="grid2">%s%s</div>' % (field(T(req, "common.first_name"), inp("first_name", c.get("first_name", ""))),
                                           field(T(req, "common.last_name"), inp("last_name", c.get("last_name", "")))),
        '<div class="grid2">%s%s</div>' % (field(T(req, "common.email"), inp("email", c.get("email", ""), "email", required=True)),
                                           field(T(req, "common.language"), select("lang", [("", "—")] + ui.lang_options(), c.get("lang", "")))),
        field(T(req, "nav.lists"), checks("lists", [(l["id"], l["name"]) for l in lists], member_ids) if lists else '<p class="muted">%s</p>' % e(T(req, "lists.empty"))),
        field(T(req, "common.tags"), inp("tags", ", ".join(tags), placeholder=T(req, "contacts.tags_hint")), T(req, "contacts.tags_help")),
        field(T(req, "contacts.notes"), textarea("notes", c.get("notes", ""), 3)),
    ]
    if new:
        parts.append(field(T(req, "contacts.consent"), inp("consent", "", required=True, placeholder=T(req, "contacts.consent_placeholder")), T(req, "contacts.consent_help")))
    else:
        parts.append(field(T(req, "common.status"), select("status", status_opts, c.get("status"))))
    err = '<div class="flash flash-error">%s</div>' % e(error) if error else ""
    return '%s<form method="post" class="card stack">%s%s<div class="form-actions"><button class="btn btn-primary">%s</button><a class="btn btn-ghost" href="/contacts">%s</a></div></form>' % (
        err, ui.csrf(req), "".join(parts), e(T(req, "common.save")), e(T(req, "common.cancel")))


def _save_contact(req, cid=None):
    email = req.get("email").strip()
    if not security.valid_email(email):
        return T(req, "err.email")
    other = db.val("SELECT id FROM contacts WHERE email = ?", (email,))
    if other and other != cid:
        return T(req, "contacts.duplicate")
    lang = req.get("lang") if req.get("lang") in i18n.LANG_NAMES else ""
    first, last, notes = req.get("first_name").strip()[:120], req.get("last_name").strip()[:120], req.get("notes")[:2000]
    if cid is None:
        consent = req.get("consent").strip()
        if not consent:
            return T(req, "contacts.consent_required")
        cid, _ = audience.upsert(email, first, last, lang, source="admin:%s" % req.user["email"])
        db.run("UPDATE contacts SET notes = ? WHERE id = ?", (notes, cid))
        audience.record_consent(cid, consent)
        audience.log(cid, "created", req.user["email"])
    else:
        status = req.get("status") if req.get("status") in STATUSES else "active"
        old = db.val("SELECT status FROM contacts WHERE id = ?", (cid,))
        db.run("UPDATE contacts SET email = ?, first_name = ?, last_name = ?, lang = ?, notes = ?, status = ?, updated_at = datetime('now') WHERE id = ?",
               (email, first, last, lang, notes, status, cid))
        if old != status:
            audience.log(cid, "status:" + status, req.user["email"])
            if status != "active":
                db.run("UPDATE list_members SET status = 'unsubscribed', updated_at = datetime('now') WHERE contact_id = ?", (cid,))
    wanted = {int(x) for x in req.getlist("lists") if x.isdigit()}
    active = db.val("SELECT status FROM contacts WHERE id = ?", (cid,)) == "active"
    for l in _lists():
        current = db.val("SELECT status FROM list_members WHERE list_id = ? AND contact_id = ?", (l["id"], cid))
        if l["id"] in wanted and active and current != "subscribed":
            audience.set_membership(cid, l["id"], "subscribed")
        elif l["id"] not in wanted and current in ("subscribed", "pending"):
            db.run("UPDATE list_members SET status = 'unsubscribed', updated_at = datetime('now') WHERE list_id = ? AND contact_id = ?", (l["id"], cid))
    audience.set_tags(cid, audience.split_tags(req.get("tags")))
    return cid


def contact_new(req):
    if req.method == "POST":
        res = _save_contact(req)
        if isinstance(res, int):
            ui.flash(req, T(req, "common.saved"))
            return redirect("/contacts/%d" % res)
        f = {k: req.get(k) for k in ("email", "first_name", "last_name", "lang", "notes")}
        return ui.page(req, T(req, "contacts.new"), _contact_form(req, f, req.getlist("lists"), audience.split_tags(req.get("tags")), res, new=True), "contacts")
    return ui.page(req, T(req, "contacts.new"), _contact_form(req, None, [], [], new=True), "contacts")


def contact_edit(req, cid):
    c = db.one("SELECT * FROM contacts WHERE id = ?", (_int(cid),))
    if not c:
        raise HTTPError(404)
    error = ""
    if req.method == "POST":
        res = _save_contact(req, c["id"])
        if isinstance(res, int):
            ui.flash(req, T(req, "common.saved"))
            return redirect("/contacts/%d" % c["id"])
        error = res
    member_ids = [r["list_id"] for r in db.q("SELECT list_id FROM list_members WHERE contact_id = ? AND status IN ('subscribed', 'pending')", (c["id"],))]
    pending = [r["name"] for r in db.q("SELECT l.name FROM list_members m JOIN lists l ON l.id = m.list_id WHERE m.contact_id = ? AND m.status = 'pending'", (c["id"],))]
    form = _contact_form(req, dict(c), member_ids, audience.contact_tags(c["id"]), error)
    events = db.q("SELECT * FROM events WHERE contact_id = ? ORDER BY id DESC LIMIT 30", (c["id"],))
    timeline = "".join('<li><span>%s</span> %s <small class="muted">%s</small></li>' % (
        e(T(req, "event." + ev["type"].split(":")[0])), e(ev["detail"] if not ev["type"].startswith("status:") else T(req, "status." + ev["type"][7:])),
        ui.local_time(ev["at"], req)) for ev in events) or '<li class="muted">—</li>'
    consent = '<dl class="meta"><dt>%s</dt><dd>%s</dd><dt>%s</dt><dd>%s</dd><dt>%s</dt><dd>%s</dd>%s</dl>' % (
        e(T(req, "contacts.consent")), e(c["consent_text"] or "—"), e(T(req, "contacts.consent_at")), ui.local_time(c["consent_at"], req) or "—",
        e(T(req, "contacts.source")), e(c["source"] or "—"),
        '<dt>%s</dt><dd>%s</dd>' % (e(T(req, "contacts.pending")), e(", ".join(pending))) if pending else "")
    side = ('<aside class="stack"><section class="card"><h2>%s</h2>%s</section><section class="card"><h2>%s</h2><ul class="timeline">%s</ul></section>'
            '<section class="card"><h2>%s</h2><p class="muted">%s</p><a class="btn" href="/contacts/%d/data.json">%s</a>'
            '<form method="post" action="/contacts/%d/delete">%s<button class="btn btn-danger" data-confirm="%s">%s</button></form></section></aside>') % (
        e(T(req, "contacts.privacy")), consent, e(T(req, "contacts.activity")), timeline, e(T(req, "contacts.gdpr")), e(T(req, "contacts.gdpr_help")),
        c["id"], e(T(req, "contacts.download_data")), c["id"], ui.csrf(req), e(T(req, "contacts.confirm_delete")), e(T(req, "contacts.delete")))
    return ui.page(req, c["email"], '<div class="split">%s%s</div>' % (form, side), "contacts")


def contact_data(req, cid):
    data = audience.personal_data(_int(cid))
    if data is None:
        raise HTTPError(404)
    return Response(data, 200, "application/json; charset=utf-8", [("Content-Disposition", 'attachment; filename="contact-%d.json"' % _int(cid))])


def contact_delete(req, cid):
    db.run("DELETE FROM contacts WHERE id = ?", (_int(cid),))
    ui.flash(req, T(req, "contacts.deleted"))
    return redirect("/contacts")


def export(req):
    f, where, args = _filters(req)
    return Response(audience.export_csv(where, args), 200, "text/csv; charset=utf-8",
                    [("Content-Disposition", 'attachment; filename="contacts.csv"')])


def import_(req):
    lists = _lists()
    if req.method == "POST":
        if not req.get("confirm_consent"):
            ui.flash(req, T(req, "import.need_consent"), "error")
            return redirect("/contacts/import")
        rows, unknown = audience.parse_csv(req.get("csv"))
        if not rows:
            ui.flash(req, T(req, "import.no_rows"), "error")
            return redirect("/contacts/import")
        list_id = _int(req.get("list_id")) or None
        stats = audience.import_rows(rows, list_id, audience.split_tags(req.get("tags")), bool(req.get("update")),
                                     req.get("consent_note").strip() or T(req, "import.default_consent"), "import:%s" % req.user["email"])
        ui.flash(req, T(req, "import.done", **stats))
        return redirect("/contacts" + ("?list=%d" % list_id if list_id else ""))
    body = ('<form method="post" class="card stack narrow">%s<p>%s</p>'
            '<label class="drop"><input type="file" accept=".csv,text/csv,text/plain" data-read-into="csv"><span>%s</span></label>%s%s%s%s%s%s'
            '<div class="form-actions"><button class="btn btn-primary">%s</button></div></form>') % (
        ui.csrf(req), e(T(req, "import.intro")), e(T(req, "import.choose_file")),
        field(T(req, "import.paste"), textarea("csv", "", 8, id="csv", placeholder="email,voornaam,achternaam,taal\nmaria@example.org,Maria,de Vries,nl", spellcheck="false")),
        field(T(req, "common.list"), select("list_id", [("", "—")] + [(l["id"], l["name"]) for l in lists], lists[0]["id"] if lists else "")),
        field(T(req, "common.tags"), inp("tags", "", placeholder=T(req, "contacts.tags_hint"))),
        field(T(req, "import.consent_note"), inp("consent_note", "", placeholder=T(req, "import.default_consent"))),
        checkbox("update", True, T(req, "import.update")),
        checkbox("confirm_consent", False, T(req, "import.confirm_consent")),
        e(T(req, "import.submit")))
    return ui.page(req, T(req, "contacts.import"), body + '<p class="muted narrow">%s</p>' % e(T(req, "import.help")), "contacts")


# ---------------------------------------------------------------- lists
def lists(req):
    rows = db.q("""SELECT l.*, (SELECT COUNT(*) FROM list_members m JOIN contacts c ON c.id = m.contact_id WHERE m.list_id = l.id AND m.status = 'subscribed' AND c.status = 'active') AS subs,
                   (SELECT COUNT(*) FROM list_members m WHERE m.list_id = l.id AND m.status = 'pending') AS pending FROM lists l ORDER BY l.name""")
    if rows:
        body = '<div class="cards">%s</div>' % "".join(
            '<article class="card list-card"><h2><a href="/lists/%d">%s</a></h2><p class="muted">%s</p><p class="big">%d <small>%s</small></p>'
            '<p class="muted small">%s%s</p><a href="/contacts?list=%d">%s &rarr;</a></article>' % (
                r["id"], e(r["name"]), e(r["description"]), r["subs"], e(T(req, "lists.subscribers")),
                e(T(req, "lists.double_optin") if r["double_optin"] else T(req, "lists.single_optin")),
                " · " + e(T(req, "lists.pending_n", n=r["pending"])) if r["pending"] else "", r["id"], e(T(req, "lists.view_contacts"))) for r in rows)
    else:
        body = ui.empty(req, T(req, "lists.empty"))
    return ui.page(req, T(req, "nav.lists"), body, "lists", '<a class="btn btn-primary" href="/lists/new">%s</a>' % e(T(req, "lists.new")))


def list_edit(req, lid=None):
    l = db.one("SELECT * FROM lists WHERE id = ?", (_int(lid),)) if lid else None
    if lid and not l:
        raise HTTPError(404)
    if req.method == "POST":
        name = req.get("name").strip()[:120]
        if not name:
            ui.flash(req, T(req, "err.name_required"), "error")
            return redirect(req.path)
        vals = (name, req.get("description").strip()[:500], 1 if req.get("double_optin") else 0)
        if l:
            db.run("UPDATE lists SET name = ?, description = ?, double_optin = ? WHERE id = ?", vals + (l["id"],))
        else:
            db.run("INSERT INTO lists(name, description, double_optin) VALUES (?, ?, ?)", vals)
        ui.flash(req, T(req, "common.saved"))
        return redirect("/lists")
    l = l or {"name": "", "description": "", "double_optin": 1}
    delete = ""
    if lid:
        delete = '<form method="post" action="/lists/%d/delete" class="danger-zone">%s<button class="btn btn-danger" data-confirm="%s">%s</button></form>' % (
            l["id"], ui.csrf(req), e(T(req, "lists.confirm_delete")), e(T(req, "lists.delete")))
    body = '<form method="post" class="card stack narrow">%s%s%s%s<div class="form-actions"><button class="btn btn-primary">%s</button><a class="btn btn-ghost" href="/lists">%s</a></div></form>%s' % (
        ui.csrf(req), field(T(req, "common.name"), inp("name", l["name"], required=True, placeholder=T(req, "lists.name_placeholder"))),
        field(T(req, "common.description"), inp("description", l["description"]), T(req, "lists.description_help")),
        checkbox("double_optin", l["double_optin"], T(req, "lists.double_optin_label")) + '<small class="hint">%s</small>' % e(T(req, "lists.double_optin_help")),
        e(T(req, "common.save")), e(T(req, "common.cancel")), delete)
    return ui.page(req, l["name"] or T(req, "lists.new"), body, "lists")


def list_delete(req, lid):
    db.run("DELETE FROM lists WHERE id = ?", (_int(lid),))
    ui.flash(req, T(req, "lists.deleted"))
    return redirect("/lists")


# ---------------------------------------------------------------- forms
def forms(req):
    rows = db.q("SELECT * FROM forms ORDER BY name")
    base = db.setting("base_url").rstrip("/")
    if rows:
        body = '<div class="card flush"><table class="table"><thead><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table></div>' % (
            e(T(req, "common.name")), e(T(req, "common.language")), e(T(req, "forms.signups")), e(T(req, "forms.public_link")),
            "".join('<tr><td><a href="/forms/%d">%s</a></td><td>%s</td><td class="num">%d</td><td><a href="%s/f/%s" target="_blank" rel="noopener">/f/%s</a></td></tr>' % (
                r["id"], e(r["name"]), e(i18n.LANG_NAMES.get(r["lang"], r["lang"])),
                db.val("SELECT COUNT(*) FROM events WHERE type = 'signup' AND detail = ?", (r["name"],), 0), e(base), e(r["public_id"]), e(r["public_id"])) for r in rows))
    else:
        body = ui.empty(req, T(req, "forms.empty"), '<a class="btn btn-primary" href="/forms/new">%s</a>' % e(T(req, "forms.new")))
    return ui.page(req, T(req, "nav.forms"), body, "forms", '<a class="btn btn-primary" href="/forms/new">%s</a>' % e(T(req, "forms.new")))


def embed_code(req, f):
    base = db.setting("base_url").rstrip("/")
    lang = f["lang"]
    lists = db.q("SELECT id, name FROM lists WHERE id IN (%s)" % ",".join("?" * len(db.jl(f["list_ids"]))), db.jl(f["list_ids"])) if db.jl(f["list_ids"]) else []
    p = lambda k: i18n.t(lang, "pub." + k)
    parts = ['<form action="%s/f/%s" method="post" accept-charset="utf-8" style="max-width:420px;font-family:inherit;">' % (base, f["public_id"])]
    if f["ask_name"]:
        parts.append('  <p><label>%s<br><input name="first_name" autocomplete="given-name" style="width:100%%;padding:8px;"></label></p>' % e(p("first_name")))
    parts.append('  <p><label>%s<br><input name="email" type="email" required autocomplete="email" style="width:100%%;padding:8px;"></label></p>' % e(p("email")))
    if len(lists) > 1:
        parts.append("  <p>%s<br>%s</p>" % (e(p("interests")), "<br>".join('<label><input type="checkbox" name="lists" value="%d" checked> %s</label>' % (l["id"], e(l["name"])) for l in lists)))
    if f["consent_text"]:
        parts.append('  <p><label><input type="checkbox" name="consent" value="1" required> %s</label></p>' % e(f["consent_text"]))
    parts.append('  <div style="position:absolute;left:-9999px;" aria-hidden="true"><input name="website" tabindex="-1" autocomplete="off"></div>')
    parts.append('  <p><button type="submit" style="padding:10px 20px;">%s</button></p>\n</form>' % e(p("subscribe")))
    return "\n".join(parts)


def form_edit(req, fid=None):
    f = db.one("SELECT * FROM forms WHERE id = ?", (_int(fid),)) if fid else None
    if fid and not f:
        raise HTTPError(404)
    all_lists = _lists()
    if req.method == "POST":
        name = req.get("name").strip()[:120]
        list_ids = [int(x) for x in req.getlist("lists") if x.isdigit()]
        if not name or not list_ids:
            ui.flash(req, T(req, "forms.need_name_list"), "error")
            return redirect(req.path)
        lang = req.get("lang") if req.get("lang") in i18n.LANG_NAMES else "nl"
        vals = (name, json.dumps(list_ids), lang, req.get("title").strip()[:200], req.get("intro").strip()[:2000],
                1 if req.get("ask_name") else 0, 1 if req.get("ask_lang") else 0, req.get("consent_text").strip()[:1000], req.get("success_text").strip()[:1000])
        if f:
            db.run("UPDATE forms SET name=?, list_ids=?, lang=?, title=?, intro=?, ask_name=?, ask_lang=?, consent_text=?, success_text=? WHERE id=?", vals + (f["id"],))
            fid = f["id"]
        else:
            fid = db.run("INSERT INTO forms(name, list_ids, lang, title, intro, ask_name, ask_lang, consent_text, success_text, public_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         vals + (security.token(6),)).lastrowid
        ui.flash(req, T(req, "common.saved"))
        return redirect("/forms/%d" % fid)
    lang = db.setting("default_lang") or "nl"
    d = dict(f) if f else {"name": "", "list_ids": "[%d]" % all_lists[0]["id"] if all_lists else "[]", "lang": lang, "title": i18n.t(lang, "pub.form_title"),
                           "intro": "", "ask_name": 1, "ask_lang": 0, "consent_text": i18n.t(lang, "pub.consent_default", org=db.setting("org_name")), "success_text": ""}
    form = '<form method="post" class="card stack">%s%s%s%s%s%s%s%s%s%s<div class="form-actions"><button class="btn btn-primary">%s</button><a class="btn btn-ghost" href="/forms">%s</a></div></form>' % (
        ui.csrf(req), field(T(req, "forms.internal_name"), inp("name", d["name"], required=True)),
        field(T(req, "nav.lists"), checks("lists", [(l["id"], l["name"]) for l in all_lists], db.jl(d["list_ids"])), T(req, "forms.lists_help")),
        field(T(req, "forms.language"), select("lang", ui.lang_options(), d["lang"]), T(req, "forms.language_help")),
        field(T(req, "forms.title"), inp("title", d["title"])),
        field(T(req, "forms.intro"), textarea("intro", d["intro"], 3)),
        checkbox("ask_name", d["ask_name"], T(req, "forms.ask_name")),
        checkbox("ask_lang", d["ask_lang"], T(req, "forms.ask_lang")),
        field(T(req, "forms.consent_text"), textarea("consent_text", d["consent_text"], 2), T(req, "forms.consent_help")),
        field(T(req, "forms.success_text"), textarea("success_text", d["success_text"], 2, placeholder=i18n.t(d["lang"], "pub.check_inbox"))),
        e(T(req, "common.save")), e(T(req, "common.cancel")))
    side = ""
    if f:
        base = db.setting("base_url").rstrip("/")
        side = ('<aside class="stack"><section class="card"><h2>%s</h2><p><a href="%s/f/%s" target="_blank" rel="noopener" class="break">%s/f/%s</a></p>'
                '<p class="muted small">%s</p></section><section class="card"><h2>%s</h2><p class="muted small">%s</p>'
                '<textarea readonly rows="12" class="code" id="embed">%s</textarea><button type="button" class="btn" data-copy="embed">%s</button></section>'
                '<form method="post" action="/forms/%d/delete" class="danger-zone">%s<button class="btn btn-danger" data-confirm="%s">%s</button></form></aside>') % (
            e(T(req, "forms.public_link")), e(base), e(f["public_id"]), e(base), e(f["public_id"]), e(T(req, "forms.public_help")),
            e(T(req, "forms.embed")), e(T(req, "forms.embed_help")), e(embed_code(req, f)), e(T(req, "common.copy")),
            f["id"], ui.csrf(req), e(T(req, "forms.confirm_delete")), e(T(req, "common.delete")))
    return ui.page(req, d["name"] or T(req, "forms.new"), '<div class="split">%s%s</div>' % (form, side), "forms")


def form_delete(req, fid):
    db.run("DELETE FROM forms WHERE id = ?", (_int(fid),))
    ui.flash(req, T(req, "common.deleted"))
    return redirect("/forms")


router.add("GET", "/contacts", contacts)
router.add("POST", "/contacts/bulk", bulk)
router.add("GET", "/contacts/new", contact_new)
router.add("POST", "/contacts/new", contact_new)
router.add("GET", "/contacts/import", import_)
router.add("POST", "/contacts/import", import_)
router.add("GET", "/contacts/export.csv", export)
router.add("GET", "/contacts/<cid>", contact_edit)
router.add("POST", "/contacts/<cid>", contact_edit)
router.add("GET", "/contacts/<cid>/data.json", contact_data)
router.add("POST", "/contacts/<cid>/delete", contact_delete)
router.add("GET", "/lists", lists)
router.add("GET", "/lists/new", list_edit)
router.add("POST", "/lists/new", list_edit)
router.add("GET", "/lists/<lid>", list_edit)
router.add("POST", "/lists/<lid>", list_edit)
router.add("POST", "/lists/<lid>/delete", list_delete)
router.add("GET", "/forms", forms)
router.add("GET", "/forms/new", form_edit)
router.add("POST", "/forms/new", form_edit)
router.add("GET", "/forms/<fid>", form_edit)
router.add("POST", "/forms/<fid>", form_edit)
router.add("POST", "/forms/<fid>/delete", form_delete)
