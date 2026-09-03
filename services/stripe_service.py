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

    # Any status where a Stripe subscription object still exists and might
    # still be billing - block a second checkout on the same customer so it
    # can't end up with two live subscriptions (the DB row only ever tracks
    # one stripe_subscription_id, so the older one would keep charging the
    # card with nothing left pointing at it). None (never subscribed) and
    # "canceled"/"incomplete_expired" (no live subscription) fall through
    # to a normal fresh checkout.
    # "paused" belongs here too: a trial that ended without a card pauses
    # rather than cancelling, and a paused subscription is still a live
    # Stripe object that can be resumed. Leaving it out would let that
    # company start a second checkout and orphan the first.
    if company["subscription_status"] in (
        "active", "trialing", "past_due", "unpaid", "incomplete", "paused",
    ):
        raise RuntimeError("This company already has a subscription - use Manage Billing instead")

    customer_id = _ensure_customer(company_id, company)

    subscription_data = {"metadata": {"company_id": str(company_id), "tier": tier}}
    if check_trial_eligibility(company["email"], company["mc_number"]):
        subscription_data["trial_period_days"] = 7
        # What happens when the trial runs out and no card was ever given.
        # Left to Stripe's default this creates an invoice nobody can pay
        # and parks the subscription in past_due - a debt on a customer who
        # never agreed to pay anything. Pausing keeps the subscription
        # resumable the moment they add a card, and the app already treats
        # anything outside active/trialing as back on free-tier limits.
        subscription_data["trial_settings"] = {
            "end_behavior": {"missing_payment_method": "pause"}
        }

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        # "if_required", not "always": with a trial attached, this means no
        # card is asked for to start one. Someone evaluating a dispatch tool
        # should be able to see it work before handing over a card, and the
        # trial converts to paid only if they choose to add one.
        payment_method_collection="if_required",
        subscription_data=subscription_data,
        success_url=f"{FRONTEND_URL}/settings?billing=success",
        cancel_url=f"{FRONTEND_URL}/pages/pricing?billing=cancelled",
        metadata={"company_id": str(company_id), "tier": tier, "interval": interval},
        # Stripe turns Managed Payments (Stripe as merchant of record, handling
        # tax remittance) on by default for new accounts, but it needs API
        # version 2025-03-31.basil or newer - the pinned stripe 11.4.1 sends
        # 2024-12-18.acacia, so every Checkout Session died with "Managed
        # Payments is not supported on API version ...", surfacing in the app
        # as a bare 500 on the upgrade button.
        #
        # Opting out explicitly rather than upgrading the SDK: whether Stripe
        # or Freight Pilot is the merchant of record decides who is liable for
        # collecting and remitting sales tax, which is a business decision, not
        # something to adopt silently as a side effect of a version bump. Turn
        # this on deliberately (and upgrade the SDK with it) when that call is
        # actually made.
        managed_payments={"enabled": False},
    )
    return session.url


def _ensure_customer(company_id: int, company: dict) -> str:
    """The company's Stripe customer, created on first need.

    Saving a card and starting a subscription both need one, and a company
    on the free plan has never had a reason to have one."""
    if company["stripe_customer_id"]:
        return company["stripe_customer_id"]

    customer = stripe.Customer.create(
        email=company["email"],
        name=company["company_name"],
        metadata={"company_id": str(company_id), "mc_number": company["mc_number"] or ""},
    )
    set_company_stripe_customer(company_id, customer.id)
    return customer.id


def create_setup_session(company_id: int) -> str:
    """A Stripe-hosted page for saving a payment method without charging.

    Checkout in "setup" mode, so this works on the free plan and before any
    subscription exists - somebody can put a card on file whenever they
    like, rather than only being asked for one at the moment they upgrade.

    Which methods appear is Stripe's decision, not ours: it offers whatever
    the account has enabled and the customer's country supports. Naming
    them here would go stale the first time that changes."""
    _require_configured()
    company = get_company_billing_info(company_id)
    if not company:
        raise ValueError(f"No company with id={company_id}")

    session = stripe.checkout.Session.create(
        mode="setup",
        customer=_ensure_customer(company_id, company),
        # Required in setup mode. A subscription session infers it from the
        # price; there is no price here, so it has to be stated - and it
        # decides which payment methods Stripe offers. USD, matching the
        # prices stripe_setup.py creates.
        currency="usd",
        success_url=f"{FRONTEND_URL}/settings?billing=card_saved",
        cancel_url=f"{FRONTEND_URL}/settings?billing=card_cancelled",
        metadata={"company_id": str(company_id)},
        # Same reason as create_checkout_session above, and it bites harder
        # here: Managed Payments is on by default and supports only
        # "subscription" and "payment", so a setup session is refused
        # outright rather than merely failing on an API version.
        managed_payments={"enabled": False},
    )
    return session.url


