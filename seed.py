"""
Seed script - creates one company and one driver for testing, and links
the driver to a given Telegram group ID.

Usage:
    python seed.py --group-id -1001234567890 --mc 123456 --company "Test Carrier LLC" --driver-name "Test Driver"

How to find the group ID: send /myid to the bot, it will print the group ID.
"""
import argparse

from db.database import init_db, get_session
from db import models
from db.repository import set_company_password
from miniapp.auth import hash_password


def seed(group_id: int, mc_number: str, company_name: str, driver_name: str, driver_bot_id: str,
         owner_password: str | None = None):
    init_db()

    with get_session() as session:
        company = (
            session.query(models.Company)
            .filter(models.Company.mc_number == mc_number)
            .first()
        )
        if company is None:
            company = models.Company(
                mc_number=mc_number,
                company_name=company_name,
                telegram_group_prefix=company_name[:10].upper().replace(" ", ""),
            )
            session.add(company)
            session.commit()
            session.refresh(company)
            print(f"✅ Company created: {company.company_name} (id={company.id})")
        else:
            print(f"ℹ️ Company already exists: {company.company_name} (id={company.id})")

        if owner_password:
            set_company_password(company.id, hash_password(owner_password))
            print(f"✅ Owner Mini App login set: MC# {mc_number} / (the password you provided)")

        driver = (
            session.query(models.Driver)
            .filter(models.Driver.telegram_group_id == group_id)
            .first()
        )
        if driver is None:
            driver = models.Driver(
                company_id=company.id,
                driver_bot_id=driver_bot_id,
                full_name=driver_name,
                telegram_group_id=group_id,
            )
            session.add(driver)
            session.commit()
            session.refresh(driver)
            print(f"✅ Driver created: {driver.full_name} (id={driver.id}), group={group_id}")
        else:
            print(f"ℹ️ This group is already linked to a driver: {driver.full_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add test data for Freight Pilot")
    parser.add_argument("--group-id", type=int, required=True, help="Telegram group ID (e.g. -1001234567890)")
    parser.add_argument("--mc", default="TEST001", help="MC number (optional for testing)")
    parser.add_argument("--company", default="Test Company", help="Company name")
    parser.add_argument("--driver-name", default="Test Driver", help="Driver's full name")
    parser.add_argument("--driver-id", default="D001", help="Driver's bot ID#")
    parser.add_argument(
        "--owner-password", default=None,
        help="Sets/updates the owner's Mini App login password (login is MC# + this password)",
    )
    args = parser.parse_args()

    seed(
        group_id=args.group_id,
        mc_number=args.mc,
        company_name=args.company,
        driver_name=args.driver_name,
        driver_bot_id=args.driver_id,
        owner_password=args.owner_password,
    )
