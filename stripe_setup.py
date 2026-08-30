"""
One-time setup script: creates the Stripe Products/Prices for Freight
Pilot's Pro/Max 5x/Max 20x plans (monthly + yearly each = 6 Prices total),
using the dollar amounts in config.PLAN_PRICES, and prints the resulting
Price IDs to paste into .env.

Safe to re-run - it skips any product that already exists (matched by
name), so it won't create duplicates.

Usage:
    python stripe_setup.py

Requires STRIPE_SECRET_KEY to already be set in .env - use a TEST-mode key
(starts sk_test_) while building/testing; only switch to a live key once
you're ready to actually charge people.
"""
import stripe

from config import PLAN_PRICES, STRIPE_SECRET_KEY

PRODUCT_NAMES = {
    "pro": "Freight Pilot Pro",
    "max_5x": "Freight Pilot Max 5x",
    "max_20x": "Freight Pilot Max 20x",
}

ENV_VAR_NAMES = {
    ("pro", "month"): "STRIPE_PRICE_PRO_MONTHLY",
    ("pro", "year"): "STRIPE_PRICE_PRO_YEARLY",
    ("max_5x", "month"): "STRIPE_PRICE_MAX_5X_MONTHLY",
    ("max_5x", "year"): "STRIPE_PRICE_MAX_5X_YEARLY",
    ("max_20x", "month"): "STRIPE_PRICE_MAX_20X_MONTHLY",
    ("max_20x", "year"): "STRIPE_PRICE_MAX_20X_YEARLY",
}


# "Software as a Service (SaaS) - Business Use". Freight Pilot is sold to
# trucking companies, not consumers, so the business-use code is the right
# one - the consumer variant is taxed differently in several US states.
#
# This is not optional decoration: Stripe enables Managed Payments by default
# on new accounts, and a Checkout Session for a product with no tax code is
# rejected outright with "the product tax code is missing", which surfaced in
# the app as a bare 500 on the upgrade button.
SAAS_TAX_CODE = "txcd_10103001"


def _find_or_create_product(name: str) -> str:
    existing = stripe.Product.search(query=f'name:"{name}" AND active:"true"')
    if existing.data:
        product = existing.data[0]
        # Backfill, so re-running this script repairs products that were
        # created before the tax code was set rather than silently leaving
        # checkout broken for them.
        if not product.get("tax_code"):
            stripe.Product.modify(product.id, tax_code=SAAS_TAX_CODE)
            print(f"  set tax code on existing product {product.id} ({name})")
        return product.id
    product = stripe.Product.create(name=name, tax_code=SAAS_TAX_CODE)
    return product.id


def _find_or_create_price(product_id: str, dollars: int, interval: str) -> str:
    """Price.list (not .search) - list is strongly consistent, search has a
    brief indexing delay that could miss a Price created moments earlier in
    the same run. Without this, re-running after a partial failure (e.g.
    the script dies partway through the 6-price loop) would create
    duplicate Prices for every tier/interval that already succeeded."""
    existing = stripe.Price.list(product=product_id, active=True, limit=100)
    for price in existing.data:
        if (
            price.currency == "usd"
            and price.unit_amount == dollars * 100
            and price.recurring
            and price.recurring.get("interval") == interval
        ):
            return price.id
    price = stripe.Price.create(
        product=product_id,
        unit_amount=dollars * 100,
        currency="usd",
        recurring={"interval": interval},
    )
    return price.id


def run_setup():
    if not STRIPE_SECRET_KEY:
        raise SystemExit("STRIPE_SECRET_KEY is not set in .env - add your Stripe test secret key first.")
    stripe.api_key = STRIPE_SECRET_KEY

    print("Creating Stripe Products/Prices...\n")
    env_lines = []

    for tier, amounts in PLAN_PRICES.items():
        product_id = _find_or_create_product(PRODUCT_NAMES[tier])
        for interval, dollars in amounts.items():
            price_id = _find_or_create_price(product_id, dollars, interval)
            env_var = ENV_VAR_NAMES[(tier, interval)]
            env_lines.append(f"{env_var}={price_id}")
            print(f"  {PRODUCT_NAMES[tier]} / {interval}ly: ${dollars} -> {price_id}")

    print("\nDone. Paste these into your .env:\n")
    print("\n".join(env_lines))


if __name__ == "__main__":
    run_setup()
