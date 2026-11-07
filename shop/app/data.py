"""In-memory demo users. Everyone's password is `demo123`.

The first four are returning customers (they have a last_login). The other eight are
new accounts that have never signed in, so last_login is None until their first login.
"""
import hashlib
from datetime import datetime, timedelta, timezone

NAMES = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi", "ivan", "judy", "ken", "lena"]
PASSWORD = "demo123"


def hash_password(password, salt):
    return hashlib.sha256((salt + password).encode()).hexdigest()


def build_users():
    users = {}
    for i, name in enumerate(NAMES):
        users[name] = {
            "username": name,
            "display_name": name.capitalize(),
            "salt": name,
            "pw_hash": hash_password(PASSWORD, name),
            "last_login": (datetime.now(timezone.utc) - timedelta(days=1 + i)) if i < 4 else None,
        }
    return users


USERS = build_users()
