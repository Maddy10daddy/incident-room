import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sentinel"))

from incident_lib import parse_ts, read_events, summarize  # noqa: E402
import sentinel as sn  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Shop:
    """An isolated run dir and port, driving the real deployctl CLI."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.port = free_port()
        self.env = dict(os.environ, INCIDENT_RUN_DIR=self.tmp.name, PORT=str(self.port))
        self.live = Path(self.tmp.name, "live")

    def ctl(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "deployctl.py"), *args],
                              env=self.env, capture_output=True, text=True, cwd=ROOT)

    def login(self, user, password="demo123"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/login",
                                     data=json.dumps({"username": user, "password": password}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def git(self, *a, cwd=None):
        return subprocess.run(["git", *a], cwd=cwd or self.live, capture_output=True, text=True,
                              env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))

    def close(self):
        pid = Path(self.tmp.name, "shop.pid")
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), 15)
            except OSError:
                pass
        self.tmp.cleanup()


class ShopFlow(unittest.TestCase):
    def setUp(self):
        self.s = Shop()
        self.assertEqual(self.s.ctl("init").returncode, 0)

    def tearDown(self):
        self.s.close()

    def test_v10_is_healthy_for_new_and_returning_users(self):
        self.assertEqual(self.s.login("alice"), 200)
        self.assertEqual(self.s.login("erin"), 200)
        self.assertEqual(self.s.login("alice", "wrong"), 401)

    def test_v11_breaks_first_time_sign_in_only(self):
        self.assertEqual(self.s.ctl("push", "v1.1").returncode, 0)
        self.assertEqual(self.s.login("erin"), 500)        # new customer: the bug
        self.assertEqual(self.s.login("alice"), 200)       # returning customer: fine
        top = summarize(read_events(Path(self.s.tmp.name, "logs", "shop.log")))["top_error"]
        self.assertIn("AttributeError", top)
        self.assertIn("auth.create_session", top)

    def test_rollback_dry_run_changes_nothing_then_real_rollback_recovers(self):
        self.s.ctl("push", "v1.1")
        dry = self.s.ctl("rollback", "--dry-run")
        self.assertIn("DRY RUN", dry.stdout)
        self.assertEqual(self.s.login("erin"), 500)
        self.assertEqual(self.s.ctl("rollback").returncode, 0)
        self.assertEqual(self.s.login("erin"), 200)
        hist = json.loads(Path(self.s.tmp.name, "deploys.json").read_text())
        self.assertEqual([h["action"] for h in hist], ["init", "push", "rollback"])

    def _write_fix_branch(self, with_test):
        """What the fixer agent does: a branch in a worktree, never the live checkout."""
        wt = Path(self.s.tmp.name, "work")
        self.s.git("worktree", "add", str(wt), "-b", "fix/first-login")
        shutil_src = ROOT / "shop" / "releases" / "v1.1.1"
        (wt / "auth.py").write_text((shutil_src / "auth.py").read_text())
        (wt / "VERSION").write_text("v1.1.1\n")
        if with_test:
            (wt / "tests" / "test_auth.py").write_text((shutil_src / "tests" / "test_auth.py").read_text())
        self.s.git("add", "-A", cwd=wt)
        self.s.git("commit", "-m", "fix first sign-in", cwd=wt)

    def test_fix_forward_via_branch_merge(self):
        self.s.ctl("push", "v1.1")
        self._write_fix_branch(with_test=True)
        self.assertEqual(self.s.login("erin"), 500, "live site must be untouched while the branch exists")
        dry = self.s.ctl("merge", "fix/first-login", "--dry-run")
        self.assertIn("PASS", dry.stdout)
        self.assertEqual(self.s.login("erin"), 500, "dry run must not deploy")
        self.assertEqual(self.s.ctl("merge", "fix/first-login").returncode, 0)
        self.assertEqual(self.s.login("erin"), 200)
        self.assertEqual((self.s.live / "VERSION").read_text().strip(), "v1.1.1")

    def test_merge_refuses_a_branch_with_failing_tests(self):
        self.s.ctl("push", "v1.1")
        wt = Path(self.s.tmp.name, "work")
        self.s.git("worktree", "add", str(wt), "-b", "fix/bad")
        (wt / "tests" / "test_auth.py").write_text(
            (wt / "tests" / "test_auth.py").read_text() + "\n\nclass Broken(unittest.TestCase):\n"
            "    def test_fails(self):\n        self.fail('nope')\n")
        self.s.git("add", "-A", cwd=wt)
        self.s.git("commit", "-m", "bad", cwd=wt)
        r = self.s.ctl("merge", "fix/bad")
        self.assertEqual(r.returncode, 3)
        self.assertIn("refusing to merge", r.stdout)
        self.assertEqual(self.s.login("erin"), 500)

    def test_unknown_release_rejected(self):
        self.assertNotEqual(self.s.ctl("push", "v9.9").returncode, 0)


def ev(offset_s, status, now, err=None, version="v1.1"):
    d = {"ts": (now - timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "status": status, "version": version}
    if err:
        d["error"] = err
    return d


class SentinelLogic(unittest.TestCase):
    now = parse_ts("2026-11-04T10:00:00Z")

    def test_quiet_traffic_no_alert(self):
        self.assertFalse(sn.evaluate([ev(i, 200, self.now) for i in range(20)])["breached"])

    def test_too_little_traffic_no_alert(self):
        self.assertFalse(sn.evaluate([ev(i, 500, self.now, "boom") for i in range(3)])["breached"])

    def test_401s_are_not_incidents(self):
        self.assertFalse(sn.evaluate([ev(i, 401, self.now) for i in range(20)])["breached"])

    def test_alert_once_then_recovery(self):
        posts = []
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            (run / "logs").mkdir()
            log = run / "logs" / "shop.log"
            (run / "deploys.json").write_text(json.dumps(
                [{"version": "v1.1", "action": "push", "at": "2026-11-04T09:40:00Z"}]))
            bad = [ev(i, 500 if i % 2 else 200, self.now, "AttributeError: x in auth.create_session")
                   for i in range(20)]
            log.write_text("\n".join(json.dumps(e) for e in bad) + "\n")
            s = sn.Sentinel(posts.append, run)
            s.tick(self.now)
            s.tick(self.now)
            self.assertEqual(len(posts), 1)
            self.assertIn("@ops-triager ALERT", posts[0])
            self.assertIn("v1.1", posts[0])
            log.write_text("\n".join(json.dumps(ev(i, 200, self.now, version="v1.1.1")) for i in range(20)) + "\n")
            s.tick(self.now)
            self.assertEqual(len(posts), 2)
            self.assertIn("RECOVERED", posts[1])


if __name__ == "__main__":
    unittest.main()