def list_payment_methods(company_id: int) -> list[dict]:
    """What is on file, in the little the UI needs to name each one.

    Never the number. Stripe holds the instrument; this app only ever sees
    a brand, four digits and an expiry, which is all anyone needs to tell
    one card from another."""
    _require_configured()
    company = get_company_billing_info(company_id)
    if not company or not company["stripe_customer_id"]:
        return []

    customer = stripe.Customer.retrieve(company["stripe_customer_id"])
    default_id = (customer.get("invoice_settings") or {}).get("default_payment_method")

    methods = stripe.PaymentMethod.list(customer=company["stripe_customer_id"])
    saved = []
    for method in methods.get("data", []):
        card = method.get("card") or {}
        saved.append({
            "id": method["id"],
            "type": method["type"],
            "brand": card.get("brand"),
            "last4": card.get("last4"),
            "exp_month": card.get("exp_month"),
            "exp_year": card.get("exp_year"),
            "is_default": method["id"] == default_id,
        })
    return saved


def detach_payment_method(company_id: int, payment_method_id: str) -> None:
    """Takes a payment method off the company's Stripe customer.

    Refuses to remove the last one while a subscription is still live -
    not to trap anyone, but because the next invoice would fail and the
    account would lapse without the person who did it understanding why.
    Cancel the subscription first and this stops objecting."""
    _require_configured()
    company = get_company_billing_info(company_id)
    if not company or not company["stripe_customer_id"]:
        raise ValueError("This company has no payment methods saved.")

    saved = list_payment_methods(company_id)
    if not any(m["id"] == payment_method_id for m in saved):
        raise ValueError("That payment method is not on this account.")

    live = company["subscription_status"] in ("active", "trialing", "past_due", "unpaid", "paused")
    if live and len(saved) == 1:
        raise ValueError(
            "This is the only payment method on a live subscription. "
            "Add another first, or cancel the subscription from Manage billing."
        )

    stripe.PaymentMethod.detach(payment_method_id)


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


def sync_from_stripe(company_id: int) -> dict:
    """Re-reads a company's subscription from Stripe and applies it locally.

    Webhooks are how this app normally learns that a subscription started,
    changed or ended - and a webhook that never arrives leaves the database
    describing a company as free while Stripe bills it. That happens in
    local development every time (Stripe cannot reach localhost without
    `stripe listen`), and in production any time a delivery is lost for
    longer than Stripe retries.

    Deliberately routed through the same handlers the webhook uses, so
    there is one description of what a subscription means to this app
    rather than two that drift apart.

    Returns what it found, for a caller that wants to report it."""
    _require_configured()
    company = get_company_billing_info(company_id)
    if not company:
        raise ValueError(f"No company with id={company_id}")
    if not company["stripe_customer_id"]:
        return {"company_id": company_id, "found": None, "applied": False}

    subs = stripe.Subscription.list(
        customer=company["stripe_customer_id"], status="all", limit=10
    )
    # Newest first, and anything still live wins over anything finished.
    live = [s for s in subs.data if s["status"] not in ("canceled", "incomplete_expired")]
    chosen = live[0] if live else (subs.data[0] if subs.data else None)

    if chosen is None:
        return {"company_id": company_id, "found": None, "applied": False}

    if chosen["status"] in ("canceled", "incomplete_expired"):
        _handle_subscription_deleted(chosen)
    else:
        _handle_subscription_created(chosen)

    return {
        "company_id": company_id,
        "found": chosen["id"],
        "status": chosen["status"],
        "applied": True,
    }


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
