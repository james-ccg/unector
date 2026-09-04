"""Removes companies that were left behind by test runs.

The public numbers on /pages/trust are read live from this database, which
is the honest thing to do - and it means a database full of leftovers makes
the site claim customers that do not exist. Fifteen companies, fourteen of
them named "Test Company NNNNNN" with no drivers and no loads, is not a
statistic anyone should be shown.

A company is only removed when it has no drivers, no loads and no stored
credentials. Anything with real data attached is left alone and reported,
so this cannot quietly take a customer with it.

    python scripts/prune_test_companies.py             # show what would go
    python scripts/prune_test_companies.py --delete    # actually remove it

Back the database up first. The script refuses to run without a backup
alongside it.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import models  # noqa: E402
from db.database import get_session  # noqa: E402


def describe(session, company) -> tuple[int, int, int]:
    drivers = session.query(models.Driver).filter(
        models.Driver.company_id == company.id
    ).all()
    driver_ids = [d.id for d in drivers] or [0]
    loads = session.query(models.Load).filter(models.Load.driver_id.in_(driver_ids)).count()
    creds = session.query(models.CompanyCredential).filter(
        models.CompanyCredential.company_id == company.id
    ).count()
    return len(drivers), loads, creds


def main() -> int:
    delete = "--delete" in sys.argv

    if delete and not list(ROOT.glob("unector.db.bak-*")):
        print("No unector.db.bak-* alongside the database. Back it up first:")
        print("  cp unector.db unector.db.bak-$(date +%Y%m%d-%H%M%S)")
        return 1

    with get_session() as session:
        companies = session.query(models.Company).order_by(models.Company.id).all()

        empty, kept = [], []
        for company in companies:
            drivers, loads, creds = describe(session, company)
            (empty if (drivers, loads, creds) == (0, 0, 0) else kept).append(
                (company, drivers, loads, creds)
            )

        print(f"{len(companies)} companies\n")
        print("Keeping - these have data attached:")
        for company, drivers, loads, creds in kept:
            print(f"  #{company.id:<4} {company.company_name:<26} "
                  f"MC {company.mc_number:<10} {drivers} drivers, {loads} loads, {creds} credentials")

        print(f"\n{'Removing' if delete else 'Would remove'} - nothing attached to any of these:")
        for company, *_ in empty:
            print(f"  #{company.id:<4} {company.company_name:<26} MC {company.mc_number}")

        if not empty:
            print("  (none)")
            return 0

        if not delete:
            print(f"\n{len(empty)} to remove. Re-run with --delete to do it.")
            return 0

        ids = [c.id for c, *_ in empty]
        session.query(models.Company).filter(models.Company.id.in_(ids)).delete(
            synchronize_session=False
        )
        session.commit()
        print(f"\nRemoved {len(ids)}.")

    with get_session() as session:
        remaining = session.query(models.Company).count()
        drivers = session.query(models.Driver).count()
        active = session.query(models.Driver).filter(
            models.Driver.subscription_active.is_(True)
        ).count()
        loads = session.query(models.Load).count()
        print(f"\nWhat /pages/trust will now show: {remaining} companies, "
              f"{active} active drivers, {loads} loads.")
        print(f"(total drivers including inactive: {drivers})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
