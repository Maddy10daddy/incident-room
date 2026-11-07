#!/usr/bin/env python3
"""ops-sentinel: a custom Switch agent that watches shop and raises the alarm.

It speaks Switch's agent protocol over HTTP: it posts into the incident room with
POST /agents/{agent_id}/message using its own API key. No human has to report the outage.

Config (env, or sentinel/.sentinel.env written by register.py):
  SWITCH_API_URL   agent bridge base URL (the same host `GET /health` answers on)
  SWITCH_AGENT_ID, SWITCH_API_KEY   from register.py
  SWITCH_ROOM_ID   the ops-incident room id
Without these it runs in dry-run mode and prints the alerts instead.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from incident_lib import now_iso, parse_ts, read_events, summarize  # noqa: E402


def evaluate(events, window_s=30, min_requests=10, threshold=0.2):
    """Pure decision function: is the error rate in `events` bad enough to alert?"""
    s = summarize(events)
    s["breached"] = s["total"] >= min_requests and s["rate"] >= threshold
    s["healthy"] = s["total"] >= min_requests and s["rate"] < threshold / 4
    return s


def alert_text(s, window_s, last_deploy, triager):
    dep = (f"last change: {last_deploy['action']} of {last_deploy['version']} at {last_deploy['at']}"
           if last_deploy else "no deploy history found")
    return (f"@{triager} ALERT shop: {s['rate']:.0%} of requests are failing "
            f"({s['errors']}/{s['total']} in the last {window_s}s). Top error: {s['top_error']}. "
            f"First failure seen at {s['first_error_ts']}. Running versions in window: "
            f"{', '.join(s['versions'])}; {dep}. Please investigate. Evidence: run/logs/shop.log "
            f"and `python3 deployctl.py history`.")


def recovery_text(s, window_s):
    return (f"RECOVERED shop: error rate is back to {s['rate']:.0%} "
            f"({s['errors']}/{s['total']} in the last {window_s}s, versions: {', '.join(s['versions'])}).")


class SwitchClient:
    def __init__(self, api_url, agent_id, api_key, room_id):
        self.url = f"{api_url.rstrip('/')}/agents/{agent_id}/message"
        self.key, self.room = api_key, room_id

    def post(self, content):
        req = urllib.request.Request(
            self.url, data=json.dumps({"room_id": self.room, "content": content}).encode(),
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status


def load_env_file(path):
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def last_deploy(run_dir):
    try:
        return json.loads((run_dir / "deploys.json").read_text())[-1]
    except (FileNotFoundError, ValueError, IndexError):
        return None


class Sentinel:
    """State machine: one alert per incident, one message when it clears."""

    def __init__(self, post, run_dir, window=30, min_requests=10, threshold=0.2, triager="ops-triager"):
        self.post, self.run_dir = post, run_dir
        self.window, self.min_requests, self.threshold, self.triager = window, min_requests, threshold, triager
        self.incident_open = False

    def tick(self, now=None):
        now = now or parse_ts(now_iso())
        events = read_events(self.run_dir / "logs" / "shop.log",
                             since=now - timedelta(seconds=self.window))
        s = evaluate(events, self.window, self.min_requests, self.threshold)
        if s["breached"] and not self.incident_open:
            self.incident_open = True
            self.post(alert_text(s, self.window, last_deploy(self.run_dir), self.triager))
        elif self.incident_open and s["healthy"]:
            self.incident_open = False
            self.post(recovery_text(s, self.window))
        return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=0.2)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--run-dir", default=os.environ.get("INCIDENT_RUN_DIR", str(ROOT / "run")))
    a = ap.parse_args()
    load_env_file(Path(__file__).parent / ".sentinel.env")
    need = ["SWITCH_API_URL", "SWITCH_AGENT_ID", "SWITCH_API_KEY", "SWITCH_ROOM_ID"]
    if all(os.environ.get(k) for k in need):
        client = SwitchClient(*(os.environ[k] for k in need))
        post = client.post
        print("sentinel: posting to Switch room", os.environ["SWITCH_ROOM_ID"], flush=True)
    else:
        post = lambda text: print("[dry-run] would post:", text, flush=True)  # noqa: E731
        print("sentinel: Switch env not set, dry-run mode", flush=True)
    run_dir = Path(a.run_dir)
    send = post

    def post(text):  # also keep a local record, which the ops panel displays
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "alerts.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now_iso(), "text": text}) + "\n")
        send(text)

    sentinel = Sentinel(post, run_dir, window=a.window, threshold=a.threshold)
    while True:
        s = sentinel.tick()
        print(f"{now_iso()} total={s['total']} errors={s['errors']} rate={s['rate']:.0%}", flush=True)
        if a.once:
            return
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
