"""
One plan per company, and a record of who paid for it.

A company has a single subscription that the owner and every dispatcher
share, and any of them can be the one who buys it. That makes "who paid?"
a real question that nothing else could answer: Stripe knows the card but
not which login clicked, and the company row holds only the current state,
so an upgrade followed by a downgrade left no trace of the first.

The rules worth holding still are the awkward ones - that a webhook Stripe
re-sends does not become a second line in the history, that a login which
has since been deleted is still the answer to who paid back then, and that
a renewal Stripe collects by itself is recorded as a payment with nobody
behind it rather than credited to whoever last touched the account.
"""
import pytest

from db import models, repository
from db.database import get_session
from services import notification_events as events
from tests.conftest import csrf_headers, unique_mc


@pytest.fixture
def company(request):
    mc = unique_mc()
    with get_session() as session:
        row = models.Company(
            mc_number=mc,
            company_name=f"Billing History {mc}",
            telegram_group_prefix=f"BH{mc}",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


class TestRecordingWhoPaid:
    def test_a_subscription_records_the_login_behind_it(self, company):
        repository.record_billing_event(
            company, "subscribed", tier="pro", billing_interval="month",
            actor_type="dispatcher", actor_id=42, actor_label="night_desk",
        )
        paid_by = repository.who_pays(company)
        assert paid_by["actor_type"] == "dispatcher"
        assert paid_by["actor_label"] == "night_desk"
        assert paid_by["tier"] == "pro"
        assert paid_by["billing_interval"] == "month"
        assert paid_by["since"], "the page shows when, so it has to be there"

    def test_nobody_has_paid_yet(self, company):
        assert repository.who_pays(company) is None

    def test_a_renewal_nobody_clicked_does_not_become_the_payer(self, company):
        """Stripe collects renewals by itself. Crediting the last person who
        touched the account for a payment they did not make would be worse
        than saying nothing."""
        repository.record_billing_event(
            company, "subscribed", tier="pro", billing_interval="month",
            actor_type="owner", actor_id=company, actor_label="owner@example.com",
        )
        repository.record_billing_event(
            company, "payment", tier="pro", amount_cents=2000, currency="USD",
        )
        assert repository.who_pays(company)["actor_label"] == "owner@example.com"

    def test_the_name_survives_the_login_being_deleted(self, company):
        """A dispatcher who paid in March and left in June is still the
        answer to who paid in March, which is why the label is stored rather
        than joined to."""
        repository.record_billing_event(
            company, "subscribed", tier="pro",
            actor_type="dispatcher", actor_id=999999, actor_label="left_in_june",
        )
        # No dispatcher row with that id exists at all.
        assert repository.who_pays(company)["actor_label"] == "left_in_june"

    def test_the_most_recent_change_is_the_one_that_counts(self, company):
        repository.record_billing_event(
            company, "subscribed", tier="pro",
            actor_type="owner", actor_id=company, actor_label="first",
        )
        repository.record_billing_event(
            company, "plan_changed", tier="max_5x",
            actor_type="dispatcher", actor_id=7, actor_label="second",
        )
        paid_by = repository.who_pays(company)
        assert paid_by["actor_label"] == "second"
        assert paid_by["tier"] == "max_5x"


class TestTheHistory:
    def test_lines_come_back_newest_first(self, company):
        for kind in ("subscribed", "payment", "plan_changed"):
            repository.record_billing_event(company, kind, tier="pro")
        assert [e["kind"] for e in repository.list_billing_events(company)] == [
            "plan_changed", "payment", "subscribed",
        ]

    def test_money_is_kept_in_the_smallest_unit(self, company):
        """Storing dollars as a float is how a cent goes missing."""
        repository.record_billing_event(
            company, "payment", amount_cents=2000, currency="USD",
        )
        line = repository.list_billing_events(company)[0]
        assert line["amount_cents"] == 2000
        assert isinstance(line["amount_cents"], int)
        assert line["currency"] == "USD"

    def test_a_resent_webhook_does_not_become_a_second_line(self, company):
        """Stripe re-sends on purpose. Without the unique key one payment
        would show up in the history two or three times."""
        first = repository.record_billing_event(
            company, "payment", amount_cents=2000, stripe_event_id="evt_same",
        )
        second = repository.record_billing_event(
            company, "payment", amount_cents=2000, stripe_event_id="evt_same",
        )
        assert (first, second) == (True, False)
        assert len(repository.list_billing_events(company)) == 1

    def test_lines_without_a_stripe_event_are_not_deduplicated(self, company):
        """Two genuine plan changes made from the dashboard on the same day
        are two lines, not one."""
        assert repository.record_billing_event(company, "plan_changed", tier="pro") is True
        assert repository.record_billing_event(company, "plan_changed", tier="max_5x") is True
        assert len(repository.list_billing_events(company)) == 2

    def test_one_company_cannot_see_another_s_history(self, company):
        other = repository.record_billing_event(company, "payment", amount_cents=1)
        assert other is True
        assert repository.list_billing_events(company + 999_999) == []


class TestOverHTTP:
    def _owner(self, client) -> str:
        mc = unique_mc()
        response = client.post("/api/auth/register", json={
            "mc_number": mc,
            "company_name": f"History Co {mc}",
            "email": f"owner{mc}@example.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert response.status_code == 200, response.text
        return mc

    def test_the_endpoint_needs_a_session(self, client):
        assert client.get("/api/billing/history").status_code == 401

    def test_a_new_company_has_an_empty_history_and_no_payer(self, client):
        self._owner(client)
        body = client.get("/api/billing/history").json()
        assert body == {"paid_by": None, "events": []}

    def test_a_dispatcher_can_see_who_paid(self, client):
        """They share the plan and may have paid for it themselves - showing
        this to the owner alone would hide somebody's own payment from them."""
        mc = self._owner(client)
        created = client.post(
            "/api/dispatchers",
            json={"username": f"disp{mc}", "password": "dispatcherpass1"},
            headers=csrf_headers(client),
        )
        assert created.status_code == 200, created.text

        with get_session() as session:
            company_id = (
                session.query(models.Company)
                .filter(models.Company.mc_number == mc)
                .first().id
            )
        repository.record_billing_event(
            company_id, "subscribed", tier="pro", billing_interval="month",
            actor_type="dispatcher", actor_id=created.json()["id"],
            actor_label=f"disp{mc}",
        )

        client.post("/api/auth/logout", headers=csrf_headers(client))
        signed_in = client.post(
            "/api/auth/dispatcher",
            json={"username": f"disp{mc}", "password": "dispatcherpass1"},
        )
        assert signed_in.status_code == 200, signed_in.text

        body = client.get("/api/billing/history").json()
        assert body["paid_by"]["actor_label"] == f"disp{mc}"
        assert body["paid_by"]["tier"] == "pro"


class TestTheWholeCompanyIsTold:
    def test_every_billing_event_reaches_dispatchers_too(self):
        for event in events.EVENTS:
            if event.category == "billing":
                assert "dispatcher" in event.audience, event.key
