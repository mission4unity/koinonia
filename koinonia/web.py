"""Tiny WSGI toolkit: request, response, router. No dependencies."""
import html
import json
import mimetypes
import os
import re
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote

MAX_BODY = 12 * 1024 * 1024
STATUS = {200: "200 OK", 204: "204 No Content", 302: "302 Found", 303: "303 See Other", 304: "304 Not Modified",
          400: "400 Bad Request", 403: "403 Forbidden", 404: "404 Not Found", 405: "405 Method Not Allowed",
          413: "413 Payload Too Large", 429: "429 Too Many Requests", 500: "500 Internal Server Error"}


def e(value):
    """HTML-escape anything (None becomes empty)."""
    return html.escape("" if value is None else str(value), quote=True)


class HTTPError(Exception):
    def __init__(self, status, message=""):
        super().__init__(message)
        self.status, self.message = status, message


class Request:
    def __init__(self, environ, trust_proxy=False):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        raw = environ.get("PATH_INFO", "/") or "/"
        try:
            raw = raw.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        self.path = raw
        self.query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        self.cookies = {}
        try:
            c = SimpleCookie(environ.get("HTTP_COOKIE", ""))
            self.cookies = {k: m.value for k, m in c.items()}
        except Exception:
            pass
        ip = environ.get("REMOTE_ADDR", "")
        if trust_proxy and environ.get("HTTP_X_FORWARDED_FOR"):
            ip = environ["HTTP_X_FORWARDED_FOR"].split(",")[0].strip()
        self.ip = ip
        self._body = None
        self._form = None
        self.params = {}
        self.user = None
        self.session = None

    @property
    def content_type(self):
        return self.environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower()

    def header(self, name, default=""):
        return self.environ.get("HTTP_" + name.upper().replace("-", "_"), default)

    def body(self):
        if self._body is None:
            try:
                n = int(self.environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                n = 0
            if n > MAX_BODY:
                raise HTTPError(413, "Payload too large")
            self._body = self.environ["wsgi.input"].read(n) if n > 0 else b""
        return self._body

    def form(self):
        if self._form is None:
            if self.content_type == "application/x-www-form-urlencoded":
                self._form = parse_qs(self.body().decode("utf-8", "replace"), keep_blank_values=True)
            else:
                self._form = {}
        return self._form

    def get(self, name, default=""):
        """First value of a form field (POST) or query parameter."""
        v = self.form().get(name) or self.query.get(name)
        return v[0] if v else default

    def getlist(self, name):
        return self.form().get(name) or self.query.get(name) or []

    def json(self):
        try:
            return json.loads(self.body().decode("utf-8") or "null")
        except ValueError:
            raise HTTPError(400, "Invalid JSON")


class Response:
    def __init__(self, body=b"", status=200, content_type="text/html; charset=utf-8", headers=None):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = [("Content-Type", content_type)] if content_type else []
        if headers:
            self.headers.extend(headers)

    def set_cookie(self, name, value, max_age=None, secure=False, path="/"):
        parts = ["%s=%s" % (name, value), "Path=" + path, "HttpOnly", "SameSite=Lax"]
        if max_age is not None:
            parts.append("Max-Age=%d" % max_age)
        if secure:
            parts.append("Secure")
        self.headers.append(("Set-Cookie", "; ".join(parts)))
        return self


def redirect(url, status=303):
    return Response(b"", status, None, [("Location", url)])


def json_response(data, status=200):
    return Response(json.dumps(data), status, "application/json; charset=utf-8")


def static_file(directory, name, cache=True):
    if not re.match(r"^[A-Za-z0-9_.-]+$", name) or name.startswith("."):
        raise HTTPError(404)
    path = os.path.join(directory, name)
    if not os.path.isfile(path):
        raise HTTPError(404)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
        ctype += "; charset=utf-8"
    with open(path, "rb") as f:
        data = f.read()
    headers = [("Cache-Control", "public, max-age=86400" if cache else "no-cache")]
    return Response(data, 200, ctype, headers)


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, handler, auth="user"):
        """auth: 'public', 'user' (any logged-in user) or 'admin'."""
        rx = re.compile("^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern) + "$")
        self.routes.append((method, rx, handler, auth))

    def match(self, method, path):
        allowed = False
        for m, rx, handler, auth in self.routes:
            mt = rx.match(path)
            if mt:
                if m == method or (m == "GET" and method == "HEAD"):
                    return handler, mt.groupdict(), auth
                allowed = True
        if allowed:
            raise HTTPError(405)
        raise HTTPError(404)


def url(path, **params):
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    if not clean:
        return path
    return path + "?" + "&".join("%s=%s" % (quote(str(k)), quote(str(v))) for k, v in clean.items())
