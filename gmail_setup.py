"""
One-time setup script: authorizes a company's Gmail account for Freight Pilot
and stores the resulting refresh token (encrypted) in the database.

Run this once per company. It opens a browser window where you log into the
Gmail account that receives RC emails, and approve access.

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
            "Create an OAuth client in Google Cloud Console first (see README)."
        )

    init_db()

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
    parser = argparse.ArgumentParser(description="Authorize a company's Gmail account for Freight Pilot")
    parser.add_argument("--company-id", type=int, required=True, help="The company's internal DB id")
    args = parser.parse_args()
    run_setup(args.company_id)
