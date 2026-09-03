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


class TestPaymentMethodsOnTheirOwn:
    """A card should be attachable and detachable independently of a plan.

    That was the whole point of adding this: on the free plan there was no
    way to put one on file at all, and the only route to removing one ran
    through a subscription. Saving is Checkout in setup mode, which needs
    no subscription and charges nothing."""

    def _methods(self, count: int) -> list[dict]:
        return [
            {"id": f"pm_{i}", "type": "card", "brand": "visa", "last4": f"000{i}",
             "exp_month": 1, "exp_year": 2030, "is_default": i == 0}
            for i in range(count)
        ]

    def test_saving_a_card_uses_setup_mode_and_charges_nothing(self, monkeypatch):
        monkeypatch.setattr(
            stripe_service, "get_company_billing_info", lambda company_id: _fake_company(None)
        )
        create_session = MagicMock()
        create_session.return_value = MagicMock(url="https://checkout.example/setup")
        monkeypatch.setattr(stripe_service.stripe.checkout.Session, "create", create_session)

        stripe_service.create_setup_session(1)

        kwargs = create_session.call_args.kwargs
        assert kwargs["mode"] == "setup"
        assert "line_items" not in kwargs

    def test_the_last_card_cannot_be_removed_from_a_live_subscription(self, monkeypatch):
        """Not to trap anyone - the next invoice would simply fail, and the
        account would lapse without the person who did it understanding
        why. The message says to cancel first."""
        monkeypatch.setattr(
            stripe_service, "get_company_billing_info", lambda company_id: _fake_company("active")
        )
        monkeypatch.setattr(stripe_service, "list_payment_methods", lambda company_id: self._methods(1))
        detach = MagicMock()
        monkeypatch.setattr(stripe_service.stripe.PaymentMethod, "detach", detach)

        with pytest.raises(ValueError, match="only payment method"):
            stripe_service.detach_payment_method(1, "pm_0")

        detach.assert_not_called()

    def test_one_of_several_can_always_be_removed(self, monkeypatch):
        monkeypatch.setattr(
            stripe_service, "get_company_billing_info", lambda company_id: _fake_company("active")
        )
        monkeypatch.setattr(stripe_service, "list_payment_methods", lambda company_id: self._methods(2))
        detach = MagicMock()
        monkeypatch.setattr(stripe_service.stripe.PaymentMethod, "detach", detach)

        stripe_service.detach_payment_method(1, "pm_1")

        detach.assert_called_once_with("pm_1")

    def test_the_last_card_can_go_once_nothing_is_billing(self, monkeypatch):
        """No live subscription, so nothing breaks by removing it - this is
        the case that was impossible before."""
        monkeypatch.setattr(
            stripe_service, "get_company_billing_info", lambda company_id: _fake_company("canceled")
        )
        monkeypatch.setattr(stripe_service, "list_payment_methods", lambda company_id: self._methods(1))
        detach = MagicMock()
        monkeypatch.setattr(stripe_service.stripe.PaymentMethod, "detach", detach)

        stripe_service.detach_payment_method(1, "pm_0")

        detach.assert_called_once_with("pm_0")

    def test_a_card_belonging_to_someone_else_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            stripe_service, "get_company_billing_info", lambda company_id: _fake_company("active")
        )
        monkeypatch.setattr(stripe_service, "list_payment_methods", lambda company_id: self._methods(2))
        detach = MagicMock()
        monkeypatch.setattr(stripe_service.stripe.PaymentMethod, "detach", detach)

        with pytest.raises(ValueError, match="not on this account"):
            stripe_service.detach_payment_method(1, "pm_from_another_company")

        detach.assert_not_called()
