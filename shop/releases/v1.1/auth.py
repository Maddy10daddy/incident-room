"""Sign-in and sessions for the shop."""
import hmac
import secrets
from datetime import datetime, timezone

import data

SESSIONS = {}


class AuthError(Exception):
    """Wrong username or password."""


def verify_password(user, password):
    return hmac.compare_digest(data.hash_password(password, user["salt"]), user["pw_hash"])


def create_session(user):
    token = secrets.token_hex(16)
    SESSIONS[token] = user["username"]
    payload = {
        "token": token,
        "user": {
            "username": user["username"],
            "display_name": user["display_name"],
            "previous_login": user["last_login"].isoformat(),
        },
    }
    user["last_login"] = datetime.now(timezone.utc)
    return payload


def login(username, password):
    user = data.USERS.get(username)
    if not user or not verify_password(user, password):
        raise AuthError("invalid credentials")
    return create_session(user)


def user_for_token(token):
    name = SESSIONS.get(token)
    return data.USERS.get(name) if name else None
