"""Contacts, lists, tags, subscriptions, CSV import/export and consent records."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone

from . import db, i18n, security

HEADER_ALIASES = {
    "email": ["email", "e-mail", "emailadres", "e-mailadres", "mail", "email address", "e-mail-adresse", "courriel", "correo", "correo electrónico"],
    "first_name": ["first_name", "firstname", "first name", "voornaam", "vorname", "prénom", "prenom", "nombre", "nome", "given name"],
    "last_name": ["last_name", "lastname", "last name", "achternaam", "nachname", "nom", "apellido", "apellidos", "sobrenome", "surname", "family name"],
    "lang": ["lang", "language", "taal", "sprache", "langue", "idioma", "língua", "lingua"],
    "tags": ["tags", "tag", "labels", "label", "groepen", "groups"],
    "notes": ["notes", "notities", "opmerkingen", "notizen", "remarques", "notas"],
}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def log(contact_id, type_, detail=""):
    db.run("INSERT INTO events(contact_id, type, detail) VALUES (?, ?, ?)", (contact_id, type_, str(detail)[:500]))


def tag_ids(names):
    ids = []
    for name in names:
        name = " ".join(name.split())[:60]
        if not name:
            continue
        db.run("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
        ids.append(db.val("SELECT id FROM tags WHERE name = ?", (name,)))
    return ids


def split_tags(text):
    return [t.strip() for t in (text or "").replace(";", ",").split(",") if t.strip()]


def set_tags(contact_id, names):
    db.run("DELETE FROM contact_tags WHERE contact_id = ?", (contact_id,))
    add_tags(contact_id, names)


def add_tags(contact_id, names):
    for tid in tag_ids(names):
        db.run("INSERT OR IGNORE INTO contact_tags(contact_id, tag_id) VALUES (?, ?)", (contact_id, tid))


def contact_tags(contact_id):
    return [r["name"] for r in db.q("SELECT t.name FROM tags t JOIN contact_tags ct ON ct.tag_id = t.id WHERE ct.contact_id = ? ORDER BY t.name", (contact_id,))]


def upsert(email, first_name=None, last_name=None, lang=None, source="", update=True):
    """Create a contact or update an existing one. Returns (id, created)."""
    email = email.strip()
    row = db.one("SELECT id FROM contacts WHERE email = ?", (email,))
    if row:
        if update:
            sets, args = [], []
            for col, v in (("first_name", first_name), ("last_name", last_name), ("lang", lang)):
                if v is not None and str(v).strip():
                    sets.append(col + " = ?")
                    args.append(str(v).strip()[:120])
            if sets:
                db.run("UPDATE contacts SET %s, updated_at = datetime('now') WHERE id = ?" % ", ".join(sets), args + [row["id"]])
        return row["id"], False
    cur = db.run("INSERT INTO contacts(email, first_name, last_name, lang, token, source) VALUES (?, ?, ?, ?, ?, ?)",
                 (email, (first_name or "").strip()[:120], (last_name or "").strip()[:120], (lang or "").strip()[:5],
                  security.token(18), source[:120]))
    return cur.lastrowid, True


def record_consent(contact_id, text, ip=""):
    db.run("UPDATE contacts SET consent_text = ?, consent_at = datetime('now'), consent_ip = ? WHERE id = ?", (text[:1000], ip[:64], contact_id))


def set_membership(contact_id, list_id, status, confirm_token=None):
    old = db.val("SELECT status FROM list_members WHERE list_id = ? AND contact_id = ?", (list_id, contact_id))
    db.run("""INSERT INTO list_members(list_id, contact_id, status, confirm_token) VALUES (?, ?, ?, ?)
              ON CONFLICT(list_id, contact_id) DO UPDATE SET status = excluded.status,
              confirm_token = excluded.confirm_token, updated_at = datetime('now')""", (list_id, contact_id, status, confirm_token))
    if status == "subscribed" and old != "subscribed":
        enroll(contact_id, list_id)
    return old


def enroll(contact_id, list_id):
    """Start every active automation that is triggered by joining this list."""
    for a in db.q("SELECT id FROM automations WHERE active = 1 AND list_id = ?", (list_id,)):
        first = db.one("SELECT delay_days FROM automation_steps WHERE automation_id = ? ORDER BY position LIMIT 1", (a["id"],))
        if not first:
            continue
        at = (datetime.now(timezone.utc) + timedelta(days=first["delay_days"])).strftime("%Y-%m-%d %H:%M:%S")
        db.run("INSERT OR IGNORE INTO enrollments(automation_id, contact_id, next_position, next_at) VALUES (?, ?, 0, ?)", (a["id"], contact_id, at))


def unsubscribe_all(contact_id, delivery_id=None, reason="unsubscribed"):
    db.run("UPDATE contacts SET status = 'unsubscribed', updated_at = datetime('now') WHERE id = ? AND status = 'active'", (contact_id,))
    db.run("UPDATE list_members SET status = 'unsubscribed', updated_at = datetime('now') WHERE contact_id = ?", (contact_id,))
    db.run("UPDATE enrollments SET done = 1 WHERE contact_id = ?", (contact_id,))
    if delivery_id:
        db.run("UPDATE deliveries SET unsubscribed_at = COALESCE(unsubscribed_at, datetime('now')) WHERE id = ?", (delivery_id,))
    log(contact_id, reason)


def subscribe_form(form, email, first_name, last_name, lang, list_ids, ip):
    """Handle a public sign-up. Returns ('subscribed'|'pending', confirm_token or None, contact_id)."""
    allowed = [int(x) for x in db.jl(form["list_ids"]) if str(x).isdigit()]
    chosen = [i for i in list_ids if i in allowed] or (allowed if len(allowed) == 1 else [])
    cid, created = upsert(email, first_name, last_name, lang or form["lang"], source="form:%s" % form["name"])
    row = db.one("SELECT status FROM contacts WHERE id = ?", (cid,))
    if row["status"] != "active":
        # Someone who left earlier is signing up again on purpose: welcome them back.
        db.run("UPDATE contacts SET status = 'active', updated_at = datetime('now') WHERE id = ?", (cid,))
    record_consent(cid, form["consent_text"] or form["title"] or form["name"], ip)
    lists = db.q("SELECT id, double_optin FROM lists WHERE id IN (%s)" % ",".join("?" * len(chosen)), chosen) if chosen else []
    token, pending = security.token(24), False
    for l in lists:
        current = db.val("SELECT status FROM list_members WHERE list_id = ? AND contact_id = ?", (l["id"], cid))
        if current == "subscribed":
            continue
        if l["double_optin"]:
            set_membership(cid, l["id"], "pending", token)
            pending = True
        else:
            set_membership(cid, l["id"], "subscribed")
    log(cid, "signup", form["name"])
    return ("pending" if pending else "subscribed"), (token if pending else None), cid


def confirm(token):
    rows = db.q("SELECT list_id, contact_id FROM list_members WHERE confirm_token = ? AND status = 'pending'", (token,)) if token else []
    for r in rows:
        set_membership(r["contact_id"], r["list_id"], "subscribed")
        log(r["contact_id"], "confirmed", db.val("SELECT name FROM lists WHERE id = ?", (r["list_id"],), ""))
    return rows[0]["contact_id"] if rows else None


def audience_sql(list_ids, tag_ids_, langs=None):
    """SQL (and args) selecting contact ids that should receive a campaign."""
    list_ids = [int(x) for x in list_ids if str(x).isdigit()]
    if not list_ids:
        return "SELECT id FROM contacts WHERE 0", []
    sql = ("SELECT c.id FROM contacts c WHERE c.status = 'active' AND EXISTS (SELECT 1 FROM list_members m "
           "WHERE m.contact_id = c.id AND m.status = 'subscribed' AND m.list_id IN (%s))" % ",".join("?" * len(list_ids)))
    args = list(list_ids)
    tag_ids_ = [int(x) for x in tag_ids_ if str(x).isdigit()]
    if tag_ids_:
        sql += " AND EXISTS (SELECT 1 FROM contact_tags ct WHERE ct.contact_id = c.id AND ct.tag_id IN (%s))" % ",".join("?" * len(tag_ids_))
        args += tag_ids_
    return sql, args


def audience_count(list_ids, tag_ids_):
    sql, args = audience_sql(list_ids, tag_ids_)
    return db.val("SELECT COUNT(*) FROM (%s)" % sql, args, 0)


# ---------------------------------------------------------------- CSV
def parse_csv(text):
    """Returns (rows as dicts with canonical keys, unknown headers)."""
    text = (text or "").lstrip("﻿")
    if not text.strip():
        return [], []
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return [], []
    header = [h.strip().lower() for h in rows[0]]
    mapping, unknown = {}, []
    for i, h in enumerate(header):
        for key, names in HEADER_ALIASES.items():
            if h in names and key not in mapping.values():
                mapping[i] = key
                break
        else:
            unknown.append(rows[0][i])
    if "email" not in mapping.values():
        # No header row: find the column that looks like e-mail addresses.
        for i, c in enumerate(rows[0]):
            if security.valid_email(c):
                mapping, unknown = {i: "email"}, []
                body = rows
                break
        else:
            return [], unknown
    else:
        body = rows[1:]
    out = []
    for r in body:
        d = {}
        for i, key in mapping.items():
            if i < len(r):
                d[key] = r[i].strip()
        out.append(d)
    return out, unknown


def import_rows(rows, list_id=None, tags=(), update=True, consent="", source="import"):
    stats = {"added": 0, "updated": 0, "invalid": 0, "skipped": 0}
    seen = set()
    for r in rows:
        email = (r.get("email") or "").strip()
        if not security.valid_email(email) or email.lower() in seen:
            stats["invalid" if not security.valid_email(email) else "skipped"] += 1
            continue
        seen.add(email.lower())
        status = db.val("SELECT status FROM contacts WHERE email = ?", (email,))
        if status and status != "active":
            stats["skipped"] += 1  # never re-subscribe people who left or bounced
            continue
        lang = i18n.content_lang(r.get("lang"), "") if r.get("lang") else None
        cid, created = upsert(email, r.get("first_name"), r.get("last_name"), lang, source=source, update=update)
        if created and r.get("notes"):
            db.run("UPDATE contacts SET notes = ? WHERE id = ?", (r["notes"][:2000], cid))
        if created and consent:
            record_consent(cid, consent)
        if list_id:
            if db.val("SELECT status FROM list_members WHERE list_id = ? AND contact_id = ?", (list_id, cid)) != "unsubscribed":
                set_membership(cid, list_id, "subscribed")
        add_tags(cid, list(tags) + split_tags(r.get("tags")))
        stats["added" if created else "updated"] += 1
        if created:
            log(cid, "imported", source)
    return stats


def export_csv(where="1", args=()):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "first_name", "last_name", "lang", "status", "lists", "tags", "created_at", "consent_at", "consent_text"])
    for c in db.q("SELECT * FROM contacts c WHERE %s ORDER BY c.email" % where, args):
        lists = ", ".join(r["name"] for r in db.q("SELECT l.name FROM lists l JOIN list_members m ON m.list_id = l.id WHERE m.contact_id = ? AND m.status = 'subscribed'", (c["id"],)))
        w.writerow([c["email"], c["first_name"], c["last_name"], c["lang"], c["status"], lists, ", ".join(contact_tags(c["id"])),
                    c["created_at"], c["consent_at"] or "", c["consent_text"]])
    return "﻿" + buf.getvalue()


def personal_data(contact_id):
    """Everything we store about one person (for a GDPR access request)."""
    c = db.one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    if not c:
        return None
    data = {k: c[k] for k in c.keys() if k != "token"}
    data["lists"] = [dict(r) for r in db.q("SELECT l.name, m.status, m.updated_at FROM list_members m JOIN lists l ON l.id = m.list_id WHERE m.contact_id = ?", (contact_id,))]
    data["tags"] = contact_tags(contact_id)
    data["emails_received"] = [dict(r) for r in db.q(
        "SELECT ca.name AS campaign, d.sent_at, d.opened_at, d.clicked_at, d.unsubscribed_at FROM deliveries d JOIN campaigns ca ON ca.id = d.campaign_id WHERE d.contact_id = ? ORDER BY d.id", (contact_id,))]
    data["activity"] = [dict(r) for r in db.q("SELECT type, detail, at FROM events WHERE contact_id = ? ORDER BY id", (contact_id,))]
    return json.dumps(data, ensure_ascii=False, indent=2)
