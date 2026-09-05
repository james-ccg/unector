"""
Gmail API integration. Handles two things:
1. Searching a company's inbox for the RC PDF matching a given load ID
2. Sending emails (detention requests, load-confirmation updates, POD)

Auth model: one Google Cloud OAuth "app" (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
in .env) is shared across all companies. Each company authorizes that app once
(via gmail_setup.py), and their resulting refresh token is stored encrypted in
the company_credentials table (cred_type="gmail_refresh_token"). At request time
we rebuild a live Credentials object from that stored refresh token - no
plain-text secrets are ever kept on disk.
"""
import base64
import re
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from db.repository import (
    delete_company_credential,
    get_company_credential,
    save_company_credential,
)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"

# Marks a connection whose stored refresh token Google has stopped accepting.
# Recorded when a real call fails rather than by probing on page load: it
# costs nothing on the happy path, and it reports the connection actually
# being broken instead of a guess about whether it might be.
#
# The most common cause by far is an OAuth app still in "Testing" publishing
# status - Google revokes refresh tokens issued by unverified apps after
# exactly 7 days, no matter how recently the owner approved it. The others
# are the owner revoking access, or the password on that Google account
# changing. All of them need the same fix: reconnect from Settings.
_TOKEN_INVALID_CRED = "gmail_token_invalid_at"

# When the current refresh token was issued. Needed to warn BEFORE the
# connection dies rather than only after: a broken Gmail link means rate
# confirmations stop being read, and the owner finds out from a driver
# asking where their load is.
_CONNECTED_AT_CRED = "gmail_connected_at"

# Google revokes refresh tokens from an OAuth app in "Testing" publishing
# status after exactly 7 days. Once the consent screen is published this
# stops applying and tokens last indefinitely, so the countdown is behind a
# config flag rather than assumed forever - see GOOGLE_OAUTH_TESTING_MODE.
TESTING_TOKEN_LIFETIME_DAYS = 7
WARN_WITHIN_DAYS = 2


def mark_token_connected(company_id: int) -> None:
    """Records the moment a fresh refresh token was stored, and clears any
    stale "this is broken" flag from the connection it replaces."""
    from datetime import datetime, timezone

    save_company_credential(company_id, _CONNECTED_AT_CRED, datetime.now(timezone.utc).isoformat())
    clear_token_invalid(company_id)


def connection_status(company_id: int) -> dict:
    """What Settings needs to decide whether to offer a reconnect, and how
    loudly. Returns `state` as one of:

      "ok"       - working, nothing to show
      "expiring" - still working, but due to be revoked within WARN_WITHIN_DAYS
      "expired"  - a real call has already failed; nothing is being read

    Purely a read of stored state - no Gmail call, so it costs nothing on a
    page load."""
    from datetime import datetime, timedelta, timezone

    from config import GOOGLE_OAUTH_TESTING_MODE

    if not get_company_credential(company_id, "gmail_refresh_token"):
        return {"connected": False, "state": "ok", "expires_at": None}

    if token_invalid_since(company_id):
        return {"connected": True, "state": "expired", "expires_at": None}

    expires_at = None
    if GOOGLE_OAUTH_TESTING_MODE:
        raw = get_company_credential(company_id, _CONNECTED_AT_CRED)
        if raw:
            try:
                connected_at = datetime.fromisoformat(raw)
            except ValueError:
                connected_at = None
            if connected_at:
                if connected_at.tzinfo is None:
                    connected_at = connected_at.replace(tzinfo=timezone.utc)
                expiry = connected_at + timedelta(days=TESTING_TOKEN_LIFETIME_DAYS)
                expires_at = expiry.isoformat()
                remaining = expiry - datetime.now(timezone.utc)
                if remaining <= timedelta(days=WARN_WITHIN_DAYS):
                    return {"connected": True, "state": "expiring", "expires_at": expires_at}

    return {"connected": True, "state": "ok", "expires_at": expires_at}


