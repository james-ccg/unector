"""
"Continue with Google" sign-in.

Deliberately separate from services/gmail_service.py even though both talk to
Google with the same OAuth client. That module requests gmail.readonly and
gmail.send - RESTRICTED scopes, which drag in Google's CASA security
assessment and show an "unverified app" warning until it's passed. Signing in
only needs to know who someone is, so this asks for the identity scopes
instead, which are neither sensitive nor restricted and need no review.

Keeping them apart also means a visitor can sign in without ever granting
inbox access, and that revoking one doesn't silently break the other.
"""
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

# "openid" and the email scope only - no inbox access of any kind.
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


def _build_flow(redirect_uri: str) -> Flow:
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)


def build_authorization_url(
    redirect_uri: str, state: str, login_hint: str | None = None
) -> str:
    """The Google consent URL to send a visitor to when they click
    "Continue with Google". `state` must be a signed, verifiable token - the
    callback trusts nothing else about where the request came from.

    `login_hint` is the address this browser last signed in with. With one,
    the account chooser is skipped and Google goes straight to that account
    - someone coming back after logging out should not have to pick their
    own address off a list again. prompt=select_account has to come off for
    that: it forces the chooser regardless of any hint, so the two together
    would cancel out. Without a hint the chooser stays, because then there
    genuinely is nothing to go on."""
    flow = _build_flow(redirect_uri)
    # No access_type=offline / prompt=consent here: sign-in needs a one-shot
    # identity assertion, not a stored refresh token, so there is nothing to
    # persist and nothing to leak.
    extra = {"login_hint": login_hint} if login_hint else {"prompt": "select_account"}
    auth_url, _ = flow.authorization_url(
        include_granted_scopes="true",
        state=state,
        **extra,
    )
    return auth_url


def exchange_code_for_email(code: str, redirect_uri: str) -> str | None:
    """Completes the flow and returns the VERIFIED email address, or None if
    Google didn't assert one. The address comes out of the signed id_token
    and is checked against our own client id, so a caller can treat it as
    proof of ownership rather than a self-declared value."""
    flow = _build_flow(redirect_uri)
    flow.fetch_token(code=code)

    raw_id_token = getattr(flow.credentials, "id_token", None)
    if not raw_id_token:
        return None

    claims = google_id_token.verify_oauth2_token(
        raw_id_token, google_requests.Request(), GOOGLE_CLIENT_ID
    )
    # email_verified guards against an account that merely typed an address
    # it doesn't control; without it this would be a trivial impersonation.
    if not claims.get("email_verified"):
        return None
    email = claims.get("email")
    return email.strip().lower() if email else None
