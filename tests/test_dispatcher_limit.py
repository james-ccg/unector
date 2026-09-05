"""
How many dispatcher logins a plan allows.

A dispatcher is a seat in the office rather than a truck on the road, so
the caps are smaller than the driver ones and scale the same way. Two rules
are worth holding still: the allowance follows the *effective* tier, which
drops back to free while a subscription is not in good standing, and going
over the cap never costs anybody a login they already have.

The marketing copy is checked here too. It claimed unlimited dispatchers on
one plan and said nothing on the others while the code capped none of
them - which is the kind of gap that turns into an argument with a customer
who read the page.
"""
import pathlib
import re

import pytest

from config import DISPATCHER_LIMITS, PLAN_LIMITS
from db import models
from db.database import get_session
from tests.conftest import csrf_headers, unique_mc

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRICING = (ROOT / "frontend" / "src" / "pages" / "PricingPage.tsx").read_text(encoding="utf-8")
HOME = (ROOT / "frontend" / "src" / "pages" / "HomePage.tsx").read_text(encoding="utf-8")
FAQ = (ROOT / "frontend" / "src" / "pages" / "FAQPage.tsx").read_text(encoding="utf-8")


def _owner(client) -> str:
    mc = unique_mc()
    response = client.post("/api/auth/register", json={
        "mc_number": mc,
        "company_name": f"Seat Test {mc}",
        "email": f"owner{mc}@example.com",
        "password": "ownerpass123",
        "confirm_password": "ownerpass123",
    })
    assert response.status_code == 200, response.text
    return mc


def _add_dispatcher(client, username: str):
    return client.post(
        "/api/dispatchers",
        json={"username": username, "password": "dispatchpass1"},
        headers=csrf_headers(client),
    )


def _set_plan(mc: str, tier: str, status: str = "active"):
    with get_session() as session:
        company = (
            session.query(models.Company).filter(models.Company.mc_number == mc).first()
        )
        company.subscription_tier = tier
        company.subscription_status = status
        session.commit()


class TestTheCaps:
    def test_every_tier_with_a_driver_cap_has_a_dispatcher_cap(self):
        """A tier missing from one table and present in the other would fall
        through to the free allowance without anybody meaning it to."""
        assert set(DISPATCHER_LIMITS) == set(PLAN_LIMITS)

    def test_the_office_is_smaller_than_the_fleet(self):
        """One dispatcher runs several trucks. A cap larger than the driver
        cap would be describing a company that does not exist."""
        for tier, seats in DISPATCHER_LIMITS.items():
            if seats is not None:
                assert seats <= PLAN_LIMITS[tier], tier

    def test_the_largest_plan_is_uncapped(self):
        assert DISPATCHER_LIMITS["max_20x"] is None


class TestEnforcement:
    def test_the_free_plan_gets_one(self, client):
        _owner(client)
        assert _add_dispatcher(client, f"d{unique_mc()}").status_code == 200

        refused = _add_dispatcher(client, f"d{unique_mc()}")
        assert refused.status_code == 402, refused.text
        assert "free plan allows up to 1" in refused.json()["detail"]

    def test_the_message_says_the_number_and_what_to_do(self, client):
        """An error that just says no leaves the reader guessing at both."""
        _owner(client)
        _add_dispatcher(client, f"d{unique_mc()}")
        detail = _add_dispatcher(client, f"d{unique_mc()}").json()["detail"]
        assert "1 dispatcher login(s)" in detail
        assert "Upgrade" in detail

    def test_a_paid_plan_gets_more(self, client):
        mc = _owner(client)
        _set_plan(mc, "pro")
        for _ in range(DISPATCHER_LIMITS["pro"]):
            assert _add_dispatcher(client, f"d{unique_mc()}").status_code == 200
        assert _add_dispatcher(client, f"d{unique_mc()}").status_code == 402

    def test_an_unpaid_subscription_falls_back_to_the_free_allowance(self, client):
        """Tier alone is not enough - a past_due Max company is not entitled
        to Max seats until the payment is put right."""
        mc = _owner(client)
        _set_plan(mc, "max_5x", status="past_due")
        assert _add_dispatcher(client, f"d{unique_mc()}").status_code == 200
        assert _add_dispatcher(client, f"d{unique_mc()}").status_code == 402

    def test_the_uncapped_plan_keeps_going(self, client):
        mc = _owner(client)
        _set_plan(mc, "max_20x")
        for _ in range(4):
            assert _add_dispatcher(client, f"d{unique_mc()}").status_code == 200

    def test_a_downgrade_does_not_take_a_login_away(self, client):
        """Locking somebody out of an account they still pay for, because a
        card expired, is not a thing to do automatically."""
        mc = _owner(client)
        _set_plan(mc, "pro")
        for _ in range(3):
            _add_dispatcher(client, f"d{unique_mc()}")

        _set_plan(mc, "free")
        assert len(client.get("/api/dispatchers").json()) == 3
        # Only adding another is refused.
        assert _add_dispatcher(client, f"d{unique_mc()}").status_code == 402


class TestWhatBillingReports:
    def test_the_allowance_is_reported(self, client):
        mc = _owner(client)
        _set_plan(mc, "pro")
        _add_dispatcher(client, f"d{unique_mc()}")

        body = client.get("/api/billing").json()
        assert body["max_dispatchers"] == DISPATCHER_LIMITS["pro"]
        assert body["dispatchers"] == 1

    def test_no_cap_is_reported_as_null_rather_than_a_number(self, client):
        """A made-up large number would eventually be shown to somebody."""
        mc = _owner(client)
        _set_plan(mc, "max_20x")
        assert client.get("/api/billing").json()["max_dispatchers"] is None


class TestTheCopyMatchesTheCode:
    def test_the_old_blanket_promise_is_gone(self):
        """"Unlimited dispatchers", flat, was on the pricing page and the
        homepage. Every plan really was uncapped then; now only the largest
        is, so the unqualified version is simply false."""
        for page, name in ((PRICING, "PricingPage"), (HOME, "HomePage"), (FAQ, "FAQPage")):
            assert "Unlimited dispatchers" not in page, name

    def test_unlimited_is_only_claimed_where_there_is_no_cap(self):
        """Max 20x genuinely has none, so it is allowed to say so - and it
        is the only tier that may. Anchored to the tier whose entry the
        phrase sits in, so moving it to a capped plan fails here."""
        uncapped = {tier for tier, seats in DISPATCHER_LIMITS.items() if seats is None}
        assert uncapped == {"max_20x"}

        entries = dict(re.findall(r"'(5x|20x)': \{(.*?)\n  \}", PRICING, re.DOTALL))
        assert set(entries) == {"5x", "20x"}, sorted(entries)
        assert "Unlimited dispatcher" in entries["20x"]
        assert "Unlimited dispatcher" not in entries["5x"]

    @pytest.mark.parametrize("tier", ["free", "pro", "max_5x"])
    def test_the_pricing_page_names_each_capped_allowance(self, tier):
        """A number on the page that does not appear in the code is the
        version customers will quote back at you."""
        seats = DISPATCHER_LIMITS[tier]
        assert re.search(rf"{seats} dispatcher", PRICING), f"{tier}: {seats}"