def mark_token_invalid(company_id: int) -> None:
    from datetime import datetime, timezone

    # Only news the first time. This is called on every failed refresh, and
    # a connection that stays broken would otherwise notify on every attempt.
    already = get_company_credential(company_id, _TOKEN_INVALID_CRED)
    save_company_credential(company_id, _TOKEN_INVALID_CRED, datetime.now(timezone.utc).isoformat())
    if already:
        return

    # Dispatch quietly stops working when this happens - rate confirmations
    # are no longer read - and the owner otherwise finds out from a driver
    # asking where their load is. Hence a notice that cannot be muted.
    from services import notification_service

    notification_service.notify(
        company_id, "security.integration_lost",
        title="Gmail disconnected",
        body="Rate confirmations aren't being read until it is reconnected. "
             "Reconnect from Settings, Integrations.",
        link="/settings#gmail", account_types=("owner",),
    )


def clear_token_invalid(company_id: int) -> None:
    """Called on a fresh connect and on any later success, so a connection
    that starts working again stops warning on its own."""
    delete_company_credential(company_id, _TOKEN_INVALID_CRED)


def token_invalid_since(company_id: int) -> str | None:
    return get_company_credential(company_id, _TOKEN_INVALID_CRED)


def _tracking_token_state(company_id: int, call):
    """Runs a Gmail call, recording whether this company's stored token is
    still accepted. Only RefreshError is treated as "reconnect needed" - an
    ordinary API error (quota, a malformed query, a transient 5xx) says
    nothing about the credential and must not raise a false alarm."""
    try:
        result = call()
    except RefreshError:
        mark_token_invalid(company_id)
        raise
    clear_token_invalid(company_id)
    return result


def _build_gmail_client(company_id: int):
    """Builds an authenticated Gmail API client for a given company."""
    refresh_token = get_company_credential(company_id, "gmail_refresh_token")
    if not refresh_token:
        raise NotImplementedError(
            f"No Gmail account connected for company_id={company_id}. "
            "Connect Gmail from the Settings page, or run gmail_setup.py."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds)


# ------------------------------------------------------------------
# Web OAuth flow - used by the Settings page's "Connect Gmail" button, so
# the owner never has to run a script or paste a token. This is separate
# from gmail_setup.py (the CLI script), which uses a different flow variant
# (InstalledAppFlow) meant for a local terminal instead of a browser redirect.
# ------------------------------------------------------------------
def _build_web_flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)


def build_authorization_url(
    redirect_uri: str,
    state: str,
    login_hint: str | None = None,
    force_picker: bool = False,
) -> str:
    """Builds the Google consent-screen URL the owner is sent to when they
    click "Connect Gmail". `state` should be a signed, verifiable token
    (not a raw company_id) so the callback can't be spoofed.

    `login_hint` is the mailbox this connection is already for. On a
    reconnect we know it - it is on the company row - and passing it means
    Google goes straight to that account instead of asking which one, which
    is the moment someone with two addresses picks the wrong one and
    silently connects the wrong inbox. It is a hint, not an instruction:
    Google still shows the picker if that account is not signed in here.

    `force_picker` is the way back out of that, and it is needed because the
    hint is only right for a reconnect. An owner whose rate confirmations
    arrive somewhere other than the address they signed up with had no way
    to say so: while the hinted account is signed in, Google walks straight
    past the chooser and the wrong inbox is the only one on offer."""
    flow = _build_web_flow(redirect_uri)
    extra = {"login_hint": login_hint} if login_hint else {}
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        # consent forces a refresh_token every time, even on reconnect;
        # select_account additionally makes Google ask which one.
        prompt="consent select_account" if force_picker else "consent",
        state=state,
        **extra,
    )
    return auth_url


def exchange_code_for_refresh_token(code: str, redirect_uri: str) -> str | None:
    """Exchanges the authorization code Google sends back to our callback
    for a long-lived refresh token."""
    token, _missing = exchange_code(code, redirect_uri)
    return token


