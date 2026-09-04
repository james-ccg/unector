"""
One-time setup script: connects a company's Samsara account by storing
their API token (encrypted) in the database.

How to get the token: in the Samsara dashboard, go to Settings > API Tokens >
Add API Token. Give it "Read Vehicle Statistics" access under the Vehicles
category (that's all this bot needs).

Usage:
    python samsara_setup.py --company-id 1 --api-key <your Samsara API token>
"""
import argparse

from db.database import init_db
from db.repository import save_company_credential


def run_setup(company_id: int, api_key: str):
    init_db()

    from db.database import get_session
    from db import models
    with get_session() as session:
        if not session.get(models.Company, company_id):
            raise SystemExit(
                f"No company with id={company_id} exists. Check the id (register a company "
                f"from the dashboard first, or query the companies table) and try again."
            )

    save_company_credential(company_id, "samsara_api_key", api_key)
    print(f"✅ Samsara account connected for company_id={company_id}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Connect a company's Samsara API key for Unector")
    parser.add_argument("--company-id", type=int, required=True, help="The company's internal DB id")
    parser.add_argument("--api-key", required=True, help="Samsara API token")
    args = parser.parse_args()
    run_setup(args.company_id, args.api_key)
