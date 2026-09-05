"""
Unector Mini App - backend API.

Serves two things:
1. A JSON API for login (owner via MC#+password, dispatcher via username+password)
   and driver management (list, toggle subscription, add dispatcher).
2. The React frontend (frontend/dist/) at the same origin, so the
   Mini App is a single deployable unit.

Run locally:
    uvicorn miniapp.api:app --reload --port 8000

To open inside Telegram, this needs to be reachable over public HTTPS - use
a tool like ngrok during development (`ngrok http 8000`), then register that
URL with @BotFather (see README's Mini App section) and set MINIAPP_URL in .env.
"""
import os
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import (
    FORCE_HTTPS,
    FRONTEND_URL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    IS_PRODUCTION,
    MAPBOX_TOKEN,
    PLAN_LIMITS,
    DISPATCHER_LIMITS,
    SAMSARA_TEST_MODE,
    TURNSTILE_SECRET_KEY,
    TURNSTILE_SITE_KEY,
    TRUST_PROXY_HEADERS,
    encrypt_value,
)
from db.database import init_db
from db.repository import (
    create_dispatcher,
    create_driver,
    get_company,
    get_company_by_mc,
    get_company_billing_info,
    set_company_password,
    get_dispatcher_by_username,
    get_dispatchers_by_company,
    get_drivers_by_company,
    get_driver_details,
    get_fleet_status,
    toggle_driver_subscription,
    current_week_start_utc,
    GROSS_ELIGIBLE_STATUSES,
    list_alert_rules,
    create_alert_rule,
    update_alert_rule,
    delete_alert_rule,
    save_company_credential,
    get_company_credential,
    delete_company_credential,
)
from miniapp.auth import (
    CSRF_COOKIE_NAME,
    LAST_ACCOUNT_COOKIE_NAME,
    SESSION_PURPOSE,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    SHORT_LIVED_SECONDS,
    clear_session_cookies,
    create_session_token,
    create_token,
    csrf_token_matches,
    decode_token,
    forget_last_account,
    hash_password,
    remember_last_account,
    set_session_cookies,
    verify_password,
)
# Imported at module level, not inside a function, because the change-recording
# middleware below runs on every request and cannot pay for an import each time.
from services import change_log, notification_service

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Unector Mini App API", lifespan=_lifespan)

