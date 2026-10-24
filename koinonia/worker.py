"""Background sender: starts scheduled campaigns, runs automations, sends queued mail
at the configured pace and tidies up old tracking data."""
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from . import audience, compose, db, mailer

log = logging.getLogger("koinonia.worker")
MAX_ATTEMPTS = 5


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def enqueue(campaign_id):
    """Create a delivery for everyone in the audience. Safe to call twice."""
    c = db.one("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    langs = [r["lang"] for r in db.q("SELECT lang FROM variants WHERE campaign_id = ?", (campaign_id,))]
    sql, args = audience.audience_sql(db.jl(c["list_ids"]), db.jl(c["tag_ids"]))
    lang_case = "CASE WHEN co.lang IN (%s) THEN co.lang ELSE ? END" % (",".join("?" * len(langs)) or "''")
    db.run("INSERT OR IGNORE INTO deliveries(campaign_id, contact_id, lang, token) "
           "SELECT ?, co.id, %s, lower(hex(randomblob(16))) FROM contacts co WHERE co.id IN (%s)" % (lang_case, sql),
           [campaign_id] + langs + [c["default_lang"]] + args)
    return db.val("SELECT COUNT(*) FROM deliveries WHERE campaign_id = ?", (campaign_id,), 0)


class Worker:
    def __init__(self, interval=2.0):
        self.interval = interval
        self.sent = deque()
        self.pause_until = 0.0
        self.last_cleanup = 0.0
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.loop, name="koinonia-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("worker tick failed")
                try:
                    db.rollback()
                except Exception:
                    pass
            self.stop_event.wait(self.interval)

    def tick(self):
        self.start_due()
        self.run_automations()
        if time.monotonic() >= self.pause_until:
            self.send_batch()
        self.finish()
        if time.monotonic() - self.last_cleanup > 3600:
            self.cleanup()
            self.last_cleanup = time.monotonic()

    def start_due(self):
        for c in db.q("SELECT id FROM campaigns WHERE kind = 'campaign' AND status = 'scheduled' AND scheduled_at <= ?", (utcnow(),)):
            db.run("UPDATE campaigns SET status = 'sending' WHERE id = ? AND status = 'scheduled'", (c["id"],))
            enqueue(c["id"])
            db.commit()

    def run_automations(self):
        due = db.q("""SELECT e.automation_id, e.contact_id, e.next_position, a.list_id FROM enrollments e
                      JOIN automations a ON a.id = e.automation_id
                      WHERE e.done = 0 AND a.active = 1 AND e.next_at <= ? LIMIT 500""", (utcnow(),))
        for e in due:
            steps = db.q("SELECT * FROM automation_steps WHERE automation_id = ? ORDER BY position, id", (e["automation_id"],))
            ok = db.val("""SELECT 1 FROM contacts c JOIN list_members m ON m.contact_id = c.id
                           WHERE c.id = ? AND c.status = 'active' AND m.list_id = ? AND m.status = 'subscribed'""",
                        (e["contact_id"], e["list_id"]))
            pos = e["next_position"]
            if not ok or pos >= len(steps):
                db.run("UPDATE enrollments SET done = 1 WHERE automation_id = ? AND contact_id = ?", (e["automation_id"], e["contact_id"]))
                continue
            step = steps[pos]
            lang = db.val("SELECT lang FROM contacts WHERE id = ?", (e["contact_id"],), "")
            camp = db.one("SELECT * FROM campaigns WHERE id = ?", (step["campaign_id"],))
            v = compose.variant(camp, lang)
            db.run("INSERT OR IGNORE INTO deliveries(campaign_id, contact_id, lang, token) VALUES (?, ?, ?, lower(hex(randomblob(16))))",
                   (camp["id"], e["contact_id"], v["lang"] if v else camp["default_lang"]))
            if pos + 1 < len(steps):
                nxt = (datetime.now(timezone.utc) + timedelta(days=steps[pos + 1]["delay_days"])).strftime("%Y-%m-%d %H:%M:%S")
                db.run("UPDATE enrollments SET next_position = ?, next_at = ? WHERE automation_id = ? AND contact_id = ?",
                       (pos + 1, nxt, e["automation_id"], e["contact_id"]))
            else:
                db.run("UPDATE enrollments SET next_position = ?, done = 1 WHERE automation_id = ? AND contact_id = ?",
                       (pos + 1, e["automation_id"], e["contact_id"]))
        db.commit()

    def budget(self, cfg):
        try:
            rate = max(1, int(cfg.get("rate_per_minute") or 60))
        except ValueError:
            rate = 60
        now = time.monotonic()
        while self.sent and now - self.sent[0] > 60:
            self.sent.popleft()
        return max(0, rate - len(self.sent))

    def send_batch(self):
        cfg = db.settings()
        n = min(self.budget(cfg), 50)
        if n <= 0:
            return 0
        rows = db.q("""SELECT d.* FROM deliveries d JOIN campaigns c ON c.id = d.campaign_id
                       LEFT JOIN automation_steps s ON s.campaign_id = c.id LEFT JOIN automations a ON a.id = s.automation_id
                       WHERE d.status = 'queued' AND ((c.kind = 'campaign' AND c.status = 'sending') OR (c.kind = 'automation' AND a.active = 1))
                       ORDER BY d.id LIMIT ?""", (n,))
        if not rows:
            return 0
        done, campaigns, caches = 0, {}, {}
        try:
            with mailer.Sender(cfg) as sender:
                for d in rows:
                    contact = db.one("SELECT * FROM contacts WHERE id = ?", (d["contact_id"],)) if d["contact_id"] else None
                    if contact is None or contact["status"] != "active":
                        db.run("UPDATE deliveries SET status = 'skipped' WHERE id = ?", (d["id"],))
                        db.commit()
                        continue
                    if d["campaign_id"] not in campaigns:
                        campaigns[d["campaign_id"]] = db.one("SELECT * FROM campaigns WHERE id = ?", (d["campaign_id"],))
                    camp = campaigns[d["campaign_id"]]
                    try:
                        built = compose.build(camp, d["lang"], contact, d, cfg, link_cache=caches.setdefault(camp["id"], {}))
                        msg = compose.message(built, contact["email"])
                    except Exception as ex:  # a broken campaign must not block the queue
                        log.exception("could not build delivery %s", d["id"])
                        db.run("UPDATE deliveries SET status = 'failed', error = ? WHERE id = ?", (("build: %s" % ex)[:500], d["id"]))
                        db.commit()
                        continue
                    try:
                        sender.send(msg)
                        db.run("UPDATE deliveries SET status = 'sent', sent_at = datetime('now'), error = '' WHERE id = ?", (d["id"],))
                        self.sent.append(time.monotonic())
                        done += 1
                    except mailer.PermanentError as ex:
                        db.run("UPDATE deliveries SET status = 'failed', error = ? WHERE id = ?", (str(ex)[:500], d["id"]))
                        db.run("UPDATE contacts SET status = 'bounced', updated_at = datetime('now') WHERE id = ?", (contact["id"],))
                        audience.log(contact["id"], "bounced", str(ex)[:200])
                    except mailer.MessageError as ex:
                        db.run("UPDATE deliveries SET status = 'failed', error = ? WHERE id = ?", (str(ex)[:500], d["id"]))
                    except mailer.TemporaryError as ex:
                        self._temporary(d, ex)
                        db.commit()
                        return done
                    db.commit()
        except mailer.TemporaryError as ex:  # could not even connect
            self._temporary(rows[0], ex)
            db.commit()
        return done

    def _temporary(self, d, ex):
        attempts = d["attempts"] + 1
        status = "failed" if attempts >= MAX_ATTEMPTS else "queued"
        db.run("UPDATE deliveries SET attempts = ?, status = ?, error = ? WHERE id = ?", (attempts, status, str(ex)[:500], d["id"]))
        self.pause_until = time.monotonic() + min(300, 15 * attempts)
        log.warning("sending paused: %s", ex)

    def finish(self):
        db.run("""UPDATE campaigns SET status = 'sent', sent_at = datetime('now') WHERE kind = 'campaign' AND status = 'sending'
                  AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.campaign_id = campaigns.id AND d.status = 'queued')""")
        db.commit()

    def cleanup(self):
        try:
            days = int(db.setting("retention_days") or 0)
        except ValueError:
            days = 0
        if days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            # Keep the totals, drop the link to the person.
            db.run("UPDATE deliveries SET contact_id = NULL WHERE contact_id IS NOT NULL AND sent_at IS NOT NULL AND sent_at < ?", (cutoff,))
            db.run("DELETE FROM events WHERE at < ? AND type IN ('opened', 'clicked')", (cutoff,))
        db.run("DELETE FROM sessions WHERE expires_at < ?", (utcnow(),))
        db.run("DELETE FROM list_members WHERE status = 'pending' AND updated_at < ?",
               ((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),))
        db.commit()
