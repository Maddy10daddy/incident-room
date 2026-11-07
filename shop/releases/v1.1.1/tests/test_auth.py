import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auth  # noqa: E402
import data  # noqa: E402


class AuthTests(unittest.TestCase):
    def setUp(self):
        data.USERS.clear()
        data.USERS.update(data.build_users())
        auth.SESSIONS.clear()

    def test_returning_user_can_sign_in(self):
        s = auth.login("alice", "demo123")
        self.assertEqual(s["user"]["username"], "alice")
        self.assertIsNotNone(s["user"]["previous_login"])

    def test_first_sign_in_has_no_previous_login(self):
        s = auth.login("erin", "demo123")  # erin has never signed in
        self.assertIsNone(s["user"]["previous_login"])
        self.assertIsNotNone(data.USERS["erin"]["last_login"])

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(auth.AuthError):
            auth.login("alice", "nope")

    def test_unknown_user_is_rejected(self):
        with self.assertRaises(auth.AuthError):
            auth.login("mallory", "demo123")

    def test_session_token_resolves_to_user(self):
        s = auth.login("bob", "demo123")
        self.assertEqual(auth.user_for_token(s["token"])["username"], "bob")


if __name__ == "__main__":
    unittest.main()
