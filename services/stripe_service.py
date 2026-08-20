"""
Stripe billing integration. A company starts on the "free" tier with no
Stripe objects at all - picking Pro or a Max plan creates a Stripe Customer
and a Checkout Session for a subscription, with a 7-day trial unless
check_trial_eligibility() finds this email/MC number already redeemed one
on a different company. Once we learn the card's fingerprint (only known
after checkout completes), a trial that turns out to reuse a card already
tied to another company's trial gets cut short in handle_webhook_event()
rather than blocked upfront.

Local dev: `stripe listen --forward-to http://localhost:8000/api/billing/webhook`
prints a webhook signing secret to put in .env as STRIPE_WEBHOOK_SECRET.
See stripe_setup.py for creating the Products/Prices this reads price IDs
from (config.PLAN_PRICE_IDS).
"""
import logging
from datetime import datetime, timezone

import stripe

from config import FRONTEND_URL, PLAN_PRICE_IDS, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from db.repository import (
    find_trial_redemption,
    get_company_billing_info,
    set_company_stripe_customer,
    update_company_subscription,
    upsert_trial_redemption,
)

stripe.api_key = STRIPE_SECRET_KEY


def _require_configured() -> None:
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is not set (add it to .env)")


def _ts_to_datetime(ts: int | None) -> datetime | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def check_trial_eligibility(
    email: str | None, mc_number: str | None, gmail_address: str | None = None
) -> bool:
    """True if none of the given signals have redeemed a trial before."""
    return find_trial_redemption(email=email, mc_number=mc_number, gmail_address=gmail_address) is None


def create_checkout_session(company_id: int, tier: str, interval: str) -> str:
    """Creates a Stripe Checkout Session for this company to subscribe to
    `tier` ("pro" | "max_5x" | "max_20x"), billed monthly or yearly.
    Returns the URL to redirect the browser to."""
    _require_configured()
    if tier not in PLAN_PRICE_IDS:
        raise ValueError(f"Not a purchasable tier: {tier}")
    if interval not in ("month", "year"):
        raise ValueError(f"Invalid billing interval: {interval}")

    price_id = PLAN_PRICE_IDS[tier][interval]
    if not price_id:
        raise RuntimeError(
            f"No Stripe price configured for {tier}/{interval} - run stripe_setup.py "
            "and add the printed price ID to .env"
        )

    company = get_company_billing_info(company_id)
    if not company:
        raise ValueError(f"No company with id={company_id}")

    if company["subscription_status"] in ("active", "trialing"):
        raise RuntimeError("This company already has an active subscription - use Manage Billing instead")

    customer_id = company["stripe_customer_id"]
    if not customer_id:
        customer = stripe.Customer.create(
            email=company["email"],
            name=company["company_name"],
            metadata={"company_id": str(company_id), "mc_number": company["mc_number"] or ""},
        )
        customer_id = customer.id
        set_company_stripe_customer(company_id, customer_id)

    subscription_data = {"metadata": {"company_id": str(company_id), "tier": tier}}
    if check_trial_eligibility(company["email"], company["mc_number"]):
        subscription_data["trial_period_days"] = 7

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        payment_method_collection="always",
        subscription_data=subscription_data,
        success_url=f"{FRONTEND_URL}/settings?billing=success",
        cancel_url=f"{FRONTEND_URL}/pages/pricing?billing=cancelled",
        metadata={"company_id": str(company_id), "tier": tier, "interval": interval},
    )
    return session.url


def create_portal_session(company_id: int) -> str:
    """Returns a URL to the Stripe-hosted billing portal (cancel, switch
    plan, update card) for this company's existing subscription."""
    _require_configured()
    company = get_company_billing_info(company_id)
    if not company or not company["stripe_customer_id"]:
        raise ValueError("This company has no Stripe subscription yet")

    session = stripe.billing_portal.Session.create(
        customer=company["stripe_customer_id"],
        return_url=f"{FRONTEND_URL}/settings",
    )
    return session.url


def handle_webhook_event(payload: bytes, sig_header: str) -> None:
    """Verifies and processes a Stripe webhook event. Raises on a bad
    signature; unrecognized event types are ignored."""
    _require_configured()
    if not STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set (add it to .env)")

    event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "customer.subscription.created":
        _handle_subscription_created(obj)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(obj)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(obj)
    else:
        logging.info("Ignoring unhandled Stripe event type: %s", event_type)


def _company_id_from_subscription(sub: dict) -> int | None:
    company_id = (sub.get("metadata") or {}).get("company_id")
    return int(company_id) if company_id else None


def _get_card_fingerprint(sub: dict) -> str | None:
    payment_method_id = sub.get("default_payment_method")
    if not payment_method_id:
        return None
    try:
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        return (pm.get("card") or {}).get("fingerprint")
    except Exception:
        logging.exception("Failed to retrieve payment method %s for its card fingerprint", payment_method_id)
        return None


def _handle_subscription_created(sub: dict) -> None:
    company_id = _company_id_from_subscription(sub)
    if not company_id:
        logging.warning("Stripe subscription %s has no company_id metadata - ignoring", sub.get("id"))
        return

    company = get_company_billing_info(company_id)
    tier = (sub.get("metadata") or {}).get("tier", "pro")
    interval = sub["items"]["data"][0]["price"]["recurring"]["interval"]

    update_company_subscription(
        company_id,
        tier=tier,
        status=sub["status"],
        stripe_subscription_id=sub["id"],
        billing_interval=interval,
        trial_ends_at=_ts_to_datetime(sub.get("trial_end")),
    )

    card_fingerprint = _get_card_fingerprint(sub)
    if card_fingerprint and sub.get("trial_end"):
        duplicate = find_trial_redemption(card_fingerprint=card_fingerprint)
        if duplicate and duplicate["company_id"] != company_id:
            # Same card already used for a trial on a different company -
            # let the subscription proceed, but cut the free week short.
            stripe.Subscription.modify(sub["id"], trial_end="now")
            update_company_subscription(company_id, status="active", trial_ends_at=None)
            logging.info("Ended trial early for company %s - card already used for a trial", company_id)

    upsert_trial_redemption(
        company_id=company_id,
        email=company["email"] if company else None,
        mc_number=company["mc_number"] if company else None,
        card_fingerprint=card_fingerprint,
    )


def _handle_subscription_updated(sub: dict) -> None:
    company_id = _company_id_from_subscription(sub)
    if not company_id:
        return
    interval = sub["items"]["data"][0]["price"]["recurring"]["interval"]
    update_company_subscription(
        company_id,
        status=sub["status"],
        billing_interval=interval,
        trial_ends_at=_ts_to_datetime(sub.get("trial_end")),
    )


def _handle_subscription_deleted(sub: dict) -> None:
    company_id = _company_id_from_subscription(sub)
    if not company_id:
        return
    # Don't force-deactivate drivers over the free tier's cap - the
    # subscription-toggle endpoint already blocks new activations past
    # PLAN_LIMITS; existing ones ride until the owner adjusts them.
    update_company_subscription(company_id, tier="free", status="canceled", trial_ends_at=None)
