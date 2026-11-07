#!/usr/bin/env python3
"""Marigold Market backend: serves the site and the sign-in API.

Env: PORT (default 8081), LOG_FILE (JSON lines, one per API request).
"""
import json
import mimetypes
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import auth

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PORT = int(os.environ.get("PORT", "8081"))
LOG_FILE = os.environ.get("LOG_FILE")
VERSION = (HERE / "VERSION").read_text().strip()
_lock = threading.Lock()


def log(**fields):
    fields.update(ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  service="shop", version=VERSION)
    if LOG_FILE:
        with _lock, open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(fields) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _static(self, rel):
        path = (STATIC / rel).resolve()
        if STATIC not in path.parents and path != STATIC or not path.is_file():
            return self._json(404, {"error": "not found"})
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"status": "ok", "version": VERSION})
        if path == "/api/version":
            return self._json(200, {"version": VERSION})
        if path == "/api/me":
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            user = auth.user_for_token(token)
            if not user:
                return self._json(401, {"error": "not signed in"})
            return self._json(200, {"username": user["username"], "display_name": user["display_name"]})
        return self._static("index.html" if path == "/" else path.lstrip("/"))

    def do_POST(self):
        if urlparse(self.path).path != "/api/login":
            return self._json(404, {"error": "not found"})
        t0 = time.time()
        err = None
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            session = auth.login(body.get("username", ""), body.get("password", ""))
            status, out = 200, session
        except auth.AuthError:
            status, out = 401, {"error": "Wrong username or password."}
        except Exception as exc:  # unexpected failure: this is what the incident is made of
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            err = f"{type(exc).__name__}: {exc} in {Path(frame.filename).stem}.{frame.name}"
            status, out = 500, {"error": "Something went wrong on our side. Please try again."}
        fields = {"level": "ERROR" if status >= 500 else "INFO", "path": "/api/login",
                  "status": status, "ms": int((time.time() - t0) * 1000)}
        if err:
            fields["error"] = err
        log(**fields)
        self._json(status, out)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
