#!/usr/bin/env python3
"""Ops panel: a live view of the shop plus the demo controls. http://localhost:8090

Reads run/logs/shop.log, run/deploys.json and run/alerts.jsonl. Buttons call deployctl.
"""
import json
import os
import signal
import subprocess
import sys
import urllib.request
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from incident_lib import now_iso, parse_ts, read_events, summarize  # noqa: E402

RUN = Path(os.environ.get("INCIDENT_RUN_DIR", ROOT / "run"))
SHOP_PORT = int(os.environ.get("PORT", "8081"))
PANEL_PORT = int(os.environ.get("PANEL_PORT", "8090"))
BUCKET_S, BUCKETS = 5, 48  # 4 minutes of history


def shop_health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{SHOP_PORT}/health", timeout=1.5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def traffic_pid():
    try:
        pid = int((RUN / "loadgen.pid").read_text())
        os.kill(pid, 0)
        return pid
    except (FileNotFoundError, ValueError, OSError):
        return None


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def status():
    now = parse_ts(now_iso())
    events = read_events(RUN / "logs" / "shop.log", since=now - timedelta(seconds=BUCKET_S * BUCKETS))
    recent = [e for e in events if parse_ts(e["ts"]) >= now - timedelta(seconds=30)]
    s = summarize(recent)
    buckets = [{"total": 0, "errors": 0} for _ in range(BUCKETS)]
    for e in events:
        age = (now - parse_ts(e["ts"])).total_seconds()
        i = BUCKETS - 1 - int(age // BUCKET_S)
        if 0 <= i < BUCKETS:
            buckets[i]["total"] += 1
            buckets[i]["errors"] += 1 if e["status"] >= 500 else 0
    errors = [e for e in events if e["status"] >= 500][-6:]
    h = shop_health()
    alerts = []
    try:
        alerts = [json.loads(l) for l in (RUN / "alerts.jsonl").read_text().splitlines() if l][-6:]
    except (FileNotFoundError, ValueError):
        pass
    state = "down" if not h else ("degraded" if s["total"] >= 10 and s["rate"] >= 0.2 else "healthy")
    return {"state": state, "version": h["version"] if h else None, "window": s, "buckets": buckets,
            "bucket_s": BUCKET_S, "recent_errors": [{"ts": e["ts"], "error": e.get("error", ""), "version": e["version"]}
                                                    for e in errors],
            "deploys": read_json(RUN / "deploys.json", [])[-8:], "alerts": alerts,
            "traffic": bool(traffic_pid())}


def ctl(*args):
    r = subprocess.run([sys.executable, str(ROOT / "deployctl.py"), *args], capture_output=True, text=True,
                       cwd=ROOT, env=dict(os.environ, INCIDENT_RUN_DIR=str(RUN), PORT=str(SHOP_PORT)))
    return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()[-400:]}


def set_traffic(on):
    pid = traffic_pid()
    if on and not pid:
        RUN.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen([sys.executable, str(ROOT / "loadgen.py"), "--port", str(SHOP_PORT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        (RUN / "loadgen.pid").write_text(str(p.pid))
    if not on and pid:
        os.kill(pid, signal.SIGTERM)
        (RUN / "loadgen.pid").unlink(missing_ok=True)
    return {"ok": True, "traffic": bool(traffic_pid())}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, (Path(__file__).parent / "panel.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self._send(200, status())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/push" and body.get("release") in ("v1.1", "v1.1.1"):
            return self._send(200, ctl("push", body["release"]))
        if self.path == "/api/traffic":
            return self._send(200, set_traffic(bool(body.get("on"))))
        if self.path == "/api/reset":
            set_traffic(False)
            res = ctl("init")
            set_traffic(True)
            (RUN / "alerts.jsonl").unlink(missing_ok=True)
            return self._send(200, res)
        self._send(400, {"error": "bad request"})


if __name__ == "__main__":
    print(f"ops panel on http://localhost:{PANEL_PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PANEL_PORT), Handler).serve_forever()
