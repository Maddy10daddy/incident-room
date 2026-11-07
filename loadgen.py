#!/usr/bin/env python3
"""Simulate shoppers signing in. About 8% use a wrong password (a normal 401, not an incident)."""
import argparse
import json
import os
import random
import time
import urllib.error
import urllib.request

NAMES = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi", "ivan", "judy", "ken", "lena"]


def attempt(port):
    body = {"username": random.choice(NAMES),
            "password": "wrong" if random.random() < 0.08 else "demo123"}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/login", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except (urllib.error.URLError, OSError):
        pass  # 401s, 500s and refused connections are all expected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8081")))
    ap.add_argument("--rps", type=float, default=5)
    ap.add_argument("--seconds", type=float, default=0, help="0 = run until killed")
    a = ap.parse_args()
    end = time.time() + a.seconds if a.seconds else None
    while end is None or time.time() < end:
        attempt(a.port)
        time.sleep(1 / a.rps)


if __name__ == "__main__":
    main()
