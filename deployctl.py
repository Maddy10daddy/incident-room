#!/usr/bin/env python3
"""deployctl: run, update, fix and roll back the shop. The live site is a real git repo.

  init                       reset: fresh live repo at v1.0, site running
  push <release>             deploy a release from shop/releases/ as a new commit (e.g. v1.1)
  rollback [--dry-run]       git revert HEAD on main, restart
  merge <branch> [--dry-run] fast-forward main to <branch> ONLY if its tests pass, restart
  status | history | verify [--window 30]

State lives in run/ (override INCIDENT_RUN_DIR). Site port: PORT (default 8081).
The live repo is run/live. Agents change code on a branch in a git worktree, never in run/live.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

from incident_lib import now_iso, parse_ts, read_events, summarize

ROOT = Path(__file__).resolve().parent
RUN = Path(os.environ.get("INCIDENT_RUN_DIR", ROOT / "run"))
LIVE = RUN / "live"
LOG = RUN / "logs" / "shop.log"
HIST = RUN / "deploys.json"
PIDFILE = RUN / "shop.pid"
PORT = int(os.environ.get("PORT", "8081"))
APP, RELEASES = ROOT / "shop" / "app", ROOT / "shop" / "releases"
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="deployctl", GIT_AUTHOR_EMAIL="deploy@local",
               GIT_COMMITTER_NAME="deployctl", GIT_COMMITTER_EMAIL="deploy@local")


def git(*args, cwd=None, check=True):
    r = subprocess.run(["git", *args], cwd=cwd or LIVE, env=GIT_ENV, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def current_version():
    try:
        return (LIVE / "VERSION").read_text().strip()
    except FileNotFoundError:
        return None


def history():
    try:
        return json.loads(HIST.read_text())
    except (FileNotFoundError, ValueError):
        return []


def record(action, **extra):
    h = history()
    h.append(dict(version=current_version(), action=action, at=now_iso(),
                  commit=git("rev-parse", "--short", "HEAD"), **extra))
    HIST.write_text(json.dumps(h, indent=2))


def health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return None


def stop():
    try:
        pid = int(PIDFILE.read_text())
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.1)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        pass
    PIDFILE.unlink(missing_ok=True)


def start():
    (RUN / "logs").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PORT=str(PORT), LOG_FILE=str(LOG))
    proc = subprocess.Popen([sys.executable, str(LIVE / "server.py")], cwd=LIVE, env=env,
                            stdout=subprocess.DEVNULL, stderr=open(RUN / "shop.err", "a"),
                            start_new_session=True)
    PIDFILE.write_text(str(proc.pid))
    for _ in range(60):
        h = health()
        if h and h.get("version") == current_version():
            return True
        time.sleep(0.1)
    return False


def restart():
    stop()
    return start()


def init():
    stop()
    for p in (LIVE, RUN / "logs", HIST):
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    wt = RUN / "work"
    shutil.rmtree(wt, ignore_errors=True)
    RUN.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP, LIVE, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    git("init", "-q", "-b", "main")
    git("config", "user.name", "shop-dev")
    git("config", "user.email", "dev@shop.local")
    (LIVE / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    git("add", "-A")
    git("commit", "-q", "-m", "v1.0: initial shop")
    git("tag", "v1.0")
    ok = start()
    record("init", note="initial shop", healthy=ok)
    print(f"init: shop v1.0 live at http://127.0.0.1:{PORT} ({'healthy' if ok else 'NOT HEALTHY'})")
    return 0 if ok else 1


def push(release):
    src = RELEASES / release
    if not (src / "VERSION").exists():
        sys.exit(f"unknown release {release!r}; have: {', '.join(sorted(p.name for p in RELEASES.iterdir()))}")
    if git("status", "--porcelain"):
        sys.exit("live repo has uncommitted changes; refusing to push")
    shutil.copytree(src, LIVE, dirs_exist_ok=True, ignore=shutil.ignore_patterns("NOTES"))
    note = (src / "NOTES").read_text().strip() if (src / "NOTES").exists() else release
    git("add", "-A")
    git("commit", "-q", "-m", f"{release}: {note}")
    git("tag", "-f", release)
    ok = restart()
    record("push", note=note, healthy=ok)
    print(f"push: {release} deployed ({'healthy' if ok else 'NOT HEALTHY'})")
    return 0 if ok else 1


def rollback(dry_run):
    if int(git("rev-list", "--count", "HEAD")) < 2:
        sys.exit("nothing to roll back to")
    subject, sha = git("log", "-1", "--format=%s"), git("rev-parse", "--short", "HEAD")
    prev = git("show", "HEAD~1:VERSION")
    if dry_run:
        print(f"DRY RUN: would `git revert` {sha} ({subject!r}) on main, restart the shop, "
              f"and wait for /health to report {prev}.\n{git('diff', '--stat', 'HEAD~1', 'HEAD')}")
        return 0
    git("revert", "--no-edit", "HEAD")
    ok = restart()
    record("rollback", note=f"reverted {sha}: {subject}", healthy=ok)
    print(f"rollback: reverted {sha}; now {current_version()} ({'healthy' if ok else 'NOT HEALTHY'})")
    return 0 if ok else 1


def run_branch_tests(branch):
    """Run the branch's committed tests in a clean export of that branch."""
    with tempfile.TemporaryDirectory() as tmp:
        arch = subprocess.run(["git", "archive", branch], cwd=LIVE, capture_output=True)
        if arch.returncode:
            sys.exit(f"unknown branch {branch!r}")
        subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=tmp,
                           capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return r.returncode == 0, (r.stderr or r.stdout).strip().splitlines()[-3:]


