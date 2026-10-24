"""The WSGI application: sessions, CSRF, routing, error pages."""
import hashlib
import logging
import os
import traceback
from datetime import datetime, timedelta, timezone

from . import db, i18n, security, ui
from .web import HTTPError, Request, Response, Router, e, redirect, static_file

log = logging.getLogger("koinonia")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
UPLOADS = os.environ.get("KOINONIA_UPLOADS", os.path.join(os.path.dirname(HERE), "data", "uploads"))
SESSION_DAYS = 14
COOKIE = "kn_session"

router = Router()
CSP_ADMIN = ("default-src 'self'; img-src * data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
             "frame-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'")


def hash_token(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def load_session(req):
    tok = req.cookies.get(COOKIE)
    if not tok:
        return
    row = db.one("SELECT * FROM sessions WHERE token = ? AND expires_at > datetime('now')", (hash_token(tok),))
    if row:
        user = db.one("SELECT * FROM users WHERE id = ?", (row["user_id"],))
        if user:
            req.session, req.user = row, user


def start_session(req, user_id, resp):
    tok = security.token(32)
    exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    db.run("INSERT INTO sessions(token, user_id, csrf, expires_at) VALUES (?, ?, ?, ?)", (hash_token(tok), user_id, security.token(24), exp))
    resp.set_cookie(COOKIE, tok, max_age=SESSION_DAYS * 86400, secure=is_https())
    return resp


def end_session(req, resp):
    if req.session:
        db.run("DELETE FROM sessions WHERE token = ?", (req.session["token"],))
    resp.set_cookie(COOKIE, "", max_age=0, secure=is_https())
    return resp


def is_https():
    return (db.setting("base_url") or "").startswith("https://")


def pick_lang(req):
    if req.user:
        return i18n.ui_lang(req.user["lang"])
    if req.cookies.get("kn_lang") in i18n.UI_LANGS:
        return req.cookies["kn_lang"]
    for part in req.header("Accept-Language").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in i18n.UI_LANGS:
            return code
    return "en"


def needs_setup():
    return not db.val("SELECT 1 FROM users LIMIT 1")


def handle(req):
    load_session(req)
    req.lang = pick_lang(req)
    handler, params, auth = router.match(req.method, req.path)
    req.params = params
    if auth != "public":
        if needs_setup() and not req.path.startswith("/setup"):
            return redirect("/setup")
        if auth in ("user", "admin") and not req.user:
            return redirect("/login?next=" + req.path if req.method == "GET" and req.path != "/" else "/login")
        if auth == "admin" and req.user["role"] != "admin":
            raise HTTPError(403)
        if req.method == "POST" and req.user:
            token = req.header("X-CSRF-Token") or req.get("_csrf")
            if not security.same(token, req.session["csrf"]):
                raise HTTPError(403, "CSRF")
    return handler(req, **params)


def error_page(req, status, message=""):
    titles = {403: "error.403", 404: "error.404", 405: "error.405", 413: "error.413", 429: "error.429", 400: "error.400"}
    title = ui.T(req, titles.get(status, "error.500"))
    body = '<h1>%s</h1><p>%s</p><p><a class="btn" href="/">%s</a></p>' % (e(title), e(message if status != 500 else ""), e(ui.T(req, "common.home")))
    return ui.bare(req, title, body, status)


def application(environ, start_response):
    req = Request(environ, trust_proxy=os.environ.get("KOINONIA_TRUST_PROXY") == "1")
    req.lang = "en"
    try:
        resp = handle(req)
        db.commit()
    except HTTPError as ex:
        db.rollback()
        resp = error_page(req, ex.status, ex.message)
    except Exception:
        db.rollback()
        log.error("unhandled error on %s %s\n%s", req.method, req.path, traceback.format_exc())
        resp = error_page(req, 500)
        try:
            db.commit()
        except Exception:
            pass
    headers = list(resp.headers)
    names = {k.lower() for k, _ in headers}
    headers.append(("X-Content-Type-Options", "nosniff"))
    headers.append(("Referrer-Policy", "strict-origin-when-cross-origin"))
    if "content-security-policy" not in names:
        headers.append(("Content-Security-Policy", CSP_ADMIN))
    if "cache-control" not in names:
        headers.append(("Cache-Control", "no-store"))
    body = b"" if req.method == "HEAD" else resp.body
    headers.append(("Content-Length", str(len(body))))
    start_response(ui_status(resp.status), headers)
    return [body]


def ui_status(code):
    from .web import STATUS
    return STATUS.get(code, "%d Unknown" % code)


# ---------------------------------------------------------------- static & uploads
def r_static(req, name):
    return static_file(STATIC, name)


def r_upload(req, name):
    resp = static_file(UPLOADS, name)
    resp.headers.append(("Content-Security-Policy", "default-src 'none'; sandbox"))
    return resp


router.add("GET", "/static/<name>", r_static, "public")
router.add("GET", "/uploads/<name>", r_upload, "public")

# Route modules register themselves on import.
from . import views_auth, views_contacts, views_campaigns, views_settings, views_public  # noqa: E402,F401


def create_app(db_path=None):
    db.init(db_path)
    i18n.load()
    os.makedirs(UPLOADS, exist_ok=True)
    return application
