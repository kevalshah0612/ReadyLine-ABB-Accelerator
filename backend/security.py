"""Server-side opaque sessions, constant-time password checks, and role enforcement."""

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000)
    return f"{salt}:{derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, expected = stored.split(":")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000)
    return hmac.compare_digest(actual.hex(), expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request):
    from backend.db import now

    token = request.cookies.get("readyline_session", "")
    row = request.app.state.db.one(
        "SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.expires>?",
        (token_hash(token), now()),
    )
    if not row:
        raise HTTPException(401, "Sign in to continue")
    # A custom header prevents cross-site form submissions. SameSite is defense in depth.
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-ReadyLine") != "1":
        raise HTTPException(403, "Missing request protection header")
    return row


def require(user: dict, *roles):
    if user["role"] not in ("admin", *roles):
        raise HTTPException(403, "Your role cannot perform this action")
