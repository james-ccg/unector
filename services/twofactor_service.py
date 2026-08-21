"""
Core two-factor auth primitives: TOTP (authenticator apps), recovery codes,
and short-lived OTP codes (used for email/SMS/Telegram delivery).

Nothing in this file talks to a database - it's pure crypto/logic. The
database reads/writes live in db/repository.py, and the delivery of codes
(actually sending an email/SMS/Telegram message) lives in their own
service modules (email_otp_service.py, sms_service.py, telegram_otp_service.py).
"""
import hashlib
import secrets
import base64
import time
from datetime import datetime, timedelta, timezone

import pyotp
import qrcode
import io

from config import encrypt_value, decrypt_value

OTP_CODE_LENGTH = 6
OTP_TTL_MINUTES = 10
RECOVERY_CODE_COUNT = 10


# ------------------------------------------------------------------
# TOTP (Google Authenticator, Authy, 1Password, etc.)
# ------------------------------------------------------------------
def generate_totp_secret() -> str:
    """Generates a new base32 TOTP secret (plaintext - caller should
    encrypt it before storing)."""
    return pyotp.random_base32()


def totp_provisioning_qr_png(secret: str, account_label: str, issuer: str = "Freight Pilot") -> bytes:
    """Builds the otpauth:// URI for this secret and renders it as a PNG QR
    code, so the owner can scan it straight into their authenticator app."""
    uri = pyotp.TOTP(secret).provisioning_uri(name=account_label, issuer_name=issuer)
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def totp_provisioning_qr_data_url(secret: str, account_label: str, issuer: str = "Freight Pilot") -> str:
    """Same as above, but returns a data: URL the frontend can drop
    straight into an <img src="..."> with no extra request."""
    png_bytes = totp_provisioning_qr_png(secret, account_label, issuer)
    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def verify_totp_code(encrypted_secret: str, code: str, last_used_step: int | None = None) -> int | None:
    """Checks a 6-digit code against a stored (encrypted) TOTP secret,
    allowing +/-1 time step (30s) for clock drift. Returns the matched
    time-step number on success - the caller should persist it (see
    db/repository.py's update_totp_last_used_step) and pass it back as
    last_used_step on the next call, so a code that's been observed once
    (shoulder-surfed, leaked in a log, ...) can't be replayed for the rest
    of its ~90s validity window. Returns None if the code is wrong, OR
    valid but already consumed (its step is <= last_used_step)."""
    secret = decrypt_value(encrypted_secret)
    totp = pyotp.TOTP(secret)
    code = code.strip()
    current_step = int(time.time()) // totp.interval
    for step in (current_step, current_step - 1, current_step + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if totp.at(step * totp.interval) == code:
            return step
    return None


# ------------------------------------------------------------------
# Recovery codes
# ------------------------------------------------------------------
def _hash_code(code: str) -> str:
    """Recovery/OTP codes are short and low-entropy compared to passwords,
    so a fast salted hash (not bcrypt) is fine here - they're also
    single-use and short-lived."""
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Generates a batch of human-typeable recovery codes, e.g. 'XXXX-XXXX'."""
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()  # 8 hex chars
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    return _hash_code(code)


def verify_recovery_code(code: str, code_hash: str) -> bool:
    return _hash_code(code) == code_hash


# ------------------------------------------------------------------
# Short-lived OTP codes (email / SMS / Telegram)
# ------------------------------------------------------------------
def generate_otp_code() -> str:
    """Generates a numeric one-time code, e.g. '482913'."""
    return "".join(secrets.choice("0123456789") for _ in range(OTP_CODE_LENGTH))


def hash_otp_code(code: str) -> str:
    return _hash_code(code)


def verify_otp_code(code: str, code_hash: str) -> bool:
    return _hash_code(code) == code_hash


def otp_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
