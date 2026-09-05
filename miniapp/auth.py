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
import hashlib
import hmac
import secrets
import time

import bcrypt
import jwt

from config import IS_PRODUCTION, JWT_SECRET_KEY

ALGORITHM = "HS256"
TOKEN_LIFETIME_SECONDS = 60 * 60 * 24 * 7  # 7 days - real login sessions
SHORT_LIVED_SECONDS = 60 * 10  # 10 minutes - 2FA handshake / OAuth state tokens

# The __Host- prefix pins a cookie to this exact origin: no subdomain can
# set it, overwrite it, or widen its path. That is precisely the attack the
# double-submit CSRF pattern otherwise falls to - see csrf_token_for below.
# The prefix requires Secure and Path=/, so it can only be used where the
# app is actually on HTTPS, which is why local dev keeps the bare names.
_HOST_PREFIX = "__Host-" if IS_PRODUCTION else ""
SESSION_COOKIE_NAME = f"{_HOST_PREFIX}un_session"
CSRF_COOKIE_NAME = f"{_HOST_PREFIX}un_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

# Every token this module mints carries one of these in its `purpose` claim,
# and whoever accepts a token names the purpose it will accept.
#
# They are all signed with the same key, so without this a token issued for
# one job is a valid token for another. The 2FA handshake token was the
# dangerous case: the login endpoint returns it to the caller *before* any
# second factor has been given, and the session check only verified the
# signature - so setting it as un_session skipped 2FA outright. The OAuth
# `state` tokens are the same shape of problem, and they travel through a
# third party in a URL.
SESSION_PURPOSE = "session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def create_token(payload: dict, lifetime_seconds: int = TOKEN_LIFETIME_SECONDS) -> str:
    """Signs a token. `payload` must carry a `purpose` - see SESSION_PURPOSE.

    Required rather than defaulted so a new token cannot be added without
    deciding what it is for: a token with no purpose is accepted by whoever
    happens to be least strict."""
    data = dict(payload)
    if not data.get("purpose"):
        raise ValueError("create_token: every token needs a `purpose` claim")
    data["exp"] = int(time.time()) + lifetime_seconds
    return jwt.encode(data, JWT_SECRET_KEY, algorithm=ALGORITHM)


def create_session_token(claims: dict) -> str:
    """A real login session, for set_session_cookies.

    `sid` is a fresh random id for this particular login. The CSRF token is
    bound to it, so a token minted for one session cannot be replayed
    against another - and a re-login invalidates the old pairing."""
    return create_token({
        **claims,
        "purpose": SESSION_PURPOSE,
        "sid": secrets.token_urlsafe(18),
    })


def _csrf_digest(session_id: str, random_value: str) -> str:
    # Length-prefixed so ("ab", "cd") and ("a", "bcd") cannot hash alike.
    message = f"{len(session_id)}!{session_id}!{random_value}".encode()
    return hmac.new(JWT_SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def csrf_token_for(session_id: str) -> str:
    """A CSRF token tied to one session.

    The plain double-submit pattern - put a random value in a cookie, make
    the client echo it in a header, check they match - is only as strong as
    the attacker's inability to write cookies on the domain. A vulnerable
    sibling subdomain, a DNS takeover or a plaintext-HTTP injection defeats
    it, because the attacker sets both halves themselves and they agree.

    OWASP's signed variant closes that: the cookie carries an HMAC over the
    session id, keyed by a server-side secret. An attacker who can write
    cookies still cannot produce a value that verifies against the victim's
    session."""
    random_value = secrets.token_hex(32)
    return f"{_csrf_digest(session_id, random_value)}.{random_value}"


def csrf_token_matches(token: str, session_id: str) -> bool:
    """Whether `token` was issued for this session. Constant-time."""
    digest, _, random_value = token.partition(".")
    if not digest or not random_value:
        return False
    return hmac.compare_digest(digest, _csrf_digest(session_id, random_value))


def decode_token(token: str, purpose: str | None = None) -> dict | None:
    """Verifies signature and expiry, and - when `purpose` is given - that
    the token was minted for that job. Pass it wherever the token's purpose
    is known, which is everywhere except the two callbacks that read the
    purpose out in order to decide what to do next."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if purpose is not None and payload.get("purpose") != purpose:
        return None
    return payload


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
    # Bound to this session's `sid`, so it is useless against any other.
    claims = decode_token(token, purpose=SESSION_PURPOSE) or {}
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token_for(claims.get("sid", "")),
        httponly=False,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=TOKEN_LIFETIME_SECONDS,
        path="/",
    )


# Which Google account this browser last signed in with. Set on the way out
# so that coming back is one click rather than picking your own address off
# a list again, and read only to build Google's `login_hint`.
#
# httpOnly on purpose: nothing on the page needs to read it, and an address
# that no script can reach is one an XSS payload cannot harvest either. It
# is a convenience, so it expires on its own - a browser nobody has signed
# in from for a month should not still be volunteering who used it.
LAST_ACCOUNT_COOKIE_NAME = f"{_HOST_PREFIX}un_last_account"
LAST_ACCOUNT_LIFETIME_SECONDS = 60 * 60 * 24 * 30


def remember_last_account(response, email: str) -> None:
    if not email:
        return
    response.set_cookie(
        key=LAST_ACCOUNT_COOKIE_NAME,
        value=email,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=LAST_ACCOUNT_LIFETIME_SECONDS,
        path="/",
    )


def forget_last_account(response) -> None:
    """For "use a different account" - the hint has to be droppable, or it
    stops being a convenience and becomes something you cannot get out of."""
    response.delete_cookie(LAST_ACCOUNT_COOKIE_NAME, path="/")


def clear_session_cookies(response) -> None:
    """Signs the browser out. The last-account hint deliberately survives:
    remembering who just left is the whole point of it."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