def merge(branch, dry_run):
    ok, tail = run_branch_tests(branch)
    stat = git("diff", "--stat", f"main..{branch}")
    print(f"tests on {branch}: {'PASS' if ok else 'FAIL'}  ({' | '.join(tail)})\n{stat}")
    if not ok:
        print("refusing to merge: the branch's tests do not pass")
        return 3
    if dry_run:
        print(f"DRY RUN: would fast-forward main to {branch} and restart the shop")
        return 0
    if git("status", "--porcelain"):
        sys.exit("live repo has uncommitted changes; refusing to merge")
    git("merge", "--ff-only", branch)
    healthy = restart()
    record("merge", note=f"merged {branch}", healthy=healthy)
    git("worktree", "prune", check=False)
    for line in git("worktree", "list", "--porcelain").split("\n\n"):
        if f"branch refs/heads/{branch}" in line:
            path = line.split("\n")[0].replace("worktree ", "")
            git("worktree", "remove", "--force", path, check=False)
    git("branch", "-d", branch, check=False)
    print(f"merge: {branch} is live as {current_version()} ({'healthy' if healthy else 'NOT HEALTHY'})")
    return 0 if healthy else 1


def verify(window):
    since = parse_ts(now_iso()) - timedelta(seconds=window)
    s = summarize(read_events(LOG, since=since))
    h = health()
    s["running_version"] = h["version"] if h else None
    print(json.dumps(s, indent=2))
    if not h:
        print("FAIL: shop not healthy")
        return 1
    if s["total"] < 5:
        print("INSUFFICIENT_DATA: fewer than 5 requests in the window; send traffic and retry")
        return 2
    ok = s["rate"] < 0.05
    print(f"{'OK' if ok else 'FAIL'}: error rate {s['rate']:.0%} over the last {window}s")
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="deployctl")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("push").add_argument("release")
    r = sub.add_parser("rollback")
    r.add_argument("--dry-run", action="store_true")
    m = sub.add_parser("merge")
    m.add_argument("branch")
    m.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    sub.add_parser("history")
    v = sub.add_parser("verify")
    v.add_argument("--window", type=int, default=30)
    a = p.parse_args(argv)
    if a.cmd == "init":
        return init()
    if a.cmd == "push":
        return push(a.release)
    if a.cmd == "rollback":
        return rollback(a.dry_run)
    if a.cmd == "merge":
        return merge(a.branch, a.dry_run)
    if a.cmd == "status":
        h = health()
        print(json.dumps({"live_repo": str(LIVE), "version": current_version(), "healthy": bool(h),
                          "branch": git("branch", "--show-current") if LIVE.exists() else None,
                          "recent_commits": git("log", "--oneline", "-5").split("\n") if LIVE.exists() else []},
                         indent=2))
        return 0
    if a.cmd == "history":
        print(json.dumps(history(), indent=2))
        return 0
    return verify(a.window)


if __name__ == "__main__":
    sys.exit(main())
