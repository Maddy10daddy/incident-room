#!/usr/bin/env python3
"""Register ops-sentinel with a Switch server (once). See docs: The agent protocol.

  SWITCH_API_URL=<bridge base URL> SWITCH_REG_KEY=<registration key> python3 register.py

The registration key is an API key of type `registration`, created on the Gateway's
API Keys page. The agent's own key is written to sentinel/.sentinel.env (mode 600)
and is never printed. Re-running with an existing name fails (409) on purpose,
because overwriting would invalidate the key the sentinel already uses.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

NAME = "ops-sentinel"


def main():
    api, reg = os.environ.get("SWITCH_API_URL"), os.environ.get("SWITCH_REG_KEY")
    if not api or not reg:
        sys.exit("set SWITCH_API_URL and SWITCH_REG_KEY (see the docstring)")
    body = {
        "name": NAME,
        "description": "Watches shop error rates and raises incidents in the room",
        "connector_type": "python-sentinel",
        "integration_profile": {
            "connection_model": "session_passive",  # posts only; nothing can push events to it
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
    }
    req = urllib.request.Request(
        f"{api.rstrip('/')}/agents", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {reg}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"registration failed: HTTP {e.code} {e.read().decode()[:300]}")
    env = Path(__file__).parent / ".sentinel.env"
    env.write_text(f"SWITCH_API_URL={api}\nSWITCH_AGENT_ID={res['id']}\nSWITCH_API_KEY={res['api_key']}\n")
    env.chmod(0o600)
    print(f"registered {NAME} as agent {res['id']}; credentials saved to {env}")
    print("next: add SWITCH_ROOM_ID=<ops-incident room id> to that file and add the agent to the room")


if __name__ == "__main__":
    main()
