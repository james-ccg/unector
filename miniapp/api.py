"""
Freight Pilot Mini App - backend API.

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
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, EmailStr, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import (
    FORCE_HTTPS,
    FRONTEND_URL,
    IS_PRODUCTION,
    PLAN_LIMITS,
    SAMSARA_TEST_MODE,
    TURNSTILE_SECRET_KEY,
    TURNSTILE_SITE_KEY,
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
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    SHORT_LIVED_SECONDS,
    clear_session_cookies,
    create_token,
    decode_token,
    hash_password,
    set_session_cookies,
    verify_password,
)

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Freight Pilot Mini App API", lifespan=_lifespan)

# Brute-force / abuse protection on auth and OTP endpoints. In-memory storage
# is fine for this single-process deployment - no Redis needed.
limiter = Limiter(key_func=get_remote_address)
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
    "img-src 'self' data:; "
    "frame-src https://challenges.cloudflare.com; "
    "connect-src 'self' https://challenges.cloudflare.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


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
        raise HTTPException(401, "Missing or invalid session")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired session - please log in again")
    return payload


def require_owner(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "owner":
        raise HTTPException(403, "Only the company owner can do this")
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
    if not cookie_value or not header_value or cookie_value != header_value:
        raise HTTPException(403, "Missing or invalid CSRF token")


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
        raise HTTPException(400, "Bot verification failed. Please try again.")

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
        raise HTTPException(503, "Bot verification service unavailable. Please try again.")

    if not result.get("success"):
        raise HTTPException(400, "Bot verification failed. Please try again.")


@app.get("/api/public/config")
def get_public_config():
    """Tells the frontend whether to render the Turnstile widget at all,
    and with which site key - the secret key never leaves the backend."""
    return {"turnstile_site_key": TURNSTILE_SITE_KEY}


@app.post("/api/auth/register")
@limiter.limit("5/minute")
def register_company(request: Request, body: RegisterRequest, response: Response):
    """Register a new logistics company"""
    from db.database import get_session
    from db import models

    verify_turnstile(body.turnstile_token, request.client.host if request.client else None)

    if body.password != body.confirm_password:
        raise HTTPException(400, "Passwords do not match")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    # bcrypt only hashes the first 72 bytes of a password - older bcrypt
    # versions silently truncated anything past that, but bcrypt>=5 raises
    # ValueError instead. hash_password() below isn't wrapped in a
    # try/except that would turn that into a clear message, so reject it
    # here with one instead of letting it fall through to a generic 500.
    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(400, "Password must be 72 bytes or fewer (most passwords qualify).")

    try:
        with get_session() as session:
            # Check if MC exists
            existing = session.query(models.Company).filter_by(mc_number=body.mc_number).first()
            if existing:
                raise HTTPException(400, "This MC number is already registered")

            # Create company
            new_company = models.Company(
                mc_number=body.mc_number,
                company_name=body.company_name,
                email=body.email,
                # mc_number is already validated (digits only, <=20 chars) and unique
                # (checked above), so keying off the full number - not a truncated
                # prefix of it - avoids collisions between MC numbers that share a
                # common prefix (e.g. "555000" vs "555001").
                telegram_group_prefix=f"FP{body.mc_number}"[:20],
                password_hash=hash_password(body.password)
            )
            session.add(new_company)
            session.commit()
            session.refresh(new_company)

            token = create_token({"role": "owner", "company_id": new_company.id, "company_name": new_company.company_name})
            set_session_cookies(response, token)
            return {
                "company_name": new_company.company_name,
                "mc_number": new_company.mc_number,
                "company_id": new_company.id,
                "role": "owner",
                "gmail_connected": False,  # a brand-new company has never connected anything yet
            }
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.exception("Registration failed")
        raise HTTPException(500, "Registration failed. Please try again.")

@app.post("/api/auth/owner")
@limiter.limit("5/minute")
def login_owner(request: Request, body: OwnerLoginRequest, response: Response):
    verify_turnstile(body.turnstile_token, request.client.host if request.client else None)
    company = get_company_by_mc(body.mc_number.strip())
    if not company or not company.password_hash or not verify_password(body.password, company.password_hash):
        raise HTTPException(401, "Invalid MC number or password")

    return _finish_password_step(
        response, "owner", company.id, {"company_name": company.company_name, "company_id": company.id}
    )


@app.post("/api/auth/dispatcher")
@limiter.limit("5/minute")
def login_dispatcher(request: Request, body: DispatcherLoginRequest, response: Response):
    verify_turnstile(body.turnstile_token, request.client.host if request.client else None)
    dispatcher = get_dispatcher_by_username(body.username.strip())
    if not dispatcher or not verify_password(body.password, dispatcher.password_hash):
        raise HTTPException(401, "Invalid username or password")

    return _finish_password_step(
        response, "dispatcher", dispatcher.id,
        {"company_id": dispatcher.company_id, "dispatcher_id": dispatcher.id},
    )


def _finish_password_step(response: Response, account_type: str, account_id: int, extra_claims: dict):
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
        token = create_token(base_claims)
        set_session_cookies(response, token)
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


@app.get("/api/me")
def me(user: dict = Depends(get_current_user)):
    return {**user, **_gmail_connected_field(user.get("role"), user.get("company_id"))}


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
        raise HTTPException(400, "Passwords do not match")

    from db.repository import consume_password_reset_token

    company_id = consume_password_reset_token(body.token)
    if not company_id:
        raise HTTPException(400, "That reset link is invalid or has expired. Request a new one.")

    set_company_password(company_id, hash_password(body.new_password))
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
        raise HTTPException(500, "Failed to load drivers.")


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
                raise HTTPException(404, "Driver not found")
            if driver_record.company_id != user["company_id"]:
                raise HTTPException(403, "Access denied")
        
        driver = get_driver_details(driver_id, user["company_id"])
        if not driver:
            raise HTTPException(404, "Driver details not available")
        return driver
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.exception("Failed to fetch driver details for driver %s", driver_id)
        raise HTTPException(500, "Failed to load driver details.")


@app.patch("/api/drivers/{driver_id}/subscription")
def update_subscription(
    driver_id: int, body: SubscriptionToggleRequest,
    user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    try:
        # Security: verify driver belongs to this company
        from db.database import get_session
        from db import models
        with get_session() as session:
            driver_record = session.get(models.Driver, driver_id)
            if not driver_record:
                raise HTTPException(404, "Driver not found")
            if driver_record.company_id != user["company_id"]:
                raise HTTPException(403, "Access denied")

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
        raise HTTPException(500, "Failed to update subscription.")


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
    body: CreateDriverRequest, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
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
        raise HTTPException(500, "Failed to create driver. Please try again.")


@app.post("/api/drivers/{driver_id}/link-token")
def regenerate_driver_link_code(
    driver_id: int, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    """Issues a fresh linking code for an existing driver - e.g. the first
    code expired, or the driver needs to be (re)linked to a different group."""
    from db.database import get_session
    from db import models

    with get_session() as session:
        driver_record = session.get(models.Driver, driver_id)
        if not driver_record:
            raise HTTPException(404, "Driver not found")
        if driver_record.company_id != user["company_id"]:
            raise HTTPException(403, "Access denied")

    return _issue_driver_link_code(driver_id)


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
    username = body.username.strip()
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    # See register_company's identical check for why - bcrypt only hashes
    # the first 72 bytes, and bcrypt>=5 raises instead of truncating.
    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(400, "Password must be 72 bytes or fewer (most passwords qualify).")
    if not username:
        raise HTTPException(400, "Username cannot be empty")
    if get_dispatcher_by_username(username):
        raise HTTPException(400, "Username already exists")
    try:
        dispatcher_id = create_dispatcher(user["company_id"], username, hash_password(body.password))
        return {"id": dispatcher_id, "username": username}
    except Exception:
        import logging
        logging.exception("Failed to create dispatcher for company %s", user["company_id"])
        raise HTTPException(500, "Failed to create dispatcher. Please try again.")


# ------------------------------------------------------------------
# Settings & Integrations
# ------------------------------------------------------------------
@app.get("/api/settings")
def get_settings(user: dict = Depends(get_current_user)):
    """Get company settings and integration status"""
    company_id = user.get("company_id")
    company = get_company(company_id)
    if not company:
        raise HTTPException(404, "Company not found")

    gmail_token = get_company_credential(company_id, "gmail_refresh_token")
    samsara_key = get_company_credential(company_id, "samsara_api_key")

    return {
        "gmail_connected": bool(gmail_token),
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
        raise HTTPException(400, "Invalid return_to")

    # The state token proves the callback belongs to this company - it's
    # short-lived and signed, so it can't be forged or reused elsewhere.
    # return_to travels inside it too, so the callback (which Google calls
    # directly, with no way for the frontend to pass its own state) still
    # knows whether to send the owner back to onboarding or Settings.
    state = create_token(
        {"company_id": user["company_id"], "purpose": "gmail_oauth", "return_to": return_to},
        lifetime_seconds=SHORT_LIVED_SECONDS,
    )
    auth_url = build_authorization_url(GMAIL_REDIRECT_URI, state)
    return {"auth_url": auth_url}


@app.get("/api/settings/gmail/callback")
def gmail_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    from fastapi.responses import RedirectResponse
    from services.gmail_service import exchange_code_for_refresh_token

    # Best-effort recovery of where to send the owner back to, even on an
    # error/expired-state path - falls back to Settings, the safer default.
    return_path = _GMAIL_RETURN_PATHS["settings"]
    payload = decode_token(state) if state else None
    if payload and payload.get("purpose") == "gmail_oauth":
        return_path = _GMAIL_RETURN_PATHS.get(payload.get("return_to"), return_path)

    if error or not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=error")

    if not payload or payload.get("purpose") != "gmail_oauth":
        return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=error")

    try:
        refresh_token = exchange_code_for_refresh_token(code, GMAIL_REDIRECT_URI)
        if not refresh_token:
            # Google only issues a refresh_token the FIRST time an account
            # approves this app - if this fails, they likely need to revoke
            # access at myaccount.google.com/permissions and try again.
            return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=error_no_refresh_token")
        save_company_credential(payload["company_id"], "gmail_refresh_token", refresh_token)
    except Exception:
        import logging
        logging.exception("Gmail OAuth callback failed for company %s", payload.get("company_id"))
        return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=error")

    return RedirectResponse(f"{FRONTEND_URL}{return_path}?gmail=connected")


@app.delete("/api/settings/gmail")
def disconnect_gmail(user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf)):
    """Disconnect Gmail account"""
    company_id = user.get("company_id")
    delete_company_credential(company_id, "gmail_refresh_token")
    return {"success": True}

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
        raise HTTPException(500, "Failed to connect Samsara.")

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
        raise HTTPException(404, "Alert rule not found")
    return updated


@app.delete("/api/settings/alert-rules/{rule_id}")
def delete_alert_rule_endpoint(
    rule_id: int, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    if not delete_alert_rule(rule_id, user["company_id"]):
        raise HTTPException(404, "Alert rule not found")
    return {"deleted": True}


# ------------------------------------------------------------------
# Billing & subscription (owner only, except the Stripe webhook below)
# ------------------------------------------------------------------
@app.get("/api/billing")
def get_billing(user: dict = Depends(require_owner)):
    """Returns the company's current plan, subscription status, and how
    many of its PLAN_LIMITS driver cap is in use."""
    info = get_company_billing_info(user["company_id"])
    if info is None:
        raise HTTPException(404, "Company not found")
    tier = info["subscription_tier"]
    return {
        "tier": tier,
        "status": info["subscription_status"],
        "trial_ends_at": info["trial_ends_at"],
        "billing_interval": info["billing_interval"],
        "max_drivers": PLAN_LIMITS.get(tier, 1),
        "active_drivers": info["active_drivers"],
    }


@app.post("/api/billing/checkout")
def create_billing_checkout(
    body: CheckoutRequest, user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf),
):
    """Starts a Stripe Checkout session for the chosen paid plan. Returns
    the URL to redirect the browser to."""
    from services import stripe_service

    try:
        url = stripe_service.create_checkout_session(user["company_id"], body.tier, body.interval)
        return {"url": url}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except Exception:
        import logging
        logging.exception("Failed to create checkout session for company %s", user["company_id"])
        raise HTTPException(500, "Failed to start checkout.")


@app.post("/api/billing/portal")
def create_billing_portal(user: dict = Depends(require_owner), _csrf: None = Depends(verify_csrf)):
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
        raise HTTPException(500, "Failed to open billing portal.")


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

        # One batched Samsara call for the whole fleet instead of one per
        # vehicle - see samsara_service.get_fleet_locations.
        vehicle_ids = sorted({d.samsara_vehicle_id for d in drivers if d.samsara_vehicle_id})
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
            location = locations.get(driver.samsara_vehicle_id) if driver.samsara_vehicle_id else None

            vehicles.append(
                {
                    "id": driver.id,
                    "name": driver.full_name or driver.driver_bot_id,
                    "driver_id": f"#{driver.driver_bot_id}",
                    "vehicle_id": driver.samsara_vehicle_id,
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
                raise HTTPException(404, "Company not found")
            
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
                "drivers": drivers or []
            }
            
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
        raise HTTPException(500, "Failed to load dashboard.")


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
        from sqlalchemy import func
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
            
            # Total loads value (sum of all rate amounts)
            loads_value = session.query(
                func.sum(models.Load.rate_amount)
            ).scalar() or 0

            # No "uptime" figure here - there's no real monitoring/health-check
            # history to compute one from, and TrustPage explicitly promises
            # these are real database numbers, not marketing claims.
            return {
                "companies": total_companies,
                "active_trucks": active_drivers,
                "loads_delivered": total_loads,
                "loads_value": float(loads_value),
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
            "loads_value": 0,
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
        raise HTTPException(401, "Missing pending session")
    payload = decode_token(authorization.removeprefix("Bearer ").strip())
    if not payload or payload.get("purpose") != "2fa_login":
        raise HTTPException(401, "Invalid or expired 2FA session - please log in again")
    return payload


def _self_account(user: dict) -> tuple[str, int]:
    if user["role"] == "owner":
        return "owner", user["company_id"]
    return "dispatcher", user["dispatcher_id"]


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
        raise HTTPException(400, "Run TOTP setup first")
    step = twofactor_service.verify_totp_code(
        info["totp_secret_encrypted"], body.code, info["totp_last_used_step"]
    )
    if step is None:
        raise HTTPException(400, "Incorrect code")
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
                raise HTTPException(400, "Email address is required")
            email_otp_service.send_otp_email(body.contact, code)
        elif body.channel == "sms":
            if not body.contact:
                raise HTTPException(400, "Phone number is required")
            sms_service.send_otp_sms(body.contact, code)
        elif body.channel == "telegram":
            info = get_2fa_delivery_info(account_type, account_id)
            if not info or not info["telegram_user_id"]:
                raise HTTPException(400, "Link your Telegram account first (see the Telegram tab)")
            await telegram_otp_service.send_otp_telegram(info["telegram_user_id"], code)
        else:
            raise HTTPException(400, "Unknown channel")
    except HTTPException:
        raise
    except NotImplementedError as e:
        raise HTTPException(400, str(e))
    except Exception:
        import logging
        logging.exception("Failed to send %s OTP enrollment code for %s %s", body.channel, account_type, account_id)
        raise HTTPException(502, "Could not send the verification code. Please try again.")

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
        raise HTTPException(400, "Incorrect or expired code")

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
        raise HTTPException(400, "Unknown channel")
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
        raise HTTPException(400, "This registration attempt has expired - please try again.")
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
        raise HTTPException(404, "Security key not found")
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
        raise HTTPException(400, "Two-factor auth is not set up for this account")

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
            raise HTTPException(400, "That method isn't enabled for this account")
    except HTTPException:
        raise
    except NotImplementedError as e:
        raise HTTPException(400, str(e))
    except Exception:
        import logging
        logging.exception("Failed to send %s OTP login code for %s %s", body.channel, account_type, account_id)
        raise HTTPException(502, "Could not send the verification code. Please try again.")

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
        raise HTTPException(400, "No security keys registered for this account")
    options_json, challenge = webauthn_service.build_authentication_options(credentials)
    create_webauthn_challenge(account_type, account_id, "login", challenge)
    return {"options": options_json}


@app.post("/api/2fa/login/verify")
@limiter.limit("10/minute")
async def login_2fa_verify(request: Request, body: TwoFaLoginVerifyRequest, response: Response):
    claims = decode_token(body.pending_token)
    if not claims or claims.get("purpose") != "2fa_login":
        raise HTTPException(401, "Invalid or expired 2FA session - please log in again")

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
        raise HTTPException(400, "Unknown method")

    if not verified:
        raise HTTPException(400, "Incorrect or expired code")

    session_claims = {k: v for k, v in claims.items() if k not in ("purpose", "exp")}
    token = create_token(session_claims)
    set_session_cookies(response, token)
    return {**session_claims, **_gmail_connected_field(session_claims["role"], session_claims["company_id"])}


@app.post("/api/2fa/login/webauthn/verify")
@limiter.limit("10/minute")
async def login_2fa_webauthn_verify(
    request: Request, body: WebAuthnLoginVerifyRequest, response: Response,
):
    claims = decode_token(body.pending_token)
    if not claims or claims.get("purpose") != "2fa_login":
        raise HTTPException(401, "Invalid or expired 2FA session - please log in again")

    account_type, account_id = claims["account_type"], claims["account_id"]
    credentials = list_webauthn_credentials(account_type, account_id)
    if not credentials:
        raise HTTPException(400, "No security keys registered for this account")

    expected_challenge = consume_webauthn_challenge(account_type, account_id, "login")
    if not expected_challenge:
        raise HTTPException(400, "This sign-in attempt has expired - please try again.")

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
        raise HTTPException(400, "Could not verify security key")

    session_claims = {k: v for k, v in claims.items() if k not in ("purpose", "exp")}
    token = create_token(session_claims)
    set_session_cookies(response, token)
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
    
    # SPA fallback - serve index.html for all other routes (React Router handles routing)
    @app.get("/{full_path:path}", response_class=FileResponse)
    def serve_react_app(full_path: str):
        """Serve React app for all non-API routes (SPA fallback)"""
        # If it's a static file in dist, serve it
        file_path = react_build_path / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        # Otherwise serve index.html (React Router handles the route)
        return FileResponse("frontend/dist/index.html")
else:
    # frontend/dist doesn't exist yet (fresh clone, npm run build not run
    # yet) - miniapp/static/public/ (the old pre-React marketing site) was
    # never finished and isn't on disk either, so there's nothing to fall
    # back to. Say so instead of a bare FileNotFoundError/500.
    app.mount("/static", StaticFiles(directory="miniapp/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_missing_frontend_notice():
        return (
            "<h1>Freight Pilot</h1>"
            "<p>The web dashboard hasn't been built yet. Run "
            "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, "
            "then restart this server.</p>"
        )


