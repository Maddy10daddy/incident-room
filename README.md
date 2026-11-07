# Incident Room: an AI on-call team that finds, fixes and ships the bug, with a human holding the key

Flip the Switch hackathon entry (Track 1: Best Business Workflow).

A real web shop breaks after an update. A custom monitoring agent raises the alarm in a Switch
room. Coding agents find the bad commit, **write the fix and a regression test on a branch**,
and prepare the options. The human on-call approves what ships. Nothing reaches the live site
without that approval, and a merge is refused if the branch's tests fail.

```
 [Push update v1.1] ──▶ shop breaks for new customers (real 500s, real log)
                              │
                              ▼
   ops-sentinel (custom agent, Switch agent protocol) ── posts the alert into the room
                              │
   ops-triager ─▶ ops-investigator ─▶ ops-fixer ─▶ ops-release ─▶ HUMAN approves ─▶ merge + deploy
        │          finds the commit     branch,      options:                          tests gate,
        │          and failing line     diff, tests  rollback or fix                   verify 0% errors
        └──────────────────────────── ops-scribe writes the postmortem ◀──────────────┘
```

## What you can see
| URL | What |
|---|---|
| `http://localhost:8081` | **Marigold Market**, the shop. Sign in as `erin` (new customer) or `alice` (returning), password `demo123`. |
| `http://localhost:8090` | **Ops panel**: live error chart, status, deploy timeline, sentinel alerts, latest errors, and the demo buttons (Push update v1.1, Ship prepared fix, Reset). |

## What is real
| Piece | What it does |
|---|---|
| `shop/app/` | The shop: Python backend (`server.py`, `auth.py`, `data.py`) and a plain HTML/CSS/JS front end. Its own tests are in `shop/app/tests/`. |
| `shop/releases/v1.1/` | The "update": a session refactor whose `auth.py` drops one guard, so **first-time sign-ins crash** (`'NoneType' object has no attribute 'isoformat'`). Returning customers still work, which is why it slips through. |
| `shop/releases/v1.1.1/` | The prepared fix plus regression test. A backup for recording; in the demo the **fixer agent writes its own**. |
| `run/live/` | The live site is a **real git repo**. "Push update" is a real commit; a fix is a real branch; rollback is a real `git revert`. |
| `deployctl.py` | `push`, `rollback [--dry-run]`, `merge <branch> [--dry-run]` (fast-forward only, **refuses unless the branch's tests pass**), `verify`, `status`, `history`. |
| `loadgen.py` | Steady shopper traffic, so errors and recovery are real numbers in a real log. 401s from wrong passwords are normal and are not counted as an incident. |
| `sentinel/` | **A custom agent built on Switch's agent protocol.** `register.py` registers it; `sentinel.py` watches the error rate and posts alerts and recoveries into the room via `POST /agents/{id}/message`. One alert per incident. |
| `ops/` | The ops panel (`panel.py`, `panel.html`). |
| `incident-room.template.yaml` | The Switch template: triager, investigator, fixer, release agent, scribe (Claude Code agents) and the room. |
| `tests/` | 10 tests: v1.0 healthy, v1.1 breaks only first sign-ins, rollback dry-run changes nothing, fix-forward via a branch, **merge refuses a failing branch**, sentinel alerts once then recovers. `python3 -m unittest discover -s tests` |

## Why Switch is central
Without Switch there is no shared place where a monitoring agent, five coding agents and a human
hand work to each other and wait on each other. The rooms, agent addressing, the agent protocol
(the sentinel is a non-Claude agent in the same room) and the human approval gate all come from Switch.

## Run it
Prerequisites: Python 3.10+, git, Switch Console with a local server, Claude Code.

1. In Switch Console create the room from `incident-room.template.yaml` (team name `ops`).
2. `./demo.sh up` starts the shop, the panel, traffic and the sentinel. Open both URLs above.
3. *(optional, for live posting)* Register the sentinel: create a registration key on the Gateway's
   API Keys page, then `SWITCH_API_URL=<bridge URL> SWITCH_REG_KEY=<key> python3 sentinel/register.py`,
   add `SWITCH_ROOM_ID=<ops-incident room id>` to `sentinel/.sentinel.env`, and add `ops-sentinel`
   to the room. Without this the sentinel runs in dry-run mode and shows its alerts in the panel.
4. Click **Push update v1.1** in the panel. Within about 30 seconds the shop sign-in fails for
   new customers and the sentinel raises the alert.
5. Let the agents work. When `ops-release` presents the options, reply `@ops-release approve fix`.
6. Backup if an agent stalls: the panel's **Ship prepared fix v1.1.1** (or `./demo.sh fix`).
7. `./demo.sh reset` for a clean second take.

## Demo script (about 2 minutes)
1. Show the healthy shop and panel (green). 2. Click **Push update v1.1**; show a new customer
failing to sign in. 3. The panel goes red and the sentinel posts the alert unprompted.
4. The investigator names the commit and the exact line in `auth.py`. 5. The fixer posts a branch
with a diff and a passing regression test. 6. The release agent offers rollback or ship the fix and
asks you. 7. You approve. 8. The merge runs the tests, deploys, `verify` shows 0% errors, the panel
turns green. 9. The scribe writes the postmortem.

## Status
Shop, panel, deploy tooling, sentinel logic and tests are built and verified locally, including the
panel button, the failing sign-in page and the prepared-fix recovery. The agents' end-to-end run with
the new template (especially the fixer) and live sentinel posting to a Switch server are not tested yet.
