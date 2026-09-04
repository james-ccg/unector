"""
One-time setup script: authorizes a company's Gmail account for Unector
and stores the resulting refresh token (encrypted) in the database.

Run this once per company. It opens a browser window where you log into the
Gmail account that receives RC emails, and approve access.

Most setups don't need this at all - the dashboard's Settings > Connect Gmail
button does the same thing without a terminal. Only use this script if you
specifically want a CLI path, AND you've created a SEPARATE "Desktop app"
OAuth client for it in Google Cloud Console. It uses a local-loopback flow
that only Google's Desktop app client type allows; the "Web application"
client documented in .env.example (GOOGLE_CLIENT_ID/SECRET, used by the
dashboard button) will fail here with a redirect_uri_mismatch error, and
vice versa - the two client types are not interchangeable.

Usage:
    python gmail_setup.py --company-id 1
"""
import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from db.database import init_db
from db.repository import save_company_credential
from services.gmail_service import SCOPES


def run_setup(company_id: int):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise SystemExit(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in .env. "
            "Create a Desktop app OAuth client in Google Cloud Console first (see this "
            "script's own docstring, and README.md's Google OAuth section)."
        )

    init_db()

    from db.database import get_session
    from db import models
    with get_session() as session:
        if not session.get(models.Company, company_id):
            raise SystemExit(
                f"No company with id={company_id} exists. Check the id (register a company "
                f"from the dashboard first, or query the companies table) and try again."
            )

    client_config = {
        "installed": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    print("A browser window will open. Log into the Gmail account that receives RC emails and approve access.")
    credentials = flow.run_local_server(port=0)

    if not credentials.refresh_token:
        raise SystemExit(
            "No refresh token was returned. This usually means the account was already "
            "authorized before - revoke access at https://myaccount.google.com/permissions "
            "and run this script again."
        )

    save_company_credential(company_id, "gmail_refresh_token", credentials.refresh_token)
    print(f"✅ Gmail account connected for company_id={company_id}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Authorize a company's Gmail account for Unector")
    parser.add_argument("--company-id", type=int, required=True, help="The company's internal DB id")
    args = parser.parse_args()
    run_setup(args.company_id)
