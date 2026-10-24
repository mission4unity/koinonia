"""Passwords, tokens and simple in-memory rate limiting."""
import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque

ITERATIONS = 240000
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def token(n=24):
    return secrets.token_urlsafe(n)


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def check_password(password, stored):
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def valid_email(addr):
    addr = (addr or "").strip()
    return len(addr) <= 254 and bool(EMAIL_RE.match(addr))


def same(a, b):
    return bool(a) and bool(b) and hmac.compare_digest(str(a), str(b))


class RateLimiter:
    """Allow `limit` hits per `window` seconds per key."""

    def __init__(self, limit, window):
        self.limit, self.window = limit, window
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self.hits) > 10000:  # keep memory bounded
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] > self.window]:
                    del self.hits[k]
            return True


login_limiter = RateLimiter(10, 300)
form_limiter = RateLimiter(20, 3600)
