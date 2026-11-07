"""Shared helpers: read the service's JSON log and compute error rates."""
import json
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def read_events(log_path, since=None):
    """Return request events (dicts) from the JSON-lines log, oldest first."""
    events = []
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if "ts" not in ev or "status" not in ev:
                    continue
                if since is not None and parse_ts(ev["ts"]) < since:
                    continue
                events.append(ev)
    except FileNotFoundError:
        pass
    return events


def summarize(events):
    """Counts, error rate and the most common error message."""
    total = len(events)
    errors = [e for e in events if e["status"] >= 500]
    top = None
    if errors:
        counts = {}
        for e in errors:
            msg = e.get("error", "unknown error")
            counts[msg] = counts.get(msg, 0) + 1
        top = max(counts.items(), key=lambda kv: kv[1])[0]
    return {
        "total": total,
        "errors": len(errors),
        "rate": (len(errors) / total) if total else 0.0,
        "top_error": top,
        "versions": sorted({e.get("version", "?") for e in events}),
        "first_error_ts": errors[0]["ts"] if errors else None,
    }