# Brute-force / abuse protection on auth and OTP endpoints. In-memory storage
# is fine for this single-process deployment - no Redis needed.
def _rate_limit_key(request: Request) -> str:
    """Who is being rate limited.

    get_remote_address reads the socket's peer, which behind a proxy is the
    proxy for every caller alike - one shared bucket, so one attacker locks
    everyone out and their own attempts are never counted separately. The
    left-most X-Forwarded-For entry is the original client, but it is
    client-supplied and forgeable, so it is only believed when the
    deployment says a proxy it controls is actually in front (see
    TRUST_PROXY_HEADERS in config.py).
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        client = forwarded.split(",")[0].strip()
        if client:
            return client
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if FORCE_HTTPS:
    from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
    app.add_middleware(HTTPSRedirectMiddleware)


# CSP is scoped to what this app actually loads: same-origin everything,
# plus Google Fonts (index.css's @import) and Cloudflare Turnstile (the
# bot-protection widget, itself only active once configured).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://challenges.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    # Map tiles are images from other origins, and this said 'self' only -
    # so on a production deploy (where this app serves the page and this
    # header) every tile was blocked and the map rendered empty. It never
    # showed in development because Vite serves the page without this CSP.
    "img-src 'self' data: https://tile.openstreetmap.org https://tiles.maps.eox.at "
    "https://api.mapbox.com; "
    "object-src 'none'; "
    "frame-src https://challenges.cloudflare.com; "
    "connect-src 'self' https://challenges.cloudflare.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


# Comfortably above the largest legitimate body - the avatar data URL, which
# its own validator caps - and far below anything that would hurt. Pydantic
# only sees the body after Starlette has read it into memory, so a per-field
# length check does not help against someone posting a gigabyte.
MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """Rejects an oversized body before it is read.

    Content-Length is the client's own claim, so this is not a hard
    guarantee against a chunked upload - it stops the ordinary case cheaply,
    and the reverse proxy in front of a real deployment should set its own
    limit as the backstop (nginx client_max_body_size, or the platform's
    equivalent)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body too large (max {MAX_REQUEST_BODY_BYTES // (1024 * 1024)}MB)"},
        )
    return await call_next(request)


@app.middleware("http")
async def record_changes(request: Request, call_next):
    """Tells the company about any request that changed one of its records.

    Here rather than in each endpoint on purpose - see services/change_log.py
    for why. The short version: a notify() call per endpoint is a promise
    that quietly stops being true the first time somebody adds an endpoint
    and forgets, and "we will tell you when anything changes" is a bad
    promise to keep only most of the time.

    Only successful requests count. A 4xx changed nothing, and telling
    somebody their record was edited when it was not is worse than silence.
    Nothing in here may fail the request either: the change has already been
    made and answered for by the time this runs, so a notification that
    cannot be sent is logged and dropped.
    """
    response = await call_next(request)

    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return response
    if not (200 <= response.status_code < 300):
        return response

    try:
        matched = change_log.match(request.method, request.url.path)
        if not matched:
            return response

        token = request.cookies.get(SESSION_COOKIE_NAME)
        claims = decode_token(token, purpose=SESSION_PURPOSE) if token else None
        company_id = (claims or {}).get("company_id")
        if not company_id:
            return response

        event_key, title, link = matched
        who = change_log.actor_name(claims)
        notification_service.notify(
            company_id, event_key,
            title=title,
            body=f"Changed by {who}." if who else None,
            link=link,
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "Couldn't record a change for %s %s", request.method, request.url.path
        )

    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = _CSP
    if IS_PRODUCTION:
        # Only sent over an actual HTTPS deployment - meaningless (and
        # potentially confusing) to send during plain-http local dev.
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response

# The frontend is served from the same origin as this API in production
# (frontend/dist is mounted below), and Vite's dev-server proxy makes it
# same-origin in development too - so credentialed cross-origin requests
# are a defense-in-depth measure, not the primary path. allow_credentials
# requires an explicit origin list; "*" is not permitted with it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Request/response schemas
# ------------------------------------------------------------------
class RegisterRequest(BaseModel):
    mc_number: str
    company_name: str
    email: EmailStr
    password: str
    confirm_password: str
    turnstile_token: str | None = None
    # From /api/auth/register/gmail/callback, once that inbox has been
    # verified (code or link) - see PendingRegistration's docstring. Optional
    # so existing integrations/tests that never touch the Gmail-first flow
    # keep working exactly as before; the real frontend flow always sends one.
    pending_token: str | None = None

    @field_validator("mc_number")
    @classmethod
    def _mc_number_digits(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or not (1 <= len(v) <= 20):
            raise ValueError("MC number must contain only digits")
        return v

    @field_validator("company_name")
    @classmethod
    def _company_name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Company name is required")
        return v


class OwnerLoginRequest(BaseModel):
    mc_number: str
    password: str
    turnstile_token: str | None = None


class DispatcherLoginRequest(BaseModel):
    username: str
    password: str
    turnstile_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    mc_number: str
    turnstile_token: str | None = None


class RegistrationVerificationRequest(BaseModel):
    pending_token: str


class VerifyRegistrationCodeRequest(BaseModel):
    pending_token: str
    code: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def _password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be 72 bytes or fewer (most passwords qualify).")
        return v


class CreateDispatcherRequest(BaseModel):
    username: str
    password: str


class UpdateDispatcherRequest(BaseModel):
    username: str | None = None
    password: str | None = None


class CreateDriverRequest(BaseModel):
    full_name: str

    @field_validator("full_name")
    @classmethod
    def _full_name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Driver name is required")
        if len(v) > 150:
            raise ValueError("Driver name must be 150 characters or fewer")
        return v


class SubscriptionToggleRequest(BaseModel):
    active: bool


class DispatcherSummary(BaseModel):
    id: int
    username: str
    role: str
    created_at: str | None
    avatar: str | None = None


class TwoFaStatusResponse(BaseModel):
    totp_enabled: bool
    email_otp_enabled: bool
    contact_email: str | None
    sms_otp_enabled: bool
    phone_number: str | None
    telegram_otp_enabled: bool
    telegram_linked: bool
    webauthn_count: int
    recovery_codes_remaining: int
    any_enabled: bool


class ConnectSamsaraRequest(BaseModel):
    api_key: str

    @field_validator("api_key")
    @classmethod
    def _api_key_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("API key is required")
        return v


class CheckoutRequest(BaseModel):
    tier: str  # "pro" | "max_5x" | "max_20x"
    interval: str  # "month" | "year"

    @field_validator("tier")
    @classmethod
    def _valid_tier(cls, v: str) -> str:
        if v not in ("pro", "max_5x", "max_20x"):
            raise ValueError("tier must be one of: pro, max_5x, max_20x")
        return v

    @field_validator("interval")
    @classmethod
    def _valid_interval(cls, v: str) -> str:
        if v not in ("month", "year"):
            raise ValueError("interval must be 'month' or 'year'")
        return v


ALERT_SCENARIOS = ("pu_near", "del_near")


class AlertRuleCreateRequest(BaseModel):
    scenario: str  # "pu_near" | "del_near"
    distance_miles: float
    message_template: str | None = None
    enabled: bool = True

    @field_validator("scenario")
    @classmethod
    def _valid_scenario(cls, v: str) -> str:
        if v not in ALERT_SCENARIOS:
            raise ValueError(f"scenario must be one of {ALERT_SCENARIOS}")
        return v

    @field_validator("distance_miles")
    @classmethod
    def _distance_in_range(cls, v: float) -> float:
        if not (0 < v <= 500):
            raise ValueError("distance_miles must be greater than 0 and at most 500")
        return v

    @field_validator("message_template")
    @classmethod
    def _template_reasonable_length(cls, v: str | None) -> str | None:
        v = (v or "").strip() or None
        if v and len(v) > 500:
            raise ValueError("message_template must be 500 characters or fewer")
        return v


class AlertRuleUpdateRequest(BaseModel):
    distance_miles: float | None = None
    message_template: str | None = None
    enabled: bool | None = None

    @field_validator("distance_miles")
    @classmethod
    def _distance_in_range(cls, v: float | None) -> float | None:
        if v is not None and not (0 < v <= 500):
            raise ValueError("distance_miles must be greater than 0 and at most 500")
        return v

    @field_validator("message_template")
    @classmethod
    def _template_reasonable_length(cls, v: str | None) -> str | None:
        v = (v or "").strip() or None
        if v and len(v) > 500:
            raise ValueError("message_template must be 500 characters or fewer")
        return v


# ------------------------------------------------------------------
# Auth helpers
#
# The session token lives in an httpOnly cookie (never touched by frontend
# JS), so get_current_user reads it from there instead of an Authorization
# header. Because the browser now attaches that cookie automatically,
# state-changing endpoints additionally require verify_csrf, which checks
# the double-submit CSRF cookie against a matching request header - see
# miniapp/auth.py's module docstring for the full threat model.
# ------------------------------------------------------------------
def get_current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(401, "You're not signed in. Log in to continue.")
    # SESSION_PURPOSE, explicitly: the 2FA handshake token, the OAuth state
    # tokens and the password-reset token are all signed with the same key,
    # and without this any of them authenticated as a full session. The 2FA
    # one is handed to the caller before the second factor is given.
    payload = decode_token(token, purpose=SESSION_PURPOSE)
    if not payload:
        raise HTTPException(401, "Your session has ended. Log in again to pick up where you left off.")
    return payload


def require_owner(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "owner":
        raise HTTPException(403, "Only the company owner can do this. Ask them to make the change.")
    return user


def _gmail_connected_field(role: str, company_id: int) -> dict:
    """Owners must connect Gmail as part of onboarding (the bot's core
    feature - pulling rate confirmations - depends on it); dispatchers
    can't manage integrations themselves, so this is owner-only. Returned
    as a dict to splat into a response body, not baked into the JWT
    itself, since connection status can change independently of the
    session's lifetime."""
    if role != "owner":
        return {}
    return {"gmail_connected": bool(get_company_credential(company_id, "gmail_refresh_token"))}


def verify_csrf(request: Request) -> None:
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_value or not header_value:
        raise HTTPException(403, "This page has been open too long to submit safely. Reload it and try again.")
    # compare_digest rather than != so the comparison does not leak the
    # matching prefix length through timing.
    if not hmac.compare_digest(cookie_value, header_value):
        raise HTTPException(403, "This page has been open too long to submit safely. Reload it and try again.")

    # The halves agreeing only proves whoever sent them controls both, which
    # an attacker who can write cookies on the domain does. The token is an
    # HMAC over this session's id, so check it actually belongs to the
    # session being used - see csrf_token_for in miniapp/auth.py.
    #
    # A missing or unreadable session fails here rather than being waved
    # through. Every endpoint that asks for CSRF also asks for a session,
    # so this cannot reject a legitimate request - and skipping the binding
    # whenever the session was absent left the weaker half of the check
    # standing alone, which is a trap for whoever adds the first
    # CSRF-without-auth endpoint.
    session = request.cookies.get(SESSION_COOKIE_NAME)
    claims = decode_token(session, purpose=SESSION_PURPOSE) if session else None
    if not claims:
        raise HTTPException(403, "You're not signed in. Log in and try again.")
    if not csrf_token_matches(cookie_value, claims.get("sid", "")):
        raise HTTPException(403, "This page belongs to an earlier sign-in. Reload it and try again.")


# ------------------------------------------------------------------
# Cloudflare Turnstile - bot protection on register/login. No-ops if
# TURNSTILE_SECRET_KEY isn't set in .env, so the app keeps working
# normally until real keys are configured.
# ------------------------------------------------------------------
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile(token: str | None, remote_ip: str | None) -> None:
    if not TURNSTILE_SECRET_KEY:
        return
    if not token:
        raise HTTPException(400, "Couldn't confirm you're not a bot. Try again.")

    import requests

    try:
        resp = requests.post(
            TURNSTILE_VERIFY_URL,
            data={"secret": TURNSTILE_SECRET_KEY, "response": token, "remoteip": remote_ip or ""},
            timeout=5,
        )
        result = resp.json()
    except Exception:
        import logging
        logging.exception("Turnstile verification request failed")
        raise HTTPException(503, "The bot check is unreachable right now. Try again in a moment.")

    if not result.get("success"):
        raise HTTPException(400, "Couldn't confirm you're not a bot. Try again.")


@app.get("/api/public/config")
def get_public_config():
    """Tells the frontend whether to render the Turnstile widget at all,
    and with which site key - the secret key never leaves the backend."""
    return {"turnstile_site_key": TURNSTILE_SITE_KEY, "mapbox_token": MAPBOX_TOKEN}


@app.post("/api/auth/register")
@limiter.limit("5/minute")
def register_company(request: Request, body: RegisterRequest, response: Response):
    """Register a new logistics company"""
    from db.database import get_session
    from db import models

    verify_turnstile(body.turnstile_token, request.client.host if request.client else None)

    if body.password != body.confirm_password:
        raise HTTPException(400, "The two passwords don't match. Retype them and try again.")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    # bcrypt only hashes the first 72 bytes of a password - older bcrypt
    # versions silently truncated anything past that, but bcrypt>=5 raises
    # ValueError instead. hash_password() below isn't wrapped in a
    # try/except that would turn that into a clear message, so reject it
    # here with one instead of letting it fall through to a generic 500.
    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(400, "Password must be 72 bytes or fewer (most passwords qualify).")

    # Consumed BEFORE the company is created (not after) - a company must
    # never exist without its Gmail credential when this flow was used, and
    # this is also a one-time claim: a second /api/auth/register call with
    # the same pending_token must fail, not silently create a duplicate
    # company sharing one Gmail connection.
    pending_gmail = None
    if body.pending_token:
        from db.repository import consume_pending_registration

        pending_gmail = consume_pending_registration(body.pending_token)
        if not pending_gmail:
            raise HTTPException(
                400, "This Gmail connection has expired. Reconnect it from Settings."
            )

    try:
        with get_session() as session:
            # Check if MC exists
            existing = session.query(models.Company).filter_by(mc_number=body.mc_number).first()
            if existing:
                raise HTTPException(400, "That MC number already has an account. Log in instead, or use a different number.")

            # Create company
            new_company = models.Company(
                mc_number=body.mc_number,
                company_name=body.company_name,
                email=body.email,
                # mc_number is already validated (digits only, <=20 chars) and unique
                # (checked above), so keying off the full number - not a truncated
                # prefix of it - avoids collisions between MC numbers that share a
                # common prefix (e.g. "555000" vs "555001").
                telegram_group_prefix=f"UN{body.mc_number}"[:20],
                password_hash=hash_password(body.password)
            )
            session.add(new_company)
            session.commit()
            session.refresh(new_company)

            if pending_gmail:
                from services.gmail_service import mark_token_connected

                save_company_credential(new_company.id, "gmail_refresh_token", pending_gmail["gmail_refresh_token"])
                mark_token_connected(new_company.id)

            token = create_session_token(
                {"role": "owner", "company_id": new_company.id, "company_name": new_company.company_name}
            )
            set_session_cookies(response, token)
            return {
                "company_name": new_company.company_name,
                "mc_number": new_company.mc_number,
                "company_id": new_company.id,
                "role": "owner",
                "gmail_connected": bool(pending_gmail),
            }
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.exception("Registration failed")
        raise HTTPException(500, "Couldn't create the account. Try again in a moment.")

@app.post("/api/auth/owner")
@limiter.limit("5/minute")
def login_owner(request: Request, body: OwnerLoginRequest, response: Response):
    verify_turnstile(body.turnstile_token, request.client.host if request.client else None)
    company = get_company_by_mc(body.mc_number.strip())
    if not company or not company.password_hash or not verify_password(body.password, company.password_hash):
        raise HTTPException(401, "That MC number and password don't match an account. Check both and try again.")

    return _finish_password_step(
        request, response, "owner", company.id, {"company_name": company.company_name, "company_id": company.id}
    )


@app.post("/api/auth/dispatcher")
@limiter.limit("5/minute")
def login_dispatcher(request: Request, body: DispatcherLoginRequest, response: Response):
    verify_turnstile(body.turnstile_token, request.client.host if request.client else None)
    dispatcher = get_dispatcher_by_username(body.username.strip())
    if not dispatcher or not verify_password(body.password, dispatcher.password_hash):
        raise HTTPException(401, "That username and password don't match an account. Check both and try again.")

    return _finish_password_step(
        request, response, "dispatcher", dispatcher.id,
        {"company_id": dispatcher.company_id, "dispatcher_id": dispatcher.id, "username": dispatcher.username},
    )


def _notify_sign_in(request: Request, claims: dict) -> None:
    """Tells an account about a sign-in from an address it has not used.

    Not every sign-in: this notice cannot be switched off, and one that
    fires whenever somebody logs in normally is noise that teaches people
    to ignore the one that mattered. A first sight of an address is the
    signal worth sending."""
    from db.repository import login_already_seen_from
    from services import notification_service

    account_type, account_id = _notification_account(claims)
    ip = _rate_limit_key(request)
    if login_already_seen_from(account_type, account_id, ip):
        return

    notification_service.notify(
        claims["company_id"], "security.new_login",
        title="A new sign-in to your account",
        body=f"Signed in from {ip}. If that was not you, change the password "
             f"and turn on two-factor authentication in Settings.",
        link="/settings#security",
        account_types=(account_type,),
    )


def _finish_password_step(request: Request, response: Response, account_type: str, account_id: int, extra_claims: dict):
    """Shared by both login endpoints: once the password checks out, either
    issue a real session (cookie) when no 2FA is enabled, or a short-lived
    "pending" token the frontend must complete a second factor with. The
    pending token is handed back in the response body rather than a cookie -
    it grants no resource access on its own (still requires a valid 2FA
    code), so it's a narrow login-handshake token, not a session."""
    from db.repository import get_2fa_status

    status = get_2fa_status(account_type, account_id)
    base_claims = {"role": account_type, **extra_claims}

    if not status["any_enabled"]:
        token = create_session_token(base_claims)
        set_session_cookies(response, token)
        _notify_sign_in(request, base_claims)
        return {"role": account_type, **extra_claims, **_gmail_connected_field(account_type, extra_claims["company_id"])}

    available_methods = [
        m
        for m, enabled in [
            ("totp", status["totp_enabled"]),
            ("email", status["email_otp_enabled"]),
            ("sms", status["sms_otp_enabled"]),
            ("telegram", status["telegram_otp_enabled"]),
            ("webauthn", status["webauthn_count"] > 0),
        ]
        if enabled
    ]
    pending_token = create_token(
        {"purpose": "2fa_login", "account_type": account_type, "account_id": account_id, **base_claims},
        lifetime_seconds=SHORT_LIVED_SECONDS,
    )
    return {"requires_2fa": True, "pending_token": pending_token, "methods": available_methods}


def _status_field(user: dict) -> dict:
    from db.repository import get_account_status

    account_type, account_id = _self_account(user)
    return {"status": get_account_status(account_type, account_id)}


def _company_name_field(user: dict) -> dict:
    """The company's name as it is now, not as it was at sign-in.

    The session token carries a copy, stamped when the token was minted, and
    returning that meant the header kept showing the old name after a rename
    while every screen that reads the database showed the new one - the same
    account, named two different things on one page, until the session
    happened to expire.

    A token is for identity: company_id is the part that is signed and the
    part that decides what anyone can reach. A display name is not
    authorisation, so it is read rather than trusted.
    """
    company_id = user.get("company_id")
    if not company_id:
        return {}

    from db.repository import get_company_billing_info

    company = get_company_billing_info(company_id)
    return {"company_name": company["company_name"]} if company else {}


@app.get("/api/me")
def me(user: dict = Depends(get_current_user)):
    return {
        **user,
        # After the spread, so a stale name in the token loses to the live one.
        **_company_name_field(user),
        **_gmail_connected_field(user.get("role"), user.get("company_id")),
        **_status_field(user),
        **_avatar_field(user),
    }


class SetStatusRequest(BaseModel):
    emoji: str | None = None
    text: str
    expires_in_minutes: int | None = None  # None = never expires

    @field_validator("text")
    @classmethod
    def _text_length(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Status text is required")
        if len(v) > 80:
            raise ValueError("Status must be 80 characters or fewer")
        return v

    @field_validator("emoji")
    @classmethod
    def _emoji_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 8:
            raise ValueError("That doesn't look like a single emoji")
        return v


@app.put("/api/me/status")
def set_my_status(
    body: SetStatusRequest, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    from datetime import timedelta
    from db.repository import set_account_status

    account_type, account_id = _self_account(user)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=body.expires_in_minutes)
        if body.expires_in_minutes else None
    )
    set_account_status(account_type, account_id, body.emoji, body.text, expires_at)
    return {"success": True}


@app.delete("/api/me/status")
def clear_my_status(user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    from db.repository import clear_account_status

    account_type, account_id = _self_account(user)
    clear_account_status(account_type, account_id)
    return {"success": True}


def _avatar_field(user: dict) -> dict:
    from db.repository import get_account_avatar

    account_type, account_id = _self_account(user)
    return {"avatar": get_account_avatar(account_type, account_id)}


# Data-URI cap: ~300KB of base64 text, comfortably above a compressed
# ~200x200 JPEG (what the frontend resizes to before uploading) with room
# to spare, while still ruling out someone stuffing a multi-MB image in.
_MAX_AVATAR_DATA_URL_LENGTH = 300_000


class SetAvatarRequest(BaseModel):
    data_url: str

    @field_validator("data_url")
    @classmethod
    def _validate_data_url(cls, v: str) -> str:
        if not v.startswith("data:image/"):
            raise ValueError("Avatar must be an image data URL")
        if len(v) > _MAX_AVATAR_DATA_URL_LENGTH:
            raise ValueError("Image is too large - please use a smaller picture")
        return v


@app.put("/api/me/avatar")
def set_my_avatar(
    body: SetAvatarRequest, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    from db.repository import set_account_avatar

    account_type, account_id = _self_account(user)
    set_account_avatar(account_type, account_id, body.data_url)
    return {"success": True}


@app.delete("/api/me/avatar")
def clear_my_avatar(user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    from db.repository import clear_account_avatar

    account_type, account_id = _self_account(user)
    clear_account_avatar(account_type, account_id)
    return {"success": True}


class TeamMember(BaseModel):
    role: str
    name: str
    avatar: str | None = None


@app.get("/api/team", response_model=list[TeamMember])
def get_team(user: dict = Depends(get_current_user)):
    """The owner plus every dispatcher under the company, with their
    avatars - lets owner and dispatchers see each other's profile
    pictures, regardless of which one of them is logged in."""
    from db.repository import get_team_roster

    return get_team_roster(user["company_id"])


# ------------------------------------------------------------------
# Offline truck game - /play. Tickets, score submission, leaderboard.
# ------------------------------------------------------------------
# Enough to cover a decent stretch with no connection without becoming a way
# to bank a large number of attempts.
MAX_GAME_SESSIONS = 5


class GameScoreSubmission(BaseModel):
    token: str
    payout: int
    delivered: int
    lost: int
    duration_ms: int


def _display_name(user: dict) -> str:
    return user.get("username") or user.get("company_name") or "Driver"


@app.post("/api/game/sessions")
@limiter.limit("20/minute")
def issue_game_session(
    request: Request, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    """Hands out play tickets, topping the account back up to
    MAX_GAME_SESSIONS. Each carries a server-chosen seed.

    Batched deliberately: the game is meant to work offline, and a client with
    no connection can't ask for a ticket when the run starts. Pre-issuing lets
    someone play offline and submit afterwards while keeping the seed - and so
    the ceiling on what the route can pay - out of the client's hands."""
    from db.repository import count_unconsumed_sessions, issue_game_sessions

    account_type, account_id = _self_account(user)
    have = count_unconsumed_sessions(account_type, account_id)
    needed = max(0, MAX_GAME_SESSIONS - have)
    issued = issue_game_sessions(account_type, account_id, needed) if needed else []
    return {"issued": issued, "held": have + len(issued)}


@app.post("/api/game/scores")
@limiter.limit("30/minute")
def submit_game_score(
    request: Request, body: GameScoreSubmission,
    user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    """Records a run, if it survives validation.

    What this proves: the ticket was real, unused, issued to this account and
    still valid, and the claimed payout is within what that route could
    possibly pay. That defeats the realistic attacks on a browser leaderboard
    - editing localStorage, replaying a good run, or POSTing an arbitrary
    number.

    What it does NOT prove: that the run was actually played. The physics runs
    on the client, so someone who scripts plausible-looking input and posts a
    believable payout inside the ceiling will get through. Closing that would
    mean re-simulating the run server-side, which needs the physics to be
    deterministic across platforms - it isn't, with a float-based rigid-body
    engine - or shipping a second, simplified simulation and scoring that
    instead. That was a deliberate trade: real physics for the player, a
    ceiling rather than a proof for the board."""
    from db.repository import GameScoreRejected, record_game_score

    account_type, account_id = _self_account(user)
    try:
        return record_game_score(
            account_type, account_id, _display_name(user),
            body.token, body.payout, body.delivered, body.lost, body.duration_ms,
        )
    except GameScoreRejected as e:
        raise HTTPException(400, str(e))


@app.get("/api/game/leaderboard")
def game_leaderboard(period: str = "week"):
    """Public on purpose - a board nobody can look at without signing in
    isn't much of a board. Playing still requires an account, since tickets
    are issued per account."""
    from db.repository import get_game_leaderboard

    if period not in ("week", "month"):
        raise HTTPException(400, "Unknown period. Use week or month.")
    return {"period": period, "entries": get_game_leaderboard(period)}


@app.post("/api/auth/logout")
def logout(response: Response):
    """Clears the session/CSRF cookies. Client-side JS can't read or delete
    an httpOnly cookie itself, so this round-trip is required."""
    clear_session_cookies(response)
    return {"success": True}


# ------------------------------------------------------------------
# Password reset (owner accounts only - see PasswordResetToken's docstring
# for why dispatchers aren't covered here)
# ------------------------------------------------------------------
_FORGOT_PASSWORD_RESPONSE = {
    "message": "If that MC number is registered, we've emailed a link to reset the password."
}


@app.post("/api/auth/forgot-password")
@limiter.limit("5/minute")
def forgot_password(request: Request, body: ForgotPasswordRequest):
    """Always returns the same generic response whether or not the MC number
    matches an account, and whether or not the email actually sends -
    responding differently in any of those cases would let this endpoint be
    used to enumerate registered MC numbers."""
    verify_turnstile(body.turnstile_token, request.client.host if request.client else None)

    company = get_company_by_mc(body.mc_number.strip())
    if company and company.email:
        import logging
        import secrets
        from db.repository import create_password_reset_token
        from services import email_otp_service

        token = secrets.token_urlsafe(32)
        create_password_reset_token(company.id, token)
        reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
        try:
            email_otp_service.send_password_reset_email(company.email, reset_url)
        except Exception:
            logging.exception("Failed to send password reset email for company %s", company.id)

    return _FORGOT_PASSWORD_RESPONSE


@app.post("/api/auth/reset-password")
@limiter.limit("10/minute")
def reset_password(request: Request, body: ResetPasswordRequest):
    if body.new_password != body.confirm_password:
        raise HTTPException(400, "The two passwords don't match. Retype them and try again.")

    from db.repository import consume_password_reset_token

    company_id = consume_password_reset_token(body.token)
    if not company_id:
        raise HTTPException(400, "This reset link has expired. Request a new one from the login page.")

    set_company_password(company_id, hash_password(body.new_password))

    from services import notification_service

    notification_service.notify(
        company_id, "security.password_changed",
        title="Your password was changed",
        body="If that was not you, reset it again straight away and turn on "
             "two-factor authentication in Settings.",
        link="/settings#security", account_types=("owner",),
    )
    return {"success": True}


# ------------------------------------------------------------------
# Driver management
# ------------------------------------------------------------------
@app.get("/api/drivers")
def list_drivers(user: dict = Depends(get_current_user)):
    try:
        drivers = get_drivers_by_company(user["company_id"])
        return drivers if drivers is not None else []
    except Exception:
        import logging
        logging.exception("Failed to fetch drivers for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't load the driver list. Try again in a moment.")


@app.get("/api/drivers/{driver_id}")
def get_driver(driver_id: int, user: dict = Depends(get_current_user)):
    """Returns detailed information about a specific driver including load history."""
    try:
        # Security: ensure the driver belongs to the logged-in user's company
        from db.database import get_session
        from db import models
        with get_session() as session:
            driver_record = session.get(models.Driver, driver_id)
            if not driver_record:
                raise HTTPException(404, "Driver not found.")
            if driver_record.company_id != user["company_id"]:
                raise HTTPException(403, "Access denied.")
        
        driver = get_driver_details(driver_id, user["company_id"])
        if not driver:
            raise HTTPException(404, "This driver has no details recorded yet.")
        return driver
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.exception("Failed to fetch driver details for driver %s", driver_id)
        raise HTTPException(500, "Couldn't load this driver. Try again in a moment.")


@app.patch("/api/drivers/{driver_id}/subscription")
def update_subscription(
    driver_id: int, body: SubscriptionToggleRequest,
    user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    # Either role can pause a driver (e.g. one who just quit) without
    # waiting on the owner, but only the owner can activate one - that
    # commits the company to another billable driver against its plan.
    if body.active and user.get("role") != "owner":
        raise HTTPException(403, "Only the company owner can activate a driver's subscription. Ask them to do it.")

    try:
        # Security: verify driver belongs to this company
        from db.database import get_session
        from db import models
        with get_session() as session:
            driver_record = session.get(models.Driver, driver_id)
            if not driver_record:
                raise HTTPException(404, "Driver not found.")
            if driver_record.company_id != user["company_id"]:
                raise HTTPException(403, "Access denied.")

            # Enforce the plan's driver cap when turning a driver ON.
            #
            # subscription_status matters here, not just tier: a failed
            # renewal (past_due/unpaid) leaves `tier` as whatever paid plan
            # the company was on - Stripe keeps retrying for weeks before
            # actually canceling - so checking tier alone would let a
            # lapsed-payment company keep activating new paid-tier drivers
            # the whole time. Already-active drivers are deliberately left
            # alone here (see _handle_subscription_deleted's docstring) -
            # this only blocks NEW activations under a plan that isn't
            # currently in good standing. add_driver (POST /api/drivers)
            # needs this same check - see its own docstring.
            if body.active and not driver_record.subscription_active:
                info = get_company_billing_info(user["company_id"])
                in_good_standing = bool(info and info["subscription_status"] in ("active", "trialing"))
                limit = PLAN_LIMITS.get(info["subscription_tier"], 1) if info and in_good_standing else 1
                if info and info["active_drivers"] >= limit:
                    raise HTTPException(
                        402,
                        f"Your {info['subscription_tier']} plan allows up to {limit} active "
                        "driver(s). Upgrade your plan to activate more.",
                    )

        toggle_driver_subscription(driver_id, body.active, user["company_id"])
        return {"status": "updated", "active": body.active}
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.exception("Failed to toggle subscription for driver %s", driver_id)
        raise HTTPException(500, "Couldn't update the subscription. Try again in a moment.")


def _issue_driver_link_code(driver_id: int) -> dict:
    """Generates a one-time code for linking a driver's Telegram group,
    reusing the same TelegramLinkToken table/pattern
    /api/2fa/telegram/link/start uses for 2FA account linking -
    account_type="driver_group" (instead of "owner"/"dispatcher") keeps the
    two uses from ever being confused, see bot.py's handle_linkdriver and
    handle_verify2fa. Good for 24 hours rather than the 15 minutes 2FA codes
    get, since this one requires the owner to go create/configure an actual
    Telegram group in between generating the code and using it."""
    import secrets
    from datetime import datetime, timezone, timedelta
    from db.repository import create_telegram_link_token

    code = secrets.token_hex(3).upper()
    create_telegram_link_token("driver_group", driver_id, code, datetime.now(timezone.utc) + timedelta(hours=24))
    return {"code": code, "bot_command": f"/linkdriver {code}"}


@app.post("/api/drivers")
def add_driver(
    body: CreateDriverRequest, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    """Creates a driver (active immediately, same as seed.py's path) and
    returns a one-time code to link it to a Telegram group - see
    handle_linkdriver in bot.py. New drivers count against the plan's
    active-driver cap right away, same check update_subscription enforces
    when reactivating one - including falling back to the free-tier cap
    while the subscription isn't in good standing (past_due/unpaid), not
    just checking subscription_tier - see update_subscription's docstring
    for why tier alone isn't enough."""
    info = get_company_billing_info(user["company_id"])
    in_good_standing = bool(info and info["subscription_status"] in ("active", "trialing"))
    limit = PLAN_LIMITS.get(info["subscription_tier"], 1) if info and in_good_standing else 1
    if info and info["active_drivers"] >= limit:
        raise HTTPException(
            402,
            f"Your {info['subscription_tier']} plan allows up to {limit} active "
            "driver(s). Upgrade your plan to add more.",
        )

    try:
        driver = create_driver(user["company_id"], body.full_name)
        link = _issue_driver_link_code(driver["id"])
        # NewDriver (frontend/src/services/api.ts) names this field
        # "link_code", not "code" - it's embedded alongside full_name/
        # driver_bot_id/etc. on the combined driver+code response, where
        # "code" would be ambiguous. The standalone regenerate-link-token
        # response below has no such ambiguity, so it keeps "code" as-is
        # (matches the DriverLinkCode type).
        return {**driver, "link_code": link["code"], "bot_command": link["bot_command"]}
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.exception("Failed to create driver for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't add the driver. Try again in a moment.")


@app.post("/api/drivers/{driver_id}/link-token")
def regenerate_driver_link_code(
    driver_id: int, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    """Issues a fresh linking code for an existing driver - e.g. the first
    code expired, or the driver needs to be (re)linked to a different group."""
    from db.database import get_session
    from db import models

    with get_session() as session:
        driver_record = session.get(models.Driver, driver_id)
        if not driver_record:
            raise HTTPException(404, "Driver not found.")
        if driver_record.company_id != user["company_id"]:
            raise HTTPException(403, "Access denied.")

    return _issue_driver_link_code(driver_id)


# ------------------------------------------------------------------
# Fleet assets - trucks and trailers.
#
# Open to owner AND dispatcher, unlike driver/dispatcher management. Keeping
# the fleet list current is day-to-day dispatch work: trailers get swapped
# and drivers move between trucks constantly, and routing every one of those
# through the owner would just stall the board.
# ------------------------------------------------------------------
class UnitNumberRequest(BaseModel):
    unit_number: str

    @field_validator("unit_number")
    @classmethod
    def _check(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Unit number is required")
        if len(v) > 30:
            raise ValueError("Unit number must be 30 characters or fewer")
        return v


class TruckAssignRequest(BaseModel):
    # None is a real value here (unhook the trailer / take the driver off),
    # so "absent" has to mean something different from "null". Pydantic's
    # exclude_unset on the dump below is what tells them apart.
    driver_id: int | None = None
    trailer_id: int | None = None


@app.get("/api/trucks")
def list_company_trucks(user: dict = Depends(get_current_user)):
    from db.repository import list_trucks

    return list_trucks(user["company_id"])


@app.post("/api/trucks")
def add_truck(
    body: UnitNumberRequest, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    from db.repository import create_truck

    truck = create_truck(user["company_id"], body.unit_number)
    if truck is None:
        raise HTTPException(400, f"Truck {body.unit_number} already exists.")
    return truck


@app.patch("/api/trucks/{truck_id}")
def assign_truck_endpoint(
    truck_id: int, body: TruckAssignRequest,
    user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    """Seats a driver on the truck and/or hooks a trailer to it. Omit a field
    to leave it as it is; send it as null to clear it."""
    from db.repository import assign_truck

    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise HTTPException(400, "Nothing to update.")

    updated = assign_truck(
        truck_id, user["company_id"],
        driver_id=provided["driver_id"] if "driver_id" in provided else ...,
        trailer_id=provided["trailer_id"] if "trailer_id" in provided else ...,
    )
    if not updated:
        raise HTTPException(404, "Truck, driver or trailer not found.")
    return {"success": True}


@app.delete("/api/trucks/{truck_id}")
def remove_truck(
    truck_id: int, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    from db.repository import delete_truck

    if not delete_truck(truck_id, user["company_id"]):
        raise HTTPException(404, "Truck not found.")
    return {"success": True}


@app.delete("/api/drivers/{driver_id}")
def remove_driver(
    driver_id: int, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    from db.repository import delete_driver

    deleted, refusal = delete_driver(driver_id, user["company_id"])
    if refusal:
        raise HTTPException(409, refusal)
    if not deleted:
        raise HTTPException(404, "Driver not found.")
    return {"success": True}


# ------------------------------------------------------------------
# Truck and driver details read from a group's description.
#
# The bot proposes what the bio says; these endpoints are the dashboard half
# of confirming it. The same proposal is confirmable from Telegram, so a
# proposal that has already been handled comes back as 409 rather than 404 -
# nothing is wrong, the office was simply second.
# ------------------------------------------------------------------
class GroupProfileConfirmRequest(BaseModel):
    # What the person changed before confirming. The dashboard shows the
    # reading in an editable form, so a misread digit gets corrected instead
    # of the whole proposal being thrown away.
    fields: dict[str, str] | None = None


class DriverDetailsRequest(BaseModel):
    truck_number: str | None = None
    trailer_number: str | None = None
    driver_name: str | None = None
    driver_phone: str | None = None
    co_driver_name: str | None = None
    co_driver_phone: str | None = None
    vin: str | None = None
    driver_email: str | None = None


@app.get("/api/group-profiles")
def list_group_profiles(user: dict = Depends(get_current_user)):
    """Everything read from a group bio and still waiting on someone."""
    from db.repository import list_pending_proposals

    return list_pending_proposals(user["company_id"])


@app.post("/api/group-profiles/{proposal_id}/confirm")
def confirm_group_profile(
    proposal_id: int,
    body: GroupProfileConfirmRequest,
    user: dict = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    from db.repository import apply_group_profile_proposal

    from db.repository import proposal_driver_id
    from services import group_profile

    owner = proposal_driver_id(proposal_id)
    ok, reason = apply_group_profile_proposal(
        proposal_id, "dashboard", company_id=user["company_id"], edits=body.fields
    )
    if ok:
        # The record is now the confirmed one, so the group's name,
        # description and picture are written to match it. Failure in any of
        # them is logged inside and does not undo the confirmation.
        if owner:
            _publish_and_announce(*owner)
        return {"success": True}
    if reason == "already_resolved":
        raise HTTPException(409, "This was already confirmed - from Telegram, or from another tab.")
    if reason == "driver_gone":
        raise HTTPException(410, "That driver has been deleted, so there is nothing to save it to.")
    raise HTTPException(404, "That reading no longer exists.")


@app.post("/api/group-profiles/{proposal_id}/dismiss")
def dismiss_group_profile(
    proposal_id: int,
    user: dict = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    from db.repository import dismiss_group_profile_proposal

    ok, reason = dismiss_group_profile_proposal(
        proposal_id, "dashboard", company_id=user["company_id"]
    )
    if ok:
        return {"success": True}
    if reason == "already_resolved":
        raise HTTPException(409, "This was already handled - from Telegram, or from another tab.")
    raise HTTPException(404, "That reading no longer exists.")


def _publish_and_announce(company_id: int, driver_id: int) -> None:
    """Writes the confirmed record onto the group, then says what changed.

    Silent when nothing was written - a group where the bot is not an admin
    refuses all three, and announcing an empty change trains people to skip
    the messages that do say something.
    """
    from services import group_profile, notification_service

    changed = group_profile.publish_all(company_id, driver_id)
    described = group_profile.describe_changes(changed.get("written") or ())
    if not described:
        return
    notification_service.notify(
        company_id, "fleet.group_updated",
        title=f"The bot updated a driver's group ({described})",
        body="Written from the details somebody confirmed.",
        link="/settings",
    )


@app.patch("/api/drivers/{driver_id}/details")
def save_driver_details(
    driver_id: int,
    body: DriverDetailsRequest,
    user: dict = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Typed in by hand, for a driver whose group bio says nothing useful."""
    from db.repository import update_driver_details
    from services import notification_service

    ok, reason = update_driver_details(
        driver_id, user["company_id"], body.model_dump(exclude_none=True)
    )
    if ok:
        _publish_and_announce(user["company_id"], driver_id)
        notification_service.notify(
            user["company_id"], "fleet.details_changed",
            title="Truck and driver details were edited",
            body=", ".join(sorted(body.model_dump(exclude_none=True))) or None,
            link="/settings",
        )
        return {"success": True}
    if reason == "nothing_to_save":
        raise HTTPException(400, "No details were sent.")
    raise HTTPException(404, "Driver not found.")


# ------------------------------------------------------------------
# Which Telegram group a driver's loads go to.
#
# Open to owner AND dispatcher, for the same reason the fleet endpoints
# are: drivers move between trucks and groups constantly, and routing every
# one of those through the owner would stall the board.
#
# A group becomes a company's by somebody running /linkdriver inside it
# with a code from Settings, which is what proves they are in the group.
# These endpoints move a group the company already holds - they cannot
# claim a new one, because a typed-in chat id would let anyone start
# posting loads into a stranger's chat.
# ------------------------------------------------------------------
class DriverGroupRequest(BaseModel):
    # None is a real value - it means unlink - so it has to be sent
    # explicitly rather than left out.
    telegram_group_id: int | None = None


@app.get("/api/groups")
def list_company_groups(user: dict = Depends(get_current_user)):
    """The company's linked groups, and which driver holds each one."""
    from db.repository import company_groups

    return {"groups": company_groups(user["company_id"])}


@app.put("/api/drivers/{driver_id}/group")
def set_driver_group_endpoint(
    driver_id: int,
    body: DriverGroupRequest,
    user: dict = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Moves one of the company's groups onto this driver, or unlinks."""
    from db.repository import set_driver_group

    ok, reason = set_driver_group(driver_id, user["company_id"], body.telegram_group_id)
    if ok:
        return {"success": True}
    if reason == "not_this_company":
        # One string literal, not two adjacent ones: the house-style check
        # in tests/test_error_message_style.py reads these out of the source
        # and only sees the first fragment of a split message.
        raise HTTPException(403, "That group isn't linked to this company - add the bot to it, then run /linkdriver there with a code from Settings.")
    raise HTTPException(404, "Driver not found.")


# ------------------------------------------------------------------
# Notifications
#
# The bell, and the screen that decides what rings it. Addressed by
# (account_type, account_id) rather than by company: an owner and a
# dispatcher at the same company are different people who asked to be told
# different things.
# ------------------------------------------------------------------
def _notification_account(user: dict) -> tuple[str, int]:
    """Which login this is, in the pair the notification tables use.

    An owner is identified by their company - there is one owner per
    company and no separate row for them - while a dispatcher has an id of
    their own."""
    role = user.get("role")
    if role == "dispatcher":
        return "dispatcher", int(user["dispatcher_id"])
    return "owner", int(user["company_id"])


class MarkReadRequest(BaseModel):
    # Omitted means all of them - the "mark everything read" button.
    ids: list[int] | None = None


class NotificationPreferenceRequest(BaseModel):
    event: str
    channel: str
    enabled: bool


@app.get("/api/notifications")
def get_notifications(
    limit: int = 50,
    unread_only: bool = False,
    user: dict = Depends(get_current_user),
):
    from db.repository import list_notifications, unread_notification_count

    account_type, account_id = _notification_account(user)
    limit = max(1, min(limit, 100))
    return {
        "notifications": list_notifications(
            account_type, account_id, limit=limit, unread_only=unread_only
        ),
        "unread": unread_notification_count(account_type, account_id),
    }


@app.post("/api/notifications/read")
def mark_notifications(
    body: MarkReadRequest,
    user: dict = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    from db.repository import mark_notifications_read, unread_notification_count

    account_type, account_id = _notification_account(user)
    marked = mark_notifications_read(account_type, account_id, body.ids)
    return {"marked": marked, "unread": unread_notification_count(account_type, account_id)}


@app.get("/api/notifications/preferences")
def get_notification_preferences(user: dict = Depends(get_current_user)):
    """The whole catalogue, as this account currently has it set.

    Everything the screen needs comes from here rather than being duplicated
    in the frontend: which events exist, which apply to this kind of login,
    which channels each one can use, and whether it is on. Mandatory events
    are included and flagged rather than hidden - people should be able to
    see what they will be told about even when they cannot change it."""
    from db.repository import notification_preferences
    from services import notification_events as events
    from services.notification_service import wants

    account_type, account_id = _notification_account(user)
    saved = notification_preferences(account_type, account_id)

    rows = []
    for event in events.for_audience(account_type):
        rows.append({
            "event": event.key,
            "category": event.category,
            "category_label": events.CATEGORY_LABELS.get(event.category, event.category),
            "label": event.label,
            "description": event.description,
            "mandatory": event.mandatory,
            "channels": {
                channel: {
                    "available": event.allows(channel),
                    "enabled": wants(account_type, account_id, event, channel, saved),
                    # The site channel is the record of what was sent, so it
                    # is never something to switch off.
                    "locked": event.mandatory or channel == events.SITE,
                }
                for channel in events.CHANNELS
            },
        })

    return {
        "channels": [
            {"key": channel, "label": events.CHANNEL_LABELS[channel]}
            for channel in events.CHANNELS
        ],
        "events": rows,
    }


@app.put("/api/notifications/preferences")
def set_notification_preferences(
    body: NotificationPreferenceRequest,
    user: dict = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    from db.repository import set_notification_preference
    from services import notification_events as events

    event = events.get(body.event)
    if not event:
        raise HTTPException(404, f"No such notification: {body.event}")
    if body.channel not in events.CHANNELS:
        raise HTTPException(400, f"No such channel: {body.channel}")

    account_type, account_id = _notification_account(user)
    if account_type not in event.audience:
        raise HTTPException(403, "That notification isn't sent to this kind of account.")
    if not event.allows(body.channel):
        raise HTTPException(400, f"{event.label} is never sent by {body.channel}.")

    # Refused rather than quietly ignored: a switch that appears to move and
    # then does nothing is worse than one that says why it cannot.
    if event.mandatory:
        raise HTTPException(
            409,
            f"{event.label} can't be turned off - it's the kind of thing you need to know about.",
        )
    if body.channel == events.SITE:
        raise HTTPException(
            409,
            "The dashboard list can't be turned off - it's the record of what was sent.",
        )

    set_notification_preference(account_type, account_id, body.event, body.channel, body.enabled)
    return {"success": True}


@app.get("/api/trailers")
def list_company_trailers(user: dict = Depends(get_current_user)):
    from db.repository import list_trailers

    return list_trailers(user["company_id"])


@app.post("/api/trailers")
def add_trailer(
    body: UnitNumberRequest, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    from db.repository import create_trailer

    trailer = create_trailer(user["company_id"], body.unit_number)
    if trailer is None:
        raise HTTPException(400, f"Trailer {body.unit_number} already exists.")
    return trailer


@app.delete("/api/trailers/{trailer_id}")
def remove_trailer(
    trailer_id: int, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    from db.repository import delete_trailer

    if not delete_trailer(trailer_id, user["company_id"]):
        raise HTTPException(404, "Trailer not found.")
    return {"success": True}


# ------------------------------------------------------------------
# Dispatcher management (owner only)
# ------------------------------------------------------------------
@app.get("/api/dispatchers", response_model=list[DispatcherSummary])
def list_dispatchers(user: dict = Depends(require_owner)):
    # response_model strips anything beyond id/username/role/created_at -
    # in particular, password_hash - even if get_dispatchers_by_company()
    # is ever changed to return more than that.
    return get_dispatchers_by_company(user["company_id"])


@app.post("/api/dispatchers")
def add_dispatcher(
    body: CreateDispatcherRequest, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    # Same shape as the driver cap above, and for the same reason: the tier
    # alone is not enough, because a subscription that has fallen out of
    # good standing drops back to the free allowance until it is put right.
    # A company already over its cap keeps every login it has - this only
    # stops another being added.
    info = get_company_billing_info(user["company_id"])
    in_good_standing = bool(info and info["subscription_status"] in ("active", "trialing"))
    tier = info["subscription_tier"] if info and in_good_standing else "free"
    limit = DISPATCHER_LIMITS.get(tier, 1)
    if limit is not None and len(get_dispatchers_by_company(user["company_id"])) >= limit:
        raise HTTPException(402, f"Your {tier} plan allows up to {limit} dispatcher login(s). Upgrade your plan to add more.")

    username = body.username.strip()
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    # See register_company's identical check for why - bcrypt only hashes
    # the first 72 bytes, and bcrypt>=5 raises instead of truncating.
    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(400, "Password must be 72 bytes or fewer (most passwords qualify).")
    if not username:
        raise HTTPException(400, "Enter a username.")
    if get_dispatcher_by_username(username):
        raise HTTPException(400, "That username is taken. Pick a different one.")
    try:
        dispatcher_id = create_dispatcher(user["company_id"], username, hash_password(body.password))
        return {"id": dispatcher_id, "username": username}
    except Exception:
        import logging
        logging.exception("Failed to create dispatcher for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't create the dispatcher login. Try again in a moment.")


@app.patch("/api/dispatchers/{dispatcher_id}")
def update_dispatcher_account(
    dispatcher_id: int, body: UpdateDispatcherRequest,
    user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    """Lets an owner change a dispatcher's username and/or password - e.g.
    the dispatcher forgot their password and has no self-service reset path
    of their own (see PasswordResetToken's docstring for why that's owner-only)."""
    from db.repository import update_dispatcher

    username = body.username.strip() if body.username is not None else None
    if username is not None and not username:
        raise HTTPException(400, "Enter a username.")

    password_hash = None
    if body.password is not None:
        if len(body.password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters.")
        if len(body.password.encode("utf-8")) > 72:
            raise HTTPException(400, "Password must be 72 bytes or fewer (most passwords qualify).")
        password_hash = hash_password(body.password)

    if username is None and password_hash is None:
        raise HTTPException(400, "Provide a new username and/or password.")

    result = update_dispatcher(dispatcher_id, user["company_id"], username=username, password_hash=password_hash)
    if result == "not_found":
        raise HTTPException(404, "Dispatcher not found.")
    if result == "username_taken":
        raise HTTPException(400, "That username is taken. Pick a different one.")
    return {"success": True}


@app.delete("/api/dispatchers/{dispatcher_id}")
def remove_dispatcher(
    dispatcher_id: int, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    from db.repository import delete_dispatcher

    if not delete_dispatcher(dispatcher_id, user["company_id"]):
        raise HTTPException(404, "Dispatcher not found.")
    return {"success": True}


# ------------------------------------------------------------------
# Settings & Integrations
# ------------------------------------------------------------------
@app.get("/api/settings")
def get_settings(user: dict = Depends(get_current_user)):
    """Get company settings and integration status"""
    company_id = user.get("company_id")
    company = get_company(company_id)
    if not company:
        raise HTTPException(404, "Company not found.")

    gmail_token = get_company_credential(company_id, "gmail_refresh_token")
    samsara_key = get_company_credential(company_id, "samsara_api_key")

    from services.gmail_service import connection_status

    gmail = connection_status(company_id)

    return {
        "gmail_connected": bool(gmail_token),
        # "ok" | "expiring" | "expired" - see gmail_service.connection_status.
        # The UI only offers a reconnect for the latter two, so a healthy
        # connection isn't cluttered with an action nobody needs to take.
        "gmail_state": gmail["state"],
        "gmail_expires_at": gmail["expires_at"],
        # Kept for the dashboard banner, which only cares about the hard
        # failure case.
        "gmail_needs_reconnect": gmail["state"] == "expired",
        "samsara_connected": bool(samsara_key) or SAMSARA_TEST_MODE,
        "company_name": company.company_name,
        "mc_number": company.mc_number
    }

# ------------------------------------------------------------------
# Gmail - real OAuth flow, triggered by clicking "Connect Gmail" in Settings.
# No copy-pasted codes or terminal commands: the owner clicks a button,
# approves access on Google's own consent screen, and lands back on
# Settings connected. This is separate from gmail_setup.py, which is the
# older CLI-based way of doing the exact same thing.
# ------------------------------------------------------------------
GMAIL_REDIRECT_URI = os.getenv("GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/api/settings/gmail/callback")


_GMAIL_RETURN_PATHS = {"settings": "/settings", "onboarding": "/onboarding/connect-gmail"}


@app.get("/api/settings/gmail/connect")
def gmail_connect(return_to: str = "settings", user: dict = Depends(require_owner)):
    from services.gmail_service import build_authorization_url

    if return_to not in _GMAIL_RETURN_PATHS:
        raise HTTPException(400, "Unknown return_to. Use settings or onboarding.")

    # The state token proves the callback belongs to this company - it's
    # short-lived and signed, so it can't be forged or reused elsewhere.
    # return_to travels inside it too, so the callback (which Google calls
    # directly, with no way for the frontend to pass its own state) still
    # knows whether to send the owner back to onboarding or Settings.
    state = create_token(
        {"company_id": user["company_id"], "purpose": "gmail_oauth", "return_to": return_to},
        lifetime_seconds=SHORT_LIVED_SECONDS,
    )
    # On a reconnect the mailbox is already on the company row, so send it
    # as the hint: Google reopens that account instead of asking. Without
    # it, an owner with two Google addresses can connect the wrong inbox on
    # a reconnect and nothing tells them until rate confirmations stop.
    from db.repository import get_company_email

    auth_url = build_authorization_url(
        GMAIL_REDIRECT_URI, state, login_hint=get_company_email(user["company_id"])
    )
    return {"auth_url": auth_url}


def _safe_oauth_reason(error: str) -> str:
    """Google's own error code, made safe to reflect into a redirect URL.

    The documented values are short identifiers like "access_denied", but
    this arrives on a public callback as a plain query parameter, so it is
    encoded and truncated rather than trusted to be one of them."""
    from urllib.parse import quote

    return quote(error[:64], safe="")


@app.get("/api/settings/gmail/callback")
def gmail_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    from fastapi.responses import RedirectResponse
    from services.gmail_service import exchange_code_for_refresh_token, mark_token_connected

    # Best-effort recovery of where to send the owner back to, even on an
    # error/expired-state path - falls back to Settings, the safer default.
    return_path = _GMAIL_RETURN_PATHS["settings"]
    payload = decode_token(state, purpose="gmail_oauth") if state else None
    if payload:
        return_path = _GMAIL_RETURN_PATHS.get(payload.get("return_to"), return_path)

    # Four different failures used to redirect with the same ?gmail=error,
    # so the page could only ever say "something went wrong" - including
    # when the owner had simply pressed Cancel on Google's consent screen.
    # Each one now names itself; the frontend maps the code to the sentence.
    if error:
        # Google's own code, e.g. access_denied when Cancel was pressed.
        return RedirectResponse(
            f"{FRONTEND_URL}{return_path}?gmail=error_google&reason={_safe_oauth_reason(error)}"
        )

    if not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=error_incomplete")

    if not payload:
        return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=error_expired_link")

    try:
        refresh_token = exchange_code_for_refresh_token(code, GMAIL_REDIRECT_URI)
        if not refresh_token:
            # Google only issues a refresh_token the FIRST time an account
            # approves this app - if this fails, they likely need to revoke
            # access at myaccount.google.com/permissions and try again.
            return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=error_no_refresh_token")
        save_company_credential(payload["company_id"], "gmail_refresh_token", refresh_token)
        # Starts the expiry clock Settings warns against, and clears any
        # "broken" flag left by the connection this one replaces.
        mark_token_connected(payload["company_id"])
        # Fresh token - retire any "needs reconnect" warning from the old one.
        from services.gmail_service import clear_token_invalid
        clear_token_invalid(payload["company_id"])

        # Record WHICH inbox this is, not just the token for it. Without
        # this an owner who signed up before the Gmail-first flow existed
        # has no email on their company row at all, which silently makes
        # password reset a no-op (it only ever reads company.email) and
        # leaves Google sign-in with nothing to match them against.
        try:
            from db.repository import set_company_email
            from services.gmail_service import get_email_address

            address = get_email_address(refresh_token)
            if address:
                set_company_email(payload["company_id"], address)
        except Exception:
            # Best-effort: the connection itself already succeeded, so a
            # failure to read the address back must not undo it.
            import logging
            logging.exception(
                "Connected Gmail for company %s but could not record its address",
                payload.get("company_id"),
            )
    except Exception:
        import logging
        logging.exception("Gmail OAuth callback failed for company %s", payload.get("company_id"))
        return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=error_exchange")

    return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=connected")


@app.delete("/api/settings/gmail")
def disconnect_gmail(user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf)):
    """Disconnect Gmail account"""
    from services.gmail_service import clear_token_invalid

    company_id = user.get("company_id")
    delete_company_credential(company_id, "gmail_refresh_token")
    # Otherwise the stale marker would make a later reconnect look broken.
    clear_token_invalid(company_id)
    return {"success": True}


# ------------------------------------------------------------------
# "Continue with Google" sign-in. Identity scopes only - see
# services/google_identity_service.py for why this is kept separate from
# the Gmail integration's restricted scopes.
# ------------------------------------------------------------------
GOOGLE_LOGIN_REDIRECT_URI = os.getenv(
    "GOOGLE_LOGIN_OAUTH_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback"
)


@app.get("/api/auth/google/start")
@limiter.limit("10/minute")
def google_login_start(request: Request, switch_account: bool = False):
    """Returns the Google consent URL for signing in. The state is a signed,
    short-lived token so the callback can prove the request originated here
    rather than being replayed from somewhere else.

    Someone who signed out of this browser recently gets sent straight back
    to the account they used, rather than picking their own address off a
    list. `switch_account=true` drops that hint and restores the chooser,
    which is what the "Use a different account" link asks for - a
    convenience nobody can escape is not one."""
    from services import google_identity_service

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google sign-in isn't configured on this server.")

    hint = None if switch_account else request.cookies.get(LAST_ACCOUNT_COOKIE_NAME)
    state = create_token({"purpose": "google_login"}, lifetime_seconds=SHORT_LIVED_SECONDS)
    body = {
        "auth_url": google_identity_service.build_authorization_url(
            GOOGLE_LOGIN_REDIRECT_URI, state, login_hint=hint
        ),
        "hinted_account": hint,
    }
    payload = JSONResponse(body)
    if switch_account:
        forget_last_account(payload)
    return payload


@app.get("/api/auth/google/callback")
def google_login_callback(
    request: Request,
    response: Response, code: str | None = None, state: str | None = None, error: str | None = None,
):
    """Google redirects the browser back here. On success this either sets a
    real session cookie and lands on the dashboard, or - when the account has
    2FA on - hands the login page a pending token to finish the second factor
    with. Proving you own the inbox is authentication, not authorization to
    skip a factor the owner deliberately turned on."""
    from fastapi.responses import RedirectResponse
    from db.repository import get_companies_by_email
    from services import google_identity_service

    def _fail(reason: str) -> RedirectResponse:
        return RedirectResponse(f"{FRONTEND_URL}/login?google={reason}")

    payload = decode_token(state, purpose="google_login") if state else None
    if error or not code or not payload:
        return _fail("error")

    try:
        email = google_identity_service.exchange_code_for_email(code, GOOGLE_LOGIN_REDIRECT_URI)
    except Exception:
        import logging
        logging.exception("Google sign-in callback failed")
        return _fail("error")

    if not email:
        return _fail("error")

    companies = get_companies_by_email(email)
    if not companies:
        return _fail("no_account")
    if len(companies) > 1:
        # Ambiguous: email isn't unique-constrained, so more than one company
        # can share an address. Refusing beats guessing which one to sign in.
        return _fail("ambiguous")

    company = companies[0]
    result = _finish_password_step(
        request, response, "owner", company.id,
        {"company_id": company.id, "company_name": company.company_name},
    )

    if result.get("requires_2fa"):
        # The available methods ride along so the login page can render the
        # same picker a password login gets. They're not secret - the JSON
        # login response returns the identical list - and the pending token
        # is what actually gates completing the factor.
        methods = ",".join(result.get("methods", []))
        challenge = RedirectResponse(
            f"{FRONTEND_URL}/login?google_2fa={result['pending_token']}&methods={methods}"
        )
        # Google has already proved who this is; only the second factor is
        # outstanding. Worth remembering either way - somebody who abandons
        # the 2FA step still came back to the same account.
        remember_last_account(challenge, email)
        return challenge

    # _finish_password_step wrote the session cookies onto `response`; carry
    # those Set-Cookie headers onto the redirect the browser actually follows.
    redirect = RedirectResponse(f"{FRONTEND_URL}/dashboard")
    for key, value in response.raw_headers:
        if key.decode().lower() == "set-cookie":
            redirect.raw_headers.append((key, value))
    remember_last_account(redirect, email)
    return redirect


# ------------------------------------------------------------------
# Gmail-first registration - connect Gmail BEFORE a Company row exists,
# confirm the visitor actually owns that inbox, THEN collect company
# details. See PendingRegistration's docstring for the full flow and why
# nothing is created until the final /api/auth/register submit.
# ------------------------------------------------------------------
REGISTER_GMAIL_REDIRECT_URI = os.getenv(
    "REGISTER_GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/api/auth/register/gmail/callback"
)


def _send_registration_verification(pending_token: str, gmail_email: str) -> None:
    import secrets

    from db.repository import set_pending_registration_verification
    from services import email_otp_service, twofactor_service

    code = twofactor_service.generate_otp_code()
    link_token = secrets.token_urlsafe(32)
    set_pending_registration_verification(pending_token, twofactor_service.hash_otp_code(code), link_token)

    verify_url = f"{FRONTEND_URL}/api/auth/register/verify-link?token={link_token}"
    email_otp_service.send_registration_verification_email(gmail_email, code, verify_url)


@app.get("/api/auth/register/gmail/start")
@limiter.limit("10/minute")
def register_gmail_start(request: Request):
    from services.gmail_service import build_authorization_url

    state = create_token({"purpose": "register_gmail"}, lifetime_seconds=SHORT_LIVED_SECONDS)
    auth_url = build_authorization_url(REGISTER_GMAIL_REDIRECT_URI, state)
    return {"auth_url": auth_url}


@app.get("/api/auth/register/gmail/callback")
def register_gmail_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """Google calls this directly - no way to redirect elsewhere on failure
    except back to the registration page with an error flag in the URL,
    same pattern as the authenticated Settings gmail_callback above."""
    from fastapi.responses import RedirectResponse
    import secrets

    from db.repository import create_pending_registration
    from services.gmail_service import exchange_code_for_refresh_token, get_email_address

    payload = decode_token(state, purpose="register_gmail") if state else None
    # Split for the same reason as the Settings callback above - a cancelled
    # consent screen and an expired link are not the same problem.
    if error:
        return RedirectResponse(
            f"{FRONTEND_URL}/register?gmail=error_google&reason={_safe_oauth_reason(error)}"
        )
    if not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}/register?gmail=error_incomplete")
    if not payload:
        return RedirectResponse(f"{FRONTEND_URL}/register?gmail=error_expired_link")

    try:
        refresh_token = exchange_code_for_refresh_token(code, REGISTER_GMAIL_REDIRECT_URI)
        if not refresh_token:
            # Same "already approved before, no refresh_token issued" case
            # the Settings flow hits - see that callback's comment.
            return RedirectResponse(f"{FRONTEND_URL}/register?gmail=error_no_refresh_token")
        gmail_email = get_email_address(refresh_token)

        pending_token = secrets.token_urlsafe(32)
        create_pending_registration(pending_token, gmail_email, refresh_token)
        try:
            _send_registration_verification(pending_token, gmail_email)
        except Exception:
            import logging
            logging.exception("Failed to send registration verification email to %s", gmail_email)
            # The pending registration still exists - the "Resend" button on
            # the verify-email step covers this instead of failing the whole
            # connection over a transient send error.
    except Exception:
        import logging
        logging.exception("Gmail OAuth callback failed during registration")
        return RedirectResponse(f"{FRONTEND_URL}/register?gmail=error_exchange")

    return RedirectResponse(f"{FRONTEND_URL}/register?pending_token={pending_token}")


@app.get("/api/auth/register/pending-status")
def register_pending_status(pending_token: str):
    from db.repository import get_pending_registration

    info = get_pending_registration(pending_token)
    if not info:
        raise HTTPException(404, "This Gmail connection has expired. Reconnect it from Settings.")
    return info


@app.post("/api/auth/register/resend-verification")
@limiter.limit("5/minute")
def register_resend_verification(request: Request, body: RegistrationVerificationRequest):
    from db.repository import get_pending_registration

    info = get_pending_registration(body.pending_token)
    if not info:
        raise HTTPException(400, "This Gmail connection has expired. Reconnect it from Settings.")
    if info["email_verified"]:
        return {"success": True}

    try:
        _send_registration_verification(body.pending_token, info["gmail_email"])
    except NotImplementedError as e:
        raise HTTPException(503, str(e))
    except Exception:
        import logging
        logging.exception("Failed to resend registration verification email")
        raise HTTPException(500, "Couldn't send the email. Try again in a moment.")
    return {"success": True}


@app.post("/api/auth/register/verify-code")
@limiter.limit("10/minute")
def register_verify_code(request: Request, body: VerifyRegistrationCodeRequest):
    from db.repository import verify_pending_registration_code
    from services import twofactor_service

    if not verify_pending_registration_code(body.pending_token, twofactor_service.hash_otp_code(body.code.strip())):
        raise HTTPException(400, "Incorrect or expired code.")
    return {"verified": True}


@app.get("/api/auth/register/verify-link")
def register_verify_link(token: str):
    from fastapi.responses import RedirectResponse
    from db.repository import verify_pending_registration_link

    pending_token = verify_pending_registration_link(token)
    if not pending_token:
        return RedirectResponse(f"{FRONTEND_URL}/register?verify=error")
    return RedirectResponse(f"{FRONTEND_URL}/register?pending_token={pending_token}&verified=1")

@app.post("/api/settings/samsara")
def connect_samsara(
    body: ConnectSamsaraRequest, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    """Connect Samsara GPS account (for owners only). Runs as a sync `def`
    route (FastAPI offloads it to a threadpool), so the blocking validation
    request below doesn't block the event loop."""
    import logging
    import requests
    from db.repository import save_company_credential
    from services import samsara_service

    company_id = user.get("company_id")

    # Quick sanity check against the real API before saving - otherwise a
    # copy-pasted/revoked/wrong-scope token just sits there looking
    # "Connected" in Settings until it silently fails during background GPS
    # polling, with nothing surfaced to the owner. Only a clear 401/403
    # (definitely-bad token) is treated as a hard failure - a timeout or any
    # other error just skips validation and saves anyway, so a Samsara
    # outage can't block someone from connecting a good key.
    try:
        resp = requests.get(
            f"{samsara_service.API_BASE}/fleet/vehicles/stats",
            headers={"Authorization": f"Bearer {body.api_key}"},
            params={"types": "gps"},
            timeout=8,
        )
        if resp.status_code in (401, 403):
            raise HTTPException(400, "That Samsara API token was rejected - double-check it and try again.")
    except HTTPException:
        raise
    except requests.RequestException:
        logging.exception("Samsara token validation request failed for company %s - saving anyway", company_id)

    try:
        save_company_credential(company_id, "samsara_api_key", body.api_key)
        return {"success": True, "message": "Samsara connected successfully"}
    except Exception:
        logging.exception("Failed to save Samsara credential for company %s", company_id)
        raise HTTPException(500, "Couldn't connect Samsara. Check the API token and try again.")

@app.delete("/api/settings/samsara")
def disconnect_samsara(user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf)):
    """Disconnect Samsara account"""
    from db.repository import delete_company_credential
    
    company_id = user.get("company_id")
    delete_company_credential(company_id, "samsara_api_key")
    return {"success": True}


# ------------------------------------------------------------------
# Customizable GPS-proximity alert rules (owner only). A company with none
# configured for a scenario keeps getting the bot's built-in default alert -
# see bot.py's _fire_scenario_alerts.
# ------------------------------------------------------------------
@app.get("/api/settings/alert-rules")
def get_alert_rules(user: dict = Depends(require_owner)):
    return list_alert_rules(user["company_id"])


@app.post("/api/settings/alert-rules")
def create_alert_rule_endpoint(
    body: AlertRuleCreateRequest, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    return create_alert_rule(
        user["company_id"], body.scenario, body.distance_miles, body.message_template, body.enabled,
    )


@app.patch("/api/settings/alert-rules/{rule_id}")
def update_alert_rule_endpoint(
    rule_id: int, body: AlertRuleUpdateRequest,
    user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    updated = update_alert_rule(rule_id, user["company_id"], body.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(404, "Alert rule not found.")
    return updated


@app.delete("/api/settings/alert-rules/{rule_id}")
def delete_alert_rule_endpoint(
    rule_id: int, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    if not delete_alert_rule(rule_id, user["company_id"]):
        raise HTTPException(404, "Alert rule not found.")
    return {"deleted": True}


# ------------------------------------------------------------------
# Billing & subscription (owner or dispatcher - either can be the one
# actually paying for the account, except the Stripe webhook below)
# ------------------------------------------------------------------
@app.get("/api/billing")
def get_billing(user: dict = Depends(get_current_user)):
    """Returns the company's current plan, subscription status, and how much
    of its driver and dispatcher allowance is in use."""
    info = get_company_billing_info(user["company_id"])
    if info is None:
        raise HTTPException(404, "Company not found.")
    tier = info["subscription_tier"]
    return {
        "tier": tier,
        "status": info["subscription_status"],
        "trial_ends_at": info["trial_ends_at"],
        "billing_interval": info["billing_interval"],
        "max_drivers": PLAN_LIMITS.get(tier, 1),
        "active_drivers": info["active_drivers"],
        # null means no cap, which is a real answer on the largest plan -
        # a number would have to be invented, and the UI can say
        # "unlimited" from the null rather than from a magic figure.
        "max_dispatchers": DISPATCHER_LIMITS.get(tier, 1),
        "dispatchers": len(get_dispatchers_by_company(user["company_id"])),
    }


@app.get("/api/billing/history")
def get_billing_history(user: dict = Depends(get_current_user)):
    """The company's billing history, and who is behind the current plan.

    Open to dispatchers as well as the owner, for the same reason the rest
    of billing is: they share one plan and any of them may have paid for it.
    Answering "who pays for this?" only for the owner would leave the person
    who actually clicked unable to see their own payment.
    """
    from db.repository import list_billing_events, who_pays

    return {
        "paid_by": who_pays(user["company_id"]),
        "events": list_billing_events(user["company_id"]),
    }


@app.post("/api/billing/checkout")
def create_billing_checkout(
    body: CheckoutRequest, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    """Starts a Stripe Checkout session for the chosen paid plan. Returns
    the URL to redirect the browser to."""
    from services import stripe_service

    try:
        # Who clicked. A company has one plan and any of its logins can be
        # the one paying for it, so this travels to Stripe as metadata and
        # comes back on the webhook - it is the only point at which the
        # payer is known, since Stripe sees a card and not a login.
        actor_type, actor_id = _self_account(user)
        url = stripe_service.create_checkout_session(
            user["company_id"], body.tier, body.interval,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_label=_actor_label(user),
        )
        return {"url": url}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except Exception:
        import logging
        logging.exception("Failed to create checkout session for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't start checkout. Try again in a moment.")


@app.post("/api/billing/portal")
def create_billing_portal(user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    """Returns a URL to the Stripe-hosted billing portal (cancel, switch
    plan, update card)."""
    from services import stripe_service

    try:
        url = stripe_service.create_portal_session(user["company_id"])
        return {"url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        import logging
        logging.exception("Failed to create billing portal session for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't open the billing portal. Try again in a moment.")


@app.get("/api/billing/payment-methods")
def list_payment_methods(user: dict = Depends(require_owner)):
    """What is on file for this company. Owner only - a dispatcher runs the
    fleet, not the company's money."""
    from services import stripe_service

    try:
        return {"payment_methods": stripe_service.list_payment_methods(user["company_id"])}
    except RuntimeError:
        # Stripe isn't configured on this server. Not an error the owner can
        # act on, and not a reason to break the billing page.
        return {"payment_methods": []}
    except Exception:
        import logging
        logging.exception("Couldn't list payment methods for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't load your payment methods. Try again in a moment.")


@app.post("/api/billing/payment-methods/setup")
def start_payment_method_setup(
    user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    """A Stripe-hosted page for putting a card on file, no charge attached.
    Works on the free plan: a card can be saved before there is anything to
    bill it for."""
    from services import stripe_service

    try:
        return {"url": stripe_service.create_setup_session(user["company_id"])}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception:
        import logging
        logging.exception("Couldn't start payment-method setup for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't open the payment form. Try again in a moment.")


@app.delete("/api/billing/payment-methods/{payment_method_id}")
def remove_payment_method(
    payment_method_id: str,
    user: dict = Depends(require_owner),
    _csrf: None = Depends(verify_csrf),
):
    """Takes a saved payment method off the account."""
    from services import stripe_service

    try:
        result = stripe_service.detach_payment_method(user["company_id"], payment_method_id)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception:
        import logging
        logging.exception("Couldn't remove payment method for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't remove that payment method. Try again in a moment.")


@app.post("/api/billing/webhook")
async def stripe_webhook(request: Request):
    """Stripe calls this server-to-server - no session cookie, no CSRF,
    authenticated instead by verifying the Stripe-Signature header against
    STRIPE_WEBHOOK_SECRET (see services/stripe_service.handle_webhook_event)."""
    from services import stripe_service

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        stripe_service.handle_webhook_event(payload, sig_header)
    except Exception as e:
        import logging
        logging.exception("Stripe webhook processing failed")
        raise HTTPException(400, f"Webhook error: {str(e)}")
    return {"received": True}


# ------------------------------------------------------------------
# Live GPS monitoring - powers the Monitoring page's map + fleet list.
# Reuses the same samsara_service the bot's background polling loop uses,
# so "connected" here means exactly what /setvehicle + Settings say it means.
# ------------------------------------------------------------------
@app.get("/api/monitoring")
async def get_monitoring(user: dict = Depends(get_current_user)):
    from db.database import get_session
    from db import models
    from services import samsara_service
    from db.repository import get_company_credential

    company_id = user["company_id"]
    samsara_connected = bool(get_company_credential(company_id, "samsara_api_key")) or SAMSARA_TEST_MODE

    with get_session() as session:
        drivers = (
            session.query(models.Driver)
            .filter(models.Driver.company_id == company_id)
            .all()
        )

        # One query for every driver's loads instead of one query per driver,
        # ordered newest-first so the first load seen per driver_id is their
        # latest one.
        driver_ids = [d.id for d in drivers]
        latest_by_driver: dict[int, models.Load] = {}
        if driver_ids:
            all_loads = (
                session.query(models.Load)
                .filter(models.Load.driver_id.in_(driver_ids))
                .order_by(models.Load.created_at.desc())
                .all()
            )
            for load in all_loads:
                latest_by_driver.setdefault(load.driver_id, load)

        # The Samsara link moved onto the truck when the fleet was
        # reorganised around trucks rather than drivers - a driver between
        # trucks has no vehicle, and a truck keeps its link when the driver
        # changes. This still read it off the driver, so the whole page
        # 500ed the moment anyone opened it.
        def vehicle_of(driver) -> str | None:
            return driver.truck.samsara_vehicle_id if driver.truck else None

        # One batched Samsara call for the whole fleet instead of one per
        # vehicle - see samsara_service.get_fleet_locations.
        vehicle_ids = sorted({v for d in drivers if (v := vehicle_of(d))})
        locations: dict[str, dict] = {}
        if samsara_connected and vehicle_ids:
            try:
                locations = await samsara_service.get_fleet_locations(company_id, vehicle_ids)
            except NotImplementedError:
                locations = {}
            except Exception:
                import logging
                logging.exception("Failed to fetch Samsara locations for company %s", company_id)
                locations = {}

        vehicles = []
        for driver in drivers:
            latest_load = latest_by_driver.get(driver.id)
            vehicle_id = vehicle_of(driver)
            location = locations.get(vehicle_id) if vehicle_id else None

            vehicles.append(
                {
                    "id": driver.id,
                    "name": driver.full_name or driver.driver_bot_id,
                    "driver_id": f"#{driver.driver_bot_id}",
                    "vehicle_id": vehicle_id,
                    "active": driver.subscription_active,
                    "location": location,
                    "load": (
                        {
                            "load_id": latest_load.load_id,
                            "status": latest_load.status,
                            "pickup": (latest_load.pu_address or "").splitlines()[0]
                            if latest_load.pu_address else "—",
                            "delivery": (latest_load.del_address or "").splitlines()[0]
                            if latest_load.del_address else "—",
                            "rate": float(latest_load.rate_amount) if latest_load.rate_amount else 0,
                        }
                        if latest_load and latest_load.status in ("dispatched", "loaded", "bol_ok")
                        else None
                    ),
                }
            )

    return {"samsara_connected": samsara_connected, "vehicles": vehicles}


# ------------------------------------------------------------------
# Dashboard API
# ------------------------------------------------------------------
@app.get("/api/dashboard")
def get_dashboard(user: dict = Depends(get_current_user)):
    """Returns dashboard data for the logged-in user (owner or dispatcher)"""
    try:
        from db.database import get_session
        from db import models
        from sqlalchemy import func
        
        with get_session() as session:
            # Get company info
            company = session.get(models.Company, user["company_id"])
            if not company:
                raise HTTPException(404, "Company not found.")
            
            # Get drivers
            drivers = get_drivers_by_company(user["company_id"])
            
            # Calculate stats
            total_drivers = len(drivers) if drivers else 0
            active_drivers = sum(1 for d in (drivers or []) if d.get("subscription_active"))
            
            # Get loads count
            total_loads = session.query(func.count(models.Load.id)).filter(
                models.Load.company_id == user["company_id"]
            ).scalar() or 0
            
            # Calculate weekly gross - same definition (calendar week, gross-eligible
            # statuses only) as the per-driver figures below, so the two reconcile.
            weekly_gross = session.query(func.sum(models.Load.rate_amount)).filter(
                models.Load.company_id == user["company_id"],
                models.Load.created_at >= current_week_start_utc(),
                models.Load.status.in_(GROSS_ELIGIBLE_STATUSES)
            ).scalar() or 0
            
            result = {
                "company_name": company.company_name,
                "stats": {
                    "total_drivers": total_drivers,
                    "active_drivers": active_drivers,
                    "total_loads": total_loads,
                    "weekly_gross": float(weekly_gross)
                },
                "drivers": drivers or [],
                # Every truck currently on a load, worst-first - see
                # get_fleet_status. Bundled into this response rather than
                # given its own endpoint so the dashboard still paints in a
                # single round-trip.
                "fleet": get_fleet_status(user["company_id"]),
            }

            # Surfaced on the dashboard, not just Settings: a dead Gmail
            # connection stops the bot finding rate confirmations at all, so
            # the owner needs to see it on the screen they actually open.
            if user.get("role") == "owner":
                from services.gmail_service import token_invalid_since

                if get_company_credential(user["company_id"], "gmail_refresh_token"):
                    result["gmail_needs_reconnect"] = bool(token_invalid_since(user["company_id"]))
            
            # Add billing info for owners
            if user.get("role") == "owner":
                billing = get_company_billing_info(user["company_id"])
                if billing:
                    tier = billing["subscription_tier"]
                    result["billing"] = {
                        "tier": tier,
                        "status": billing["subscription_status"],
                        "trial_ends_at": billing["trial_ends_at"],
                        "billing_interval": billing["billing_interval"],
                        "max_drivers": PLAN_LIMITS.get(tier, 1),
                        "active_drivers": billing["active_drivers"],
                    }
            
            return result
            
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.exception("Failed to load dashboard for company %s", user["company_id"])
        raise HTTPException(500, "Couldn't load the dashboard. Try again in a moment.")


# ------------------------------------------------------------------
# Static page routes - NEW STRUCTURE
# ------------------------------------------------------------------
from fastapi.responses import FileResponse

# These routes are now handled by React SPA (see bottom of file)

# API endpoint for public statistics
@app.get("/api/public/stats")
def get_public_stats():
    """Returns aggregated public statistics from database"""
    try:
        from db.database import get_session
        from db import models

        with get_session() as session:
            # Total companies registered
            total_companies = session.query(models.Company).count()
            
            # Total active drivers
            active_drivers = session.query(models.Driver).filter(
                models.Driver.subscription_active == True
            ).count()
            
            # Total loads processed
            total_loads = session.query(models.Load).count()

            # Deliberately no total rate value. Counts stay anonymous however
            # few companies there are, but a sum of money does not: while one
            # carrier is signed up, "all loads booked through Unector" is that
            # carrier's revenue, published to anyone who asks and signed in as
            # nobody. It was never shown on the trust page either, so serving
            # it bought nothing.
            #
            # No "uptime" figure here - there's no real monitoring/health-check
            # history to compute one from, and TrustPage explicitly promises
            # these are real database numbers, not marketing claims.
            return {
                "companies": total_companies,
                "active_trucks": active_drivers,
                "loads_delivered": total_loads,
            }
    except Exception:
        import logging
        logging.exception("Failed to fetch public stats")
        # Never fabricate numbers for a public page - if the query fails,
        # report honest zeros rather than fake social-proof figures.
        return {
            "companies": 0,
            "active_trucks": 0,
            "loads_delivered": 0,
        }


# ------------------------------------------------------------------
# Two-factor authentication
# ------------------------------------------------------------------
import secrets as _secrets
from datetime import datetime, timezone, timedelta as _timedelta

from db.repository import (
    get_2fa_status,
    get_2fa_delivery_info,
    save_totp_secret,
    set_totp_enabled,
    update_totp_last_used_step,
    set_email_otp,
    set_sms_otp,
    create_pending_otp,
    consume_pending_otp,
    save_recovery_codes,
    consume_recovery_code,
    add_webauthn_credential,
    list_webauthn_credentials,
    update_webauthn_sign_count,
    delete_webauthn_credential,
    create_telegram_link_token,
    create_webauthn_challenge,
    consume_webauthn_challenge,
)
from services import twofactor_service, email_otp_service, sms_service, telegram_otp_service, webauthn_service


class OtpChannelRequest(BaseModel):
    channel: str
    contact: str | None = None


class OtpVerifyRequest(BaseModel):
    channel: str
    code: str


class TwoFaLoginVerifyRequest(BaseModel):
    pending_token: str
    method: str
    code: str


class WebAuthnVerifyRequest(BaseModel):
    credential_json: str
    label: str | None = None


class WebAuthnLoginVerifyRequest(BaseModel):
    pending_token: str
    credential_json: str


def get_pending_2fa_claims(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "This sign-in has expired. Start again from the login page.")
    payload = decode_token(authorization.removeprefix("Bearer ").strip(), purpose="2fa_login")
    if not payload:
        raise HTTPException(401, "This sign-in took too long to finish. Start again from the login page.")
    return payload


def _self_account(user: dict) -> tuple[str, int]:
    if user["role"] == "owner":
        return "owner", user["company_id"]
    return "dispatcher", user["dispatcher_id"]


def _actor_label(user: dict) -> str:
    """How a login is named in a record that outlives it.

    Billing history keeps this alongside the id, because a dispatcher who
    paid in March and left in June is still the answer to who paid in
    March - and joining to a row that no longer exists would either erase
    them or break the page."""
    for key in ("username", "email"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return "the owner" if user.get("role") == "owner" else "a dispatcher"


@app.get("/api/2fa/status", response_model=TwoFaStatusResponse)
def get_two_factor_status(user: dict = Depends(get_current_user)):
    # response_model acts as an allow-list here: get_2fa_status() reads a
    # TwoFactorSecret row that also holds totp_secret_encrypted - if a
    # future edit to that function ever returned the raw row instead of a
    # curated dict, FastAPI would strip it back down to this schema
    # instead of silently serializing the encrypted secret to the client.
    account_type, account_id = _self_account(user)
    return get_2fa_status(account_type, account_id)


@app.post("/api/2fa/totp/setup")
@limiter.limit("10/minute")
def totp_setup(request: Request, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    account_type, account_id = _self_account(user)
    secret = twofactor_service.generate_totp_secret()
    save_totp_secret(account_type, account_id, encrypt_value(secret))
    label = user.get("company_name") or f"{account_type}-{account_id}"
    qr_data_url = twofactor_service.totp_provisioning_qr_data_url(secret, label)
    return {"secret": secret, "qr_code": qr_data_url}


@app.post("/api/2fa/totp/verify")
@limiter.limit("10/minute")
def totp_verify(
    request: Request, body: OtpVerifyRequest, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    account_type, account_id = _self_account(user)
    info = get_2fa_delivery_info(account_type, account_id)
    if not info or not info["totp_secret_encrypted"]:
        raise HTTPException(400, "Start the authenticator setup before confirming a code.")
    step = twofactor_service.verify_totp_code(
        info["totp_secret_encrypted"], body.code, info["totp_last_used_step"]
    )
    if step is None:
        raise HTTPException(400, "That code is incorrect. Check the digits and try again.")
    update_totp_last_used_step(account_type, account_id, step)
    set_totp_enabled(account_type, account_id, True)
    return {"enabled": True}


@app.delete("/api/2fa/totp")
def totp_disable(user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    account_type, account_id = _self_account(user)
    set_totp_enabled(account_type, account_id, False)
    return {"enabled": False}


@app.post("/api/2fa/otp/send")
@limiter.limit("5/minute")
async def otp_send(
    request: Request, body: OtpChannelRequest,
    user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    account_type, account_id = _self_account(user)
    code = twofactor_service.generate_otp_code()

    # Send BEFORE persisting the pending code - a delivery failure here
    # (SMTP/SMS_PROVIDER unconfigured, a real send error, the user blocked
    # the bot, ...) previously propagated as a bare, detail-less 500 with
    # no indication of what went wrong, AND still left a pending_otp row
    # for a code that was never actually delivered.
    try:
        if body.channel == "email":
            if not body.contact:
                raise HTTPException(400, "Enter an email address.")
            email_otp_service.send_otp_email(body.contact, code)
        elif body.channel == "sms":
            if not body.contact:
                raise HTTPException(400, "Enter a phone number.")
            sms_service.send_otp_sms(body.contact, code)
        elif body.channel == "telegram":
            info = get_2fa_delivery_info(account_type, account_id)
            if not info or not info["telegram_user_id"]:
                raise HTTPException(400, "Link your Telegram account first (see the Telegram tab).")
            await telegram_otp_service.send_otp_telegram(info["telegram_user_id"], code)
        else:
            raise HTTPException(400, "Unknown channel. Use email, sms or telegram.")
    except HTTPException:
        raise
    except NotImplementedError as e:
        raise HTTPException(400, str(e))
    except Exception:
        import logging
        logging.exception("Failed to send %s OTP enrollment code for %s %s", body.channel, account_type, account_id)
        raise HTTPException(502, "Couldn't send the verification code. Try again in a moment.")

    create_pending_otp(
        account_type, account_id, body.channel, "enroll",
        twofactor_service.hash_otp_code(code), twofactor_service.otp_expiry(),
    )

    return {"sent": True}


@app.post("/api/2fa/otp/confirm")
@limiter.limit("10/minute")
def otp_confirm(
    request: Request, body: OtpVerifyRequest, contact: str | None = None,
    user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    account_type, account_id = _self_account(user)
    if not consume_pending_otp(account_type, account_id, body.channel, "enroll", twofactor_service.hash_otp_code(body.code)):
        raise HTTPException(400, "That code is incorrect or has expired. Request a new one and try again.")

    if body.channel == "email":
        set_email_otp(account_type, account_id, contact, True)
    elif body.channel == "sms":
        set_sms_otp(account_type, account_id, contact, True)
    elif body.channel == "telegram":
        pass  # already linked via /verify2fa in the bot

    return {"enabled": True}


@app.delete("/api/2fa/otp/{channel}")
def otp_disable(channel: str, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    from db.repository import set_telegram_otp as _set_tg

    account_type, account_id = _self_account(user)
    if channel == "email":
        set_email_otp(account_type, account_id, None, False)
    elif channel == "sms":
        set_sms_otp(account_type, account_id, None, False)
    elif channel == "telegram":
        _set_tg(account_type, account_id, None, False)
    else:
        raise HTTPException(400, "Unknown channel. Use email, sms or telegram.")
    return {"enabled": False}


@app.post("/api/2fa/telegram/link/start")
def telegram_link_start(user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    account_type, account_id = _self_account(user)
    code = _secrets.token_hex(3).upper()
    create_telegram_link_token(account_type, account_id, code, datetime.now(timezone.utc) + _timedelta(minutes=15))
    return {"code": code, "bot_command": f"/verify2fa {code}"}


@app.get("/api/2fa/webauthn")
def webauthn_list(user: dict = Depends(get_current_user)):
    account_type, account_id = _self_account(user)
    creds = list_webauthn_credentials(account_type, account_id)
    return [{"id": c["id"], "label": c["label"], "created_at": c["created_at"]} for c in creds]


@app.post("/api/2fa/webauthn/register/options")
def webauthn_register_options(user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    account_type, account_id = _self_account(user)
    existing = [c["credential_id"] for c in list_webauthn_credentials(account_type, account_id)]
    label = user.get("company_name") or f"{account_type}-{account_id}"
    options_json, challenge = webauthn_service.build_registration_options(f"{account_type}:{account_id}", label, existing)
    # Stored server-side and consumed on verify below - the challenge is
    # NOT sent back to the client to echo back (see WebauthnChallenge's
    # docstring for why trusting a client-supplied challenge is unsafe).
    create_webauthn_challenge(account_type, account_id, "register", challenge)
    return {"options": options_json}


@app.post("/api/2fa/webauthn/register/verify")
def webauthn_register_verify(
    body: WebAuthnVerifyRequest, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    account_type, account_id = _self_account(user)
    expected_challenge = consume_webauthn_challenge(account_type, account_id, "register")
    if not expected_challenge:
        raise HTTPException(400, "This registration has expired. Start it again from the sign-up page.")
    try:
        result = webauthn_service.verify_registration(body.credential_json, expected_challenge)
    except Exception as e:
        raise HTTPException(400, f"Could not verify security key: {e}")
    add_webauthn_credential(
        account_type, account_id, result["credential_id"], result["public_key"], result["sign_count"], body.label
    )
    return {"registered": True}


@app.delete("/api/2fa/webauthn/{credential_pk}")
def webauthn_delete(
    credential_pk: int, user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf),
):
    account_type, account_id = _self_account(user)
    if not delete_webauthn_credential(account_type, account_id, credential_pk):
        raise HTTPException(404, "Security key not found.")
    return {"deleted": True}


@app.post("/api/2fa/recovery-codes/generate")
def recovery_codes_generate(user: dict = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    account_type, account_id = _self_account(user)
    codes = twofactor_service.generate_recovery_codes()
    save_recovery_codes(account_type, account_id, [twofactor_service.hash_recovery_code(c) for c in codes])
    return {"codes": codes}


@app.post("/api/2fa/login/challenge")
@limiter.limit("5/minute")
async def login_2fa_challenge(
    request: Request, body: OtpChannelRequest, claims: dict = Depends(get_pending_2fa_claims),
):
    account_type, account_id = claims["account_type"], claims["account_id"]
    info = get_2fa_delivery_info(account_type, account_id)
    if not info:
        raise HTTPException(400, "Two-factor authentication isn't set up on this account yet.")

    code = twofactor_service.generate_otp_code()

    # Send BEFORE persisting the pending code - see otp_send's comment for
    # why: an unhandled delivery failure here used to surface as a bare,
    # detail-less 500 and still leave a pending_otp row for a code that was
    # never actually delivered.
    try:
        if body.channel == "email" and info["email_otp_enabled"] and info["contact_email"]:
            email_otp_service.send_otp_email(info["contact_email"], code)
        elif body.channel == "sms" and info["sms_otp_enabled"] and info["phone_number"]:
            sms_service.send_otp_sms(info["phone_number"], code)
        elif body.channel == "telegram" and info["telegram_otp_enabled"] and info["telegram_user_id"]:
            await telegram_otp_service.send_otp_telegram(info["telegram_user_id"], code)
        else:
            raise HTTPException(400, "That method isn't enabled for this account.")
    except HTTPException:
        raise
    except NotImplementedError as e:
        raise HTTPException(400, str(e))
    except Exception:
        import logging
        logging.exception("Failed to send %s OTP login code for %s %s", body.channel, account_type, account_id)
        raise HTTPException(502, "Couldn't send the verification code. Try again in a moment.")

    create_pending_otp(
        account_type, account_id, body.channel, "login",
        twofactor_service.hash_otp_code(code), twofactor_service.otp_expiry(),
    )

    return {"sent": True}


@app.post("/api/2fa/login/webauthn/options")
def login_2fa_webauthn_options(claims: dict = Depends(get_pending_2fa_claims)):
    account_type, account_id = claims["account_type"], claims["account_id"]
    credentials = [c["credential_id"] for c in list_webauthn_credentials(account_type, account_id)]
    if not credentials:
        raise HTTPException(400, "No security keys are registered on this account. Add one from Settings first.")
    options_json, challenge = webauthn_service.build_authentication_options(credentials)
    create_webauthn_challenge(account_type, account_id, "login", challenge)
    return {"options": options_json}


@app.post("/api/2fa/login/verify")
@limiter.limit("10/minute")
async def login_2fa_verify(request: Request, body: TwoFaLoginVerifyRequest, response: Response):
    claims = decode_token(body.pending_token, purpose="2fa_login")
    if not claims:
        raise HTTPException(401, "This sign-in took too long to finish. Start again from the login page.")

    account_type, account_id = claims["account_type"], claims["account_id"]
    verified = False

    if body.method == "totp":
        info = get_2fa_delivery_info(account_type, account_id)
        totp_step = None
        if info and info["totp_secret_encrypted"]:
            totp_step = twofactor_service.verify_totp_code(
                info["totp_secret_encrypted"], body.code, info["totp_last_used_step"]
            )
        verified = totp_step is not None
        if verified:
            update_totp_last_used_step(account_type, account_id, totp_step)
    elif body.method in ("email", "sms", "telegram"):
        verified = consume_pending_otp(account_type, account_id, body.method, "login", twofactor_service.hash_otp_code(body.code))
    elif body.method == "recovery":
        verified = consume_recovery_code(account_type, account_id, twofactor_service.hash_recovery_code(body.code))
    else:
        raise HTTPException(400, "Unknown method. Use totp, email, sms, telegram, webauthn or recovery.")

    if not verified:
        raise HTTPException(400, "That code is incorrect or has expired. Request a new one and try again.")

    session_claims = {k: v for k, v in claims.items() if k not in ("purpose", "exp")}
    token = create_session_token(session_claims)
    set_session_cookies(response, token)
    _notify_sign_in(request, session_claims)
    return {**session_claims, **_gmail_connected_field(session_claims["role"], session_claims["company_id"])}


@app.post("/api/2fa/login/webauthn/verify")
@limiter.limit("10/minute")
async def login_2fa_webauthn_verify(
    request: Request, body: WebAuthnLoginVerifyRequest, response: Response,
):
    claims = decode_token(body.pending_token, purpose="2fa_login")
    if not claims:
        raise HTTPException(401, "This sign-in took too long to finish. Start again from the login page.")

    account_type, account_id = claims["account_type"], claims["account_id"]
    credentials = list_webauthn_credentials(account_type, account_id)
    if not credentials:
        raise HTTPException(400, "No security keys are registered on this account. Add one from Settings first.")

    expected_challenge = consume_webauthn_challenge(account_type, account_id, "login")
    if not expected_challenge:
        raise HTTPException(400, "This sign-in has expired. Start again from the login page.")

    verified_any = False
    for cred in credentials:
        try:
            new_count = webauthn_service.verify_authentication(
                body.credential_json, expected_challenge, cred["public_key"], cred["sign_count"]
            )
            update_webauthn_sign_count(cred["credential_id"], new_count)
            verified_any = True
            break
        except Exception:
            continue

    if not verified_any:
        raise HTTPException(400, "Couldn't verify that security key. Try again, or use another method.")

    session_claims = {k: v for k, v in claims.items() if k not in ("purpose", "exp")}
    token = create_session_token(session_claims)
    set_session_cookies(response, token)
    _notify_sign_in(request, session_claims)
    return {**session_claims, **_gmail_connected_field(session_claims["role"], session_claims["company_id"])}


# ------------------------------------------------------------------
# Static frontend - mount React app build
# ------------------------------------------------------------------
# Check if React build exists, otherwise fall back to old static files
react_build_path = Path("frontend/dist")
if react_build_path.exists():
    # Mount assets folder
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")
    
    # Serve static files (favicon, icons, etc.)
    @app.get("/favicon.svg", response_class=FileResponse)
    def serve_favicon():
        return FileResponse("frontend/dist/favicon.svg")
    
    @app.get("/icons.svg", response_class=FileResponse)
    def serve_icons():
        return FileResponse("frontend/dist/icons.svg")
    
    # The social-preview tags are written relative in index.html and made
    # absolute here, against whatever host the request actually arrived on.
    #
    # They have to be absolute: Open Graph requires it, and Telegram will
    # not fetch a relative og:image at all. They cannot be hardcoded either
    # - during development the host is a tunnel whose name changes every
    # time it restarts, and in production it will be a real domain. Reading
    # it off the request is the only version that is right in both.
    _ABSOLUTE_META = ("og:url", "og:image", "twitter:image")

    def _with_absolute_preview_urls(html: str, base: str) -> str:
        for key in _ABSOLUTE_META:
            attr = "property" if key.startswith("og:") else "name"
            for quote in ('"', "'"):
                needle = f'{attr}={quote}{key}{quote} content={quote}/'
                html = html.replace(needle, f'{attr}={quote}{key}{quote} content={quote}{base}/')
        return html

    @app.get("/{full_path:path}", response_class=FileResponse)
    def serve_react_app(request: Request, full_path: str):
        """Serve React app for all non-API routes (SPA fallback)"""
        # An /api path that got this far matched no route above, so it does
        # not exist. Falling through to index.html would answer it 200 with
        # a page of HTML: the caller sees a success, parses no JSON, and
        # carries on with an empty object instead of being told the endpoint
        # is missing. Say 404, in the same JSON shape as every other error.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"No such endpoint: /{full_path}")

        # If it's a static file in dist, serve it
        file_path = react_build_path / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        # Otherwise serve index.html (React Router handles the route), with
        # the preview URLs resolved against this request's own host.
        index = (react_build_path / "index.html").read_text(encoding="utf-8")
        base = str(request.base_url).rstrip("/")
        return HTMLResponse(_with_absolute_preview_urls(index, base))
else:
    # frontend/dist doesn't exist yet (fresh clone, npm run build not run
    # yet) - miniapp/static/public/ (the old pre-React marketing site) was
    # never finished and isn't on disk either, so there's nothing to fall
    # back to. Say so instead of a bare FileNotFoundError/500.
    app.mount("/static", StaticFiles(directory="miniapp/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_missing_frontend_notice():
        return (
            "<h1>Unector</h1>"
            "<p>The web dashboard hasn't been built yet. Run "
            "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, "
            "then restart this server.</p>"
        )


