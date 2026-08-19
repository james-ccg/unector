"""
Central configuration.
Global settings (bot token, DB url, Gemini API key) are read from .env.
Each COMPANY's own credentials (Samsara, email) are read from the
company_credentials table in the DB, in ENCRYPTED form - not from here.
"""
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

# --- Global (single) settings ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///dispatch_bot.db")

# Optional: if a direct connection to api.telegram.org is blocked/unstable,
# set a proxy address here, e.g. http://user:pass@host:port or socks5://host:port
# Leave empty to connect directly.
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "").strip() or None

# Google OAuth client (same for every company - one Google Cloud project).
# Each company's own refresh token is stored separately, encrypted, in the DB.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# Samsara GPS monitoring settings. Each company's own Samsara API key is
# stored encrypted in the DB (see samsara_setup.py) - these two are just
# tuning knobs, not secrets.
SAMSARA_NEARBY_MILES = float(os.getenv("SAMSARA_NEARBY_MILES", "5"))
SAMSARA_POLL_INTERVAL_SECONDS = int(os.getenv("SAMSARA_POLL_INTERVAL_SECONDS", "120"))

# Deployment environment. Set ENVIRONMENT=production on the real server -
# this gates cookie Secure flags and HTTPS enforcement, both of which would
# otherwise break plain-http localhost development.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"
# Off by default so local http://localhost dev keeps working. Turn on once
# deployed somewhere that actually terminates HTTPS in front of this app -
# if a reverse proxy already redirects to HTTPS, leave this off too, to
# avoid a redirect loop.
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false").strip().lower() == "true"

# Mini App (owner/dispatcher dashboard) settings.
# JWT_SECRET_KEY signs login sessions - set a real random value in production;
# the fallback below is only for local development.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-me-before-going-live")
# Public HTTPS URL where the Mini App is served (e.g. an ngrok tunnel during
# development, or your real domain once deployed). Used by the bot's
# /dashboard command to open the Mini App from a button.
MINIAPP_URL = os.getenv("MINIAPP_URL", "").strip() or None

# The web dashboard's own URL (React frontend, e.g. Vite dev server or the
# production domain). Used to redirect back here after OAuth flows like
# Gmail Connect complete.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# ------------------------------------------------------------------
# Two-factor authentication settings
# ------------------------------------------------------------------
# WebAuthn (security keys / Touch ID / Windows Hello). RP_ID must be the
# bare domain the frontend is served from (e.g. "localhost" in dev,
# "app.freightpilot.com" in production) - no scheme, no port.
WEBAUTHN_RP_ID = os.getenv("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_RP_NAME = os.getenv("WEBAUTHN_RP_NAME", "Freight Pilot")
WEBAUTHN_ORIGIN = os.getenv("WEBAUTHN_ORIGIN", "http://localhost:5173")

# Email OTP - sent via plain SMTP (separate from the per-company Gmail OAuth
# used for RC processing, since this is platform-level login security, not
# tied to any one company's inbox). A Gmail "app password" works fine here.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME)

# Cloudflare Turnstile (bot protection on register/login) - free tier,
# sign up at dash.cloudflare.com/?to=/:account/turnstile. Leave both empty
# to disable; register/login work normally without it, just unprotected.
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "").strip() or None
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "").strip() or None

# SMS OTP - pluggable provider. Only Twilio is wired up as an example; you
# need your own paid Twilio (or similar) account for this to actually send
# a text message. Everything else (TOTP, Telegram OTP, recovery codes,
# security keys) works with no paid third party at all.
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "")  # "" (disabled) | "twilio"
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")

# Master key used to encrypt/decrypt each company's credentials.
# Keep this only in .env on the server - never commit it or paste it anywhere.
FERNET_KEY = os.getenv("FERNET_MASTER_KEY")
_fernet = Fernet(FERNET_KEY.encode()) if FERNET_KEY else None


def encrypt_value(plain_text: str) -> str:
    """Encrypts a company's API key before writing it to the DB."""
    if not _fernet:
        raise RuntimeError("FERNET_MASTER_KEY is not set (add it to .env)")
    return _fernet.encrypt(plain_text.encode()).decode()


def decrypt_value(encrypted_text: str) -> str:
    """Decrypts a key read from the DB before it's used."""
    if not _fernet:
        raise RuntimeError("FERNET_MASTER_KEY is not set (add it to .env)")
    return _fernet.decrypt(encrypted_text.encode()).decode()


def generate_new_fernet_key() -> str:
    """One-off helper: generates a new master key (run this in the terminal)."""
    return Fernet.generate_key().decode()


if __name__ == "__main__":
    print("New FERNET_MASTER_KEY:", generate_new_fernet_key())
