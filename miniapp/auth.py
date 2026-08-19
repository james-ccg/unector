"""
Password hashing (bcrypt), login-session tokens (JWT), and the httpOnly
session/CSRF cookies built on top of them for the Mini App. Kept separate
from the Telegram bot's own logic - this module is only used by
miniapp/api.py.

Session model: the JWT itself is never exposed to JavaScript. It's carried
in an httpOnly cookie (SESSION_COOKIE_NAME), so it can't be read or
exfiltrated by an XSS payload. Because the browser now attaches that cookie
automatically to every same-site request, a second, non-httpOnly cookie
(CSRF_COOKIE_NAME) carries a random token the frontend must echo back in
the X-CSRF-Token header on any state-changing request - the classic
"double-submit cookie" pattern. A cross-site attacker can trick a browser
into sending the session cookie, but can't read the CSRF cookie to also
set the matching header, so the request gets rejected.
"""
import secrets
import time

import bcrypt
import jwt

from config import IS_PRODUCTION, JWT_SECRET_KEY

ALGORITHM = "HS256"
TOKEN_LIFETIME_SECONDS = 60 * 60 * 24 * 7  # 7 days - real login sessions
SHORT_LIVED_SECONDS = 60 * 10  # 10 minutes - 2FA handshake / OAuth state tokens

SESSION_COOKIE_NAME = "fp_session"
CSRF_COOKIE_NAME = "fp_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def create_token(payload: dict, lifetime_seconds: int = TOKEN_LIFETIME_SECONDS) -> str:
    data = dict(payload)
    data["exp"] = int(time.time()) + lifetime_seconds
    return jwt.encode(data, JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def set_session_cookies(response, token: str) -> None:
    """Issues the httpOnly session cookie plus its paired, JS-readable CSRF
    cookie. Call this on every endpoint that hands out a real (non-pending)
    session token."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=TOKEN_LIFETIME_SECONDS,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=secrets.token_urlsafe(32),
        httponly=False,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=TOKEN_LIFETIME_SECONDS,
        path="/",
    )


def clear_session_cookies(response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
