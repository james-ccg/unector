"""
Tests for services/stripe_service.py's create_checkout_session guard.

A second checkout must be blocked for ANY subscription status where a
Stripe subscription object still exists and might still be billing - not
just "active"/"trialing". Before this fix, a company stuck in "past_due" or
"unpaid" (a failed renewal Stripe is still retrying) could start a brand
new Checkout Session on the same Stripe customer, ending up with two live
subscriptions - the company row only ever tracks one stripe_subscription_id,
so the older one would keep charging the card with nothing left pointing
at it. See services/stripe_service.py's create_checkout_session.
"""
from unittest.mock import MagicMock

import pytest

from services import stripe_service


def _fake_company(status: str | None) -> dict:
    return {
        "id": 1,
        "email": "owner@example.com",
        "mc_number": "123456",
        "company_name": "Test Co",
        "subscription_tier": "pro",
        "subscription_status": status,
        "stripe_customer_id": "cus_existing",
    }


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(stripe_service, "STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setattr(
        stripe_service, "PLAN_PRICE_IDS",
        {"pro": {"month": "price_dummy_month", "year": "price_dummy_year"}},
    )


@pytest.mark.parametrize(
    "status", ["active", "trialing", "past_due", "unpaid", "incomplete", "paused"]
)
def test_checkout_blocked_while_a_subscription_is_still_live(monkeypatch, status):
    monkeypatch.setattr(stripe_service, "get_company_billing_info", lambda company_id: _fake_company(status))
    create_session = MagicMock()
    monkeypatch.setattr(stripe_service.stripe.checkout.Session, "create", create_session)

    with pytest.raises(RuntimeError, match="already has a subscription"):
        stripe_service.create_checkout_session(1, "pro", "month")

    create_session.assert_not_called()


@pytest.mark.parametrize("status", [None, "canceled", "incomplete_expired"])
def test_checkout_allowed_when_no_subscription_is_live(monkeypatch, status):
    monkeypatch.setattr(stripe_service, "get_company_billing_info", lambda company_id: _fake_company(status))
    monkeypatch.setattr(stripe_service, "check_trial_eligibility", lambda *a, **k: False)
    create_session = MagicMock(return_value=MagicMock(url="https://checkout.stripe.com/fake"))
    monkeypatch.setattr(stripe_service.stripe.checkout.Session, "create", create_session)

    url = stripe_service.create_checkout_session(1, "pro", "month")

    assert url == "https://checkout.stripe.com/fake"
    create_session.assert_called_once()


class TestTrialDoesNotDemandACard:
    """A trial that asks for a card before it starts is not really a trial.

    Stripe collects one anyway unless told otherwise, and if a trial then
    runs out with no card on file its default is to raise an invoice and
    park the subscription in past_due - a debt owed by someone who never
    agreed to pay. Both are configured explicitly here."""

    def test_checkout_does_not_collect_a_card_up_front(self, monkeypatch):
        monkeypatch.setattr(
            stripe_service, "get_company_billing_info", lambda company_id: _fake_company(None)
        )
        monkeypatch.setattr(stripe_service, "check_trial_eligibility", lambda *a, **k: True)
        create_session = MagicMock()
        create_session.return_value = MagicMock(url="https://checkout.example/session")
        monkeypatch.setattr(stripe_service.stripe.checkout.Session, "create", create_session)

        stripe_service.create_checkout_session(1, "pro", "month")

        kwargs = create_session.call_args.kwargs
        assert kwargs["payment_method_collection"] == "if_required"

    def test_a_trial_that_ends_without_a_card_pauses_rather_than_owing(self, monkeypatch):
        monkeypatch.setattr(
            stripe_service, "get_company_billing_info", lambda company_id: _fake_company(None)
        )
        monkeypatch.setattr(stripe_service, "check_trial_eligibility", lambda *a, **k: True)
        create_session = MagicMock()
        create_session.return_value = MagicMock(url="https://checkout.example/session")
        monkeypatch.setattr(stripe_service.stripe.checkout.Session, "create", create_session)

        stripe_service.create_checkout_session(1, "pro", "month")

        subscription_data = create_session.call_args.kwargs["subscription_data"]
        assert subscription_data["trial_period_days"] == 7
        assert (
            subscription_data["trial_settings"]["end_behavior"]["missing_payment_method"]
            == "pause"
        )