def exchange_code(code: str, redirect_uri: str) -> tuple[str | None, list[str]]:
    """The refresh token, and any scope the owner did not actually grant.

    Google's consent screen lists each permission with its own checkbox, so
    approving the app and approving everything it asked for are different
    events. Someone can tick "read my mail" and leave "send mail on my
    behalf" alone, and the flow still completes with a usable token.

    Without this the connection was saved and shown as working, and the
    missing half surfaced later - at the moment a driver sends a POD and the
    broker never receives it, which is the worst place to find out.
    """
    flow = _build_web_flow(redirect_uri)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # Absent and empty are different answers and must not be collapsed.
    # An older google-auth has no granted_scopes at all, which means "cannot
    # tell" - refusing every connection on those versions would be worse
    # than the problem. An empty list is Google saying nothing was granted,
    # which is exactly the case worth catching.
    granted = getattr(credentials, "granted_scopes", None)
    if granted is None:
        return credentials.refresh_token, []

    missing = [scope for scope in SCOPES if scope not in set(granted)]
    return credentials.refresh_token, missing


def get_email_address(refresh_token: str) -> str:
    """Returns the Gmail address a refresh token grants access to - used
    right after the OAuth callback during registration, before any Company
    row exists to look this up the normal way (_build_gmail_client keys off
    company_id, which isn't available yet at that point)."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def find_rc_pdf_by_load_id(company_id: int, load_id: str) -> bytes | None:
    """Searches the inbox for a message mentioning the load ID with a PDF attached,
    returns the first matching PDF's bytes, or None if nothing is found."""
    service = _build_gmail_client(company_id)

    # load_id comes from a Telegram command argument the driver types - strip
    # quotes so it can't break out of the quoted search term and inject
    # extra Gmail search operators (e.g. "OR from:someone-else").
    safe_load_id = load_id.replace('"', "")
    query = f'"{safe_load_id}" has:attachment filename:pdf'
    # First call that actually contacts Google, so this is where an expired
    # or revoked refresh token surfaces - see _tracking_token_state.
    results = _tracking_token_state(
        company_id,
        lambda: service.users().messages().list(userId="me", q=query, maxResults=5).execute(),
    )
    messages = results.get("messages", [])
    if not messages:
        return None

    for msg_ref in messages:
        msg = service.users().messages().get(userId="me", id=msg_ref["id"]).execute()
        pdf_bytes = _extract_first_pdf_attachment(service, msg)
        if pdf_bytes:
            return pdf_bytes

    return None


def _extract_first_pdf_attachment(service, message: dict) -> bytes | None:
    """Walks a Gmail message's parts and downloads the first PDF attachment found."""
    parts = message.get("payload", {}).get("parts", []) or []
    for part in parts:
        filename = part.get("filename", "")
        if filename.lower().endswith(".pdf"):
            attachment_id = part.get("body", {}).get("attachmentId")
            if not attachment_id:
                continue
            attachment = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message["id"], id=attachment_id)
                .execute()
            )
            data = attachment.get("data", "")
            return base64.urlsafe_b64decode(data)
    return None


def send_email(company_id: int, to_address: str, subject: str, body: str, attachments: list | None = None):
    """Sends an email from the company's connected Gmail account.

    attachments: optional list of dicts, each {"filename": str, "data": bytes, "mime_type": str}.
    Used for forwarding the POD to the broker."""
    if not to_address or not re.match(r"[^@]+@[^@]+\.[^@]+", to_address):
        raise ValueError(f"Invalid or missing recipient email address: {to_address!r}")

    service = _build_gmail_client(company_id)

    if attachments:
        message = MIMEMultipart()
        message["to"] = to_address
        message["subject"] = subject
        message.attach(MIMEText(body))
        for att in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(att["data"])
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{att["filename"]}"')
            message.attach(part)
    else:
        message = MIMEText(body)
        message["to"] = to_address
        message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        _tracking_token_state(
            company_id,
            lambda: service.users().messages().send(userId="me", body={"raw": raw}).execute(),
        )
    except HttpError as e:
        raise RuntimeError(f"Gmail API failed to send email: {e}") from e
