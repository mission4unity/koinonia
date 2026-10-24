"""Builds MIME messages and sends them over SMTP (or writes .eml files for testing)."""
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from . import db

OUTBOX = os.environ.get("KOINONIA_OUTBOX", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "outbox"))


class PermanentError(Exception):
    """The recipient address was rejected for good (hard bounce)."""


class MessageError(Exception):
    """This one message was refused (content, sender); do not retry it."""


class TemporaryError(Exception):
    """Connection or server trouble; try again later."""


def clean(s):
    return " ".join(str(s or "").split())


def build(from_name, from_email, to, subject, html, text, reply_to="", headers=None, lang=""):
    msg = EmailMessage()
    msg["Subject"] = clean(subject)
    msg["From"] = formataddr((clean(from_name), clean(from_email)))
    msg["To"] = clean(to)
    msg["Date"] = formatdate(localtime=True)
    domain = clean(from_email).rpartition("@")[2] or "localhost"
    msg["Message-ID"] = make_msgid(domain=domain)
    if reply_to:
        msg["Reply-To"] = clean(reply_to)
    for k, v in (headers or {}).items():
        msg[k] = clean(v)
    msg.set_content(text, cte="quoted-printable")
    msg.add_alternative(html, subtype="html", cte="quoted-printable")
    if lang:  # after set_content(), which clears Content-* headers
        msg["Content-Language"] = clean(lang)
    return msg


class Sender:
    """Use as a context manager so one SMTP connection serves a whole batch."""

    def __init__(self, cfg=None):
        self.cfg = cfg or db.settings()
        self.conn = None

    def __enter__(self):
        if self.cfg.get("transport") == "smtp":
            self.conn = self._connect()
        return self

    def __exit__(self, *exc):
        if self.conn is not None:
            try:
                self.conn.quit()
            except Exception:
                pass
            self.conn = None

    def _connect(self):
        c = self.cfg
        host, sec = c.get("smtp_host", "").strip(), c.get("smtp_security", "starttls")
        if not host:
            raise TemporaryError("SMTP host is not configured")
        try:
            port = int(c.get("smtp_port") or (465 if sec == "ssl" else 587))
            ctx = ssl.create_default_context()
            if sec == "ssl":
                conn = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)
            else:
                conn = smtplib.SMTP(host, port, timeout=30)
                conn.ehlo()
                if sec == "starttls":
                    conn.starttls(context=ctx)
                    conn.ehlo()
            if c.get("smtp_user"):
                conn.login(c["smtp_user"], c.get("smtp_password", ""))
            return conn
        except (OSError, smtplib.SMTPException, ValueError) as ex:
            raise TemporaryError(str(ex) or ex.__class__.__name__)

    def send(self, msg):
        if self.cfg.get("transport") != "smtp":
            os.makedirs(OUTBOX, exist_ok=True)
            name = "%d-%s.eml" % (int(time.time() * 1000), os.urandom(4).hex())
            with open(os.path.join(OUTBOX, name), "wb") as f:
                f.write(bytes(msg))
            return
        if self.conn is None:
            self.conn = self._connect()
        try:
            self.conn.send_message(msg)
        except smtplib.SMTPRecipientsRefused as ex:
            code, why = list(ex.recipients.values())[0] if ex.recipients else (550, b"refused")
            text = why.decode("utf-8", "replace") if isinstance(why, bytes) else str(why)
            if 500 <= code < 600:
                raise PermanentError("%s %s" % (code, text))
            raise TemporaryError("%s %s" % (code, text))
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError) as ex:
            self.conn = None
            raise TemporaryError(str(ex) or ex.__class__.__name__)
        except smtplib.SMTPResponseException as ex:
            text = ex.smtp_error.decode("utf-8", "replace") if isinstance(ex.smtp_error, bytes) else str(ex.smtp_error)
            if 500 <= ex.smtp_code < 600 and ex.smtp_code not in (530, 535):
                raise MessageError("%s %s" % (ex.smtp_code, text))
            raise TemporaryError("%s %s" % (ex.smtp_code, text))


def test_connection(cfg):
    """Returns '' when OK, otherwise an error message."""
    if cfg.get("transport") != "smtp":
        return ""
    try:
        with Sender(cfg):
            pass
        return ""
    except TemporaryError as ex:
        return str(ex)
