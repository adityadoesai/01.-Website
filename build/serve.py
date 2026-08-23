#!/usr/bin/env python3
"""Local preview server for site/. Run: python3 build/serve.py [port]"""
import http.server
import os
import socketserver
import sys

# Resolve without os.getcwd(): the launcher may run from an unreadable cwd.
here = os.path.dirname(__file__) or "."
target = os.path.normpath(os.path.join(here, os.pardir, "site"))
os.chdir(target)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4321


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    sys.stderr.write("serving %s on http://127.0.0.1:%d\n" % (target, PORT))
    httpd.serve_forever()
