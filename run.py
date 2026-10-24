#!/usr/bin/env python3
"""Start Koinonia:  python3 run.py  [--host 0.0.0.0] [--port 8080] [--db data/koinonia.db]"""
import argparse
import logging
import socketserver
import sys
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

if sys.version_info < (3, 9):
    sys.exit("Koinonia needs Python 3.9 or newer.")

from koinonia import app as appmod  # noqa: E402
from koinonia.worker import Worker  # noqa: E402


class ThreadingServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        logging.getLogger("koinonia.http").debug(fmt, *args)


def main():
    p = argparse.ArgumentParser(description="Koinonia — free email for churches and Christian organisations")
    p.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--db", default=None, help="path to the SQLite database file")
    p.add_argument("--no-worker", action="store_true", help="do not start the background sender")
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    application = appmod.create_app(a.db)
    if not a.no_worker:
        Worker().start()
    server = make_server(a.host, a.port, application, server_class=ThreadingServer, handler_class=QuietHandler)
    print("Koinonia is running at http://%s:%d  (stop with Ctrl+C)" % ("localhost" if a.host in ("127.0.0.1", "0.0.0.0") else a.host, a.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGoodbye. God bless!")


if __name__ == "__main__":
    main()
