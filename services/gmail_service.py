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

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from db.repository import get_company_credential

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"


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


def build_authorization_url(redirect_uri: str, state: str) -> str:
    """Builds the Google consent-screen URL the owner is sent to when they
    click "Connect Gmail". `state` should be a signed, verifiable token
    (not a raw company_id) so the callback can't be spoofed."""
    flow = _build_web_flow(redirect_uri)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # forces a refresh_token every time, even on reconnect
        state=state,
    )
    return auth_url


def exchange_code_for_refresh_token(code: str, redirect_uri: str) -> str | None:
    """Exchanges the authorization code Google sends back to our callback
    for a long-lived refresh token."""
    flow = _build_web_flow(redirect_uri)
    flow.fetch_token(code=code)
    return flow.credentials.refresh_token


def find_rc_pdf_by_load_id(company_id: int, load_id: str) -> bytes | None:
    """Searches the inbox for a message mentioning the load ID with a PDF attached,
    returns the first matching PDF's bytes, or None if nothing is found."""
    service = _build_gmail_client(company_id)

    query = f'"{load_id}" has:attachment filename:pdf'
    results = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
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
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail API failed to send email: {e}") from e
