"""Re-reads subscriptions from Stripe and applies them locally.

The app learns about subscriptions through webhooks. When one does not
arrive, the database goes on describing a company as free while Stripe
bills it - the two disagree, and the one holding the money is right.

That happens every time in local development, because Stripe cannot reach
localhost. The fix there is to forward them while you work:

    stripe listen --forward-to http://localhost:8000/api/billing/webhook

This script is for the other case: putting things straight after a
delivery was missed, without editing the database by hand.

    python scripts/sync_stripe.py            # show what disagrees
    python scripts/sync_stripe.py --apply    # fix it
    python scripts/sync_stripe.py --apply --company 1
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import models  # noqa: E402
from db.database import get_session  # noqa: E402
from db.repository import get_company_billing_info  # noqa: E402
from services import stripe_service  # noqa: E402


def companies(only: int | None) -> list[int]:
    with get_session() as session:
        rows = session.query(models.Company.id).order_by(models.Company.id).all()
    ids = [row[0] for row in rows]
    return [i for i in ids if only is None or i == only]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--company", type=int, help="just this company id")
    args = parser.parse_args()

    ids = companies(args.company)
    if not ids:
        print("No companies to check.")
        return 0

    print(f"{len(ids)} compan{'y' if len(ids) == 1 else 'ies'}\n")
    disagreed = 0

    for company_id in ids:
        before = get_company_billing_info(company_id)
        if not before or not before["stripe_customer_id"]:
            continue

        try:
            result = stripe_service.sync_from_stripe(company_id) if args.apply else None
        except Exception as e:  # noqa: BLE001 - reported, not swallowed
            print(f"  #{company_id}  could not be read from Stripe: {e}")
            continue

        after = get_company_billing_info(company_id) if args.apply else before
        live = _describe_stripe(before["stripe_customer_id"])

        local = f"{before['subscription_tier']}/{before['subscription_status']}"
        remote = live or "no subscription"

        if args.apply:
            now = f"{after['subscription_tier']}/{after['subscription_status']}"
            if now != local:
                disagreed += 1
                print(f"  #{company_id}  {local}  ->  {now}   (Stripe: {remote})")
                if result:
                    print(f"            {result['found']}")
            continue

        # Dry run: say whether the two sides tell the same story.
        agrees = live is None or before["subscription_status"] in live
        if not agrees:
            disagreed += 1
            print(f"  #{company_id}  locally {local}, but Stripe says {remote}")

    if not disagreed:
        print("  Everything already agrees with Stripe.")
    elif not args.apply:
        print(f"\n{disagreed} to fix. Re-run with --apply.")
    return 0


def _describe_stripe(customer_id: str) -> str | None:
    import stripe

    subs = stripe.Subscription.list(customer=customer_id, status="all", limit=5)
    if not subs.data:
        return None
    sub = subs.data[0]
    tier = (sub.get("metadata") or {}).get("tier", "?")
    return f"{tier}/{sub['status']}"


if __name__ == "__main__":
    raise SystemExit(main())
