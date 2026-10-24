"""Test helpers: an isolated data directory, a WSGI test client and a fake SMTP server."""
import email
import glob
import json
import os
import re
import socketserver
import tempfile
import threading
from email import policy
from io import BytesIO
from urllib.parse import urlencode

TMP = tempfile.mkdtemp(prefix="koinonia-test-")
os.environ["KOINONIA_OUTBOX"] = os.path.join(TMP, "outbox")
os.environ["KOINONIA_UPLOADS"] = os.path.join(TMP, "uploads")

from koinonia import app as appmod, db, mailer  # noqa: E402


def fresh_app(name):
    path = os.path.join(TMP, name + ".db")
    if os.path.exists(path):
        os.remove(path)
    return appmod.create_app(path)


class Resp:
    def __init__(self, code, headers, body):
        self.status, self.headers, self.raw = code, headers, body
        self.text = body.decode("utf-8", "replace")

    def header(self, name):
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return None

    def json(self):
        return json.loads(self.text)


class Client:
    def __init__(self, app, ip="127.0.0.1"):
        self.app, self.cookies, self.ip = app, {}, ip
        self.csrf = ""

    def request(self, method, path, data=None, json_body=None, headers=None, raw=None, content_type=None):
        path, _, qs = path.partition("?")
        body, ctype = b"", ""
        if json_body is not None:
            body, ctype = json.dumps(json_body).encode(), "application/json"
        elif data is not None:
            body, ctype = urlencode(data, doseq=True).encode(), "application/x-www-form-urlencoded"
        elif raw is not None:
            body, ctype = raw, content_type or "application/octet-stream"
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "SERVER_NAME": "localhost", "SERVER_PORT": "8080",
               "HTTP_HOST": "localhost:8080", "wsgi.url_scheme": "http", "wsgi.input": BytesIO(body), "CONTENT_LENGTH": str(len(body)),
               "CONTENT_TYPE": ctype, "REMOTE_ADDR": self.ip,
               "HTTP_COOKIE": "; ".join("%s=%s" % kv for kv in self.cookies.items())}
        for k, v in (headers or {}).items():
            env["HTTP_" + k.upper().replace("-", "_")] = v
        holder = {}

        def start(status, hdrs):
            holder["status"], holder["headers"] = status, hdrs

        out = b"".join(self.app(env, start))
        for k, v in holder["headers"]:
            if k == "Set-Cookie":
                name, val = v.split(";")[0].split("=", 1)
                if "Max-Age=0" in v:
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = val
        r = Resp(int(holder["status"].split()[0]), holder["headers"], out)
        m = re.search(r'name="csrf-token" content="([^"]+)"', r.text) or re.search(r'name="_csrf" value="([^"]+)"', r.text)
        if m:
            self.csrf = m.group(1)
        return r

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, data=None, csrf=True, **kw):
        data = dict(data or {})
        if csrf and "_csrf" not in data:
            data["_csrf"] = self.csrf
        return self.request("POST", path, data=data, **kw)

    def post_json(self, path, body):
        return self.request("POST", path, json_body=body, headers={"X-CSRF-Token": self.csrf})


def outbox():
    """All emails written by the file transport, oldest first, parsed."""
    files = sorted(glob.glob(os.path.join(mailer.OUTBOX, "*.eml")))
    msgs = []
    for f in files:
        with open(f, "rb") as fh:
            msgs.append(email.message_from_bytes(fh.read(), policy=policy.default))
    return msgs


def clear_outbox():
    for f in glob.glob(os.path.join(mailer.OUTBOX, "*.eml")):
        os.remove(f)


def html_of(msg):
    return msg.get_body(("html",)).get_content()


def text_of(msg):
    return msg.get_body(("plain",)).get_content()


class FakeSMTP:
    """A minimal SMTP server. Recipients containing 'bounce' get a 550."""

    def __init__(self):
        self.messages = []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                w = lambda s: self.wfile.write((s + "\r\n").encode())
                w("220 fake ESMTP")
                rcpts, data_mode, buf = [], False, []
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    text = line.decode("utf-8", "replace").rstrip("\r\n")
                    if data_mode:
                        if text == ".":
                            data_mode = False
                            outer.messages.append((rcpts, "\r\n".join(buf)))
                            rcpts, buf = [], []
                            w("250 queued")
                        else:
                            buf.append(text[1:] if text.startswith("..") else text)
                        continue
                    cmd = text[:4].upper()
                    if cmd in ("EHLO", "HELO"):
                        w("250-fake\r\n250 SIZE 10000000")
                    elif cmd == "MAIL":
                        w("250 ok")
                    elif cmd == "RCPT":
                        if "bounce" in text.lower():
                            w("550 5.1.1 no such user")
                        else:
                            rcpts.append(text)
                            w("250 ok")
                    elif cmd == "DATA":
                        data_mode = True
                        w("354 go ahead")
                    elif cmd == "RSET":
                        rcpts = []
                        w("250 ok")
                    elif cmd == "NOOP":
                        w("250 ok")
                    elif cmd == "QUIT":
                        w("221 bye")
                        return
                    else:
                        w("502 not implemented")

        class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def setup_admin(client, lang="nl"):
    client.get("/setup?ui=%s" % lang)
    r = client.post("/setup", {"org_name": "Gemeente De Ark", "name": "Anna Jansen", "email": "anna@deark.example", "password": "lang genoeg wachtwoord", "lang": lang}, csrf=False)
    assert r.status == 303, r.text
    db.set_settings({"org_address": "Kerkstraat 1\n1234 AB Ergens", "rate_per_minute": "1000"})
    db.commit()
    client.get("/")
    return r
