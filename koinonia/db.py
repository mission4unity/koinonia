"""SQLite storage. One connection per thread; the whole database is one file."""
import json
import os
import sqlite3
import threading

_local = threading.local()
DB_PATH = os.environ.get("KOINONIA_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "koinonia.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE COLLATE NOCASE NOT NULL, name TEXT NOT NULL DEFAULT '',
  pw_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'editor', lang TEXT NOT NULL DEFAULT 'nl',
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, flash TEXT, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lists (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  double_optin INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE COLLATE NOCASE NOT NULL,
  first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '', lang TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active', notes TEXT NOT NULL DEFAULT '', token TEXT UNIQUE NOT NULL,
  source TEXT NOT NULL DEFAULT '', consent_text TEXT NOT NULL DEFAULT '', consent_at TEXT, consent_ip TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS list_members (
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'subscribed', confirm_token TEXT, updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (list_id, contact_id));
CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL);
CREATE TABLE IF NOT EXISTS contact_tags (
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY (contact_id, tag_id));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
  type TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS forms (
  id INTEGER PRIMARY KEY, public_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, list_ids TEXT NOT NULL DEFAULT '[]',
  lang TEXT NOT NULL DEFAULT 'nl', title TEXT NOT NULL DEFAULT '', intro TEXT NOT NULL DEFAULT '',
  ask_name INTEGER NOT NULL DEFAULT 1, ask_lang INTEGER NOT NULL DEFAULT 0, consent_text TEXT NOT NULL DEFAULT '',
  success_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY, public_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL DEFAULT 'campaign',
  name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', list_ids TEXT NOT NULL DEFAULT '[]',
  tag_ids TEXT NOT NULL DEFAULT '[]', default_lang TEXT NOT NULL DEFAULT 'nl',
  from_name TEXT NOT NULL DEFAULT '', from_email TEXT NOT NULL DEFAULT '', reply_to TEXT NOT NULL DEFAULT '',
  track_opens INTEGER NOT NULL DEFAULT 1, track_clicks INTEGER NOT NULL DEFAULT 1, archive INTEGER NOT NULL DEFAULT 0,
  theme TEXT NOT NULL DEFAULT '{}', scheduled_at TEXT, sent_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS variants (
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE, lang TEXT NOT NULL,
  subject TEXT NOT NULL DEFAULT '', preheader TEXT NOT NULL DEFAULT '', blocks TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (campaign_id, lang));
CREATE TABLE IF NOT EXISTS deliveries (
  id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL, lang TEXT NOT NULL DEFAULT '',
  token TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'queued', error TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), sent_at TEXT, opened_at TEXT, open_count INTEGER NOT NULL DEFAULT 0,
  clicked_at TEXT, click_count INTEGER NOT NULL DEFAULT 0, unsubscribed_at TEXT,
  UNIQUE (campaign_id, contact_id));
CREATE INDEX IF NOT EXISTS ix_deliveries_status ON deliveries(status, campaign_id);
CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  url TEXT NOT NULL, UNIQUE (campaign_id, url));
CREATE TABLE IF NOT EXISTS clicks (
  delivery_id INTEGER NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
  link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE, at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS automations (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, list_id INTEGER REFERENCES lists(id) ON DELETE SET NULL,
  active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS automation_steps (
  id INTEGER PRIMARY KEY, automation_id INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, delay_days INTEGER NOT NULL DEFAULT 0,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS enrollments (
  automation_id INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  next_position INTEGER NOT NULL DEFAULT 0, next_at TEXT, done INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (automation_id, contact_id));
"""

DEFAULT_SETTINGS = {
    "org_name": "", "org_address": "", "org_website": "", "base_url": "http://localhost:8080",
    "from_name": "", "from_email": "", "reply_to": "", "default_lang": "nl", "content_langs": "nl,en",
    "timezone": "Europe/Amsterdam",
    "transport": "file", "smtp_host": "", "smtp_port": "587", "smtp_security": "starttls",
    "smtp_user": "", "smtp_password": "", "rate_per_minute": "60",
    "track_opens": "1", "track_clicks": "1", "retention_days": "365",
    "accent_color": "#3d5a40", "logo_url": "", "donate_url": "", "archive_enabled": "1",
}


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def get():
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "path", None) != DB_PATH:
        conn = connect()
        _local.conn, _local.path = conn, DB_PATH
    return conn


def close():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init(path=None):
    global DB_PATH
    if path:
        DB_PATH = path
        close()
    conn = get()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.commit()


def q(sql, args=()):
    return get().execute(sql, args).fetchall()


def one(sql, args=()):
    return get().execute(sql, args).fetchone()


def val(sql, args=(), default=None):
    row = get().execute(sql, args).fetchone()
    return row[0] if row is not None and row[0] is not None else default


def run(sql, args=()):
    return get().execute(sql, args)


def commit():
    get().commit()


def rollback():
    get().rollback()


def settings():
    return {r["key"]: r["value"] for r in q("SELECT key, value FROM settings")}


def setting(key, default=""):
    return val("SELECT value FROM settings WHERE key = ?", (key,), DEFAULT_SETTINGS.get(key, default))


def set_settings(values):
    for k, v in values.items():
        run("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))


def jl(text, default=None):
    """Parse a JSON column, tolerating junk."""
    try:
        v = json.loads(text or "")
    except (TypeError, ValueError):
        return [] if default is None else default
    return v
