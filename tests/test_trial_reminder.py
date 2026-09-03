"""The email that goes out before a trial turns into a charge.

Two days' notice, sent once. What matters here is mostly what must not
happen: no reminder after the charge has already landed, none twice, and no
warning about a charge to someone who has no card on file and will not be
charged at all.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

import bot
from db import models, repository
from db.database import get_session
from services import email_otp_service


def _company(session, *, tag, status="trialing", ends_in_hours=24,
             email="owner@example.com", reminded=False, tier="pro"):
    company = models.Company(
        mc_number=f"MC-{tag}",
        company_name=f"Carrier {tag}",
        telegram_group_prefix=tag,
        email=email,
        subscription_tier=tier,
        subscription_status=status,
        billing_interval="month",
        trial_ends_at=(
            models.now_utc() + timedelta(hours=ends_in_hours)
            if ends_in_hours is not None else None
        ),
        trial_reminder_sent_at=models.now_utc() if reminded else None,
    )
    session.add(company)
    session.commit()
    return company.id


@pytest.fixture
def tag(request):
    return f"TR{abs(hash(request.node.name)) % 100000}"


# ------------------------------------------------------------------
# Who gets one
# ------------------------------------------------------------------

def test_a_trial_ending_tomorrow_is_due(tag):
    with get_session() as session:
        company_id = _company(session, tag=tag, ends_in_hours=24)
    due = [c["id"] for c in repository.companies_due_trial_reminder(48)]
    assert company_id in due


def test_a_trial_ending_next_week_is_not_due_yet(tag):
    with get_session() as session:
        company_id = _company(session, tag=tag, ends_in_hours=24 * 6)
    due = [c["id"] for c in repository.companies_due_trial_reminder(48)]
    assert company_id not in due


def test_a_trial_that_already_ended_gets_nothing(tag):
    """A reminder after the charge is not a reminder."""
    with get_session() as session:
        company_id = _company(session, tag=tag, ends_in_hours=-2)
    due = [c["id"] for c in repository.companies_due_trial_reminder(48)]
    assert company_id not in due


def test_a_company_already_reminded_is_not_reminded_again(tag):
    with get_session() as session:
        company_id = _company(session, tag=tag, ends_in_hours=24, reminded=True)
    due = [c["id"] for c in repository.companies_due_trial_reminder(48)]
    assert company_id not in due


def test_a_company_that_is_not_on_a_trial_is_skipped(tag):
    with get_session() as session:
        company_id = _company(session, tag=tag, status="active", ends_in_hours=24)
    due = [c["id"] for c in repository.companies_due_trial_reminder(48)]
    assert company_id not in due


def test_a_company_with_no_email_is_skipped(tag):
    with get_session() as session:
        company_id = _company(session, tag=tag, email=None, ends_in_hours=24)
    due = [c["id"] for c in repository.companies_due_trial_reminder(48)]
    assert company_id not in due


def test_marking_it_sent_takes_it_off_the_list(tag):
    with get_session() as session:
        company_id = _company(session, tag=tag, ends_in_hours=24)
    assert company_id in [c["id"] for c in repository.companies_due_trial_reminder(48)]
    repository.mark_trial_reminder_sent(company_id)
    assert company_id not in [c["id"] for c in repository.companies_due_trial_reminder(48)]


# ------------------------------------------------------------------
# What it says
# ------------------------------------------------------------------

def _sent_body(**kwargs):
    defaults = {
        "company_name": "Carrier",
        "ends_on": "05 September 2026",
        "charge": "$20 a month",
        "has_card": True,
    }
    defaults.update(kwargs)
    with patch.object(email_otp_service, "is_configured", return_value=True), \
         patch.object(email_otp_service.smtplib, "SMTP") as smtp:
        server = MagicMock()
        smtp.return_value.__enter__.return_value = server
        email_otp_service.send_trial_ending_email("owner@example.com", **defaults)
    return server.sendmail.call_args.args[2]


def test_it_names_the_date_the_amount_and_the_way_out():
    body = _sent_body()
    assert "05 September 2026" in body
    assert "$20 a month" in body
    assert "cancel" in body.lower()
    assert "/settings" in body


def test_it_says_the_payment_method_is_held_until_the_first_charge():
    body = " ".join(_sent_body().split())
    assert "until this first payment goes through" in body
    assert "can't be removed" in body


def test_someone_with_no_card_is_not_warned_about_a_charge():
    """They will not be charged, so telling them they will is a lie that
    costs a customer."""
    body = " ".join(_sent_body(has_card=False).split())
    assert "no payment method on file, so nothing will be charged" in body
    assert "will be charged automatically" not in body


def test_when_stripe_cannot_be_asked_the_wording_covers_both():
    body = _sent_body(has_card=None)
    assert "depends on whether a payment method is on file" in " ".join(body.split())


def test_a_plan_with_no_price_does_not_get_one_invented():
    body = _sent_body(charge=None)
    assert "the price of your plan" in body
    assert "$" not in body.split("Manage or cancel")[0]


def test_the_subject_line_carries_the_date():
    """It has to be readable in an inbox list, unopened."""
    subject = next(
        line for line in _sent_body().splitlines() if line.startswith("Subject:")
    )
    assert "05 September 2026" in subject
    assert "trial ends" in subject.lower()


# ------------------------------------------------------------------
# The pass that sends them
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_successful_send_is_recorded(tag):
    with get_session() as session:
        company_id = _company(session, tag=tag, ends_in_hours=24)

    with patch.object(email_otp_service, "is_configured", return_value=True), \
         patch.object(email_otp_service, "send_trial_ending_email") as send, \
         patch.object(bot, "_has_card_on_file", return_value=True):
        await bot._send_trial_reminders_once()

    # One pass sends to every company inside the window, and earlier tests
    # in this run leave theirs there, so this looks for its own rather than
    # counting calls.
    mine = [c for c in send.call_args_list if c.kwargs["company_name"] == f"Carrier {tag}"]
    assert len(mine) == 1
    assert mine[0].args[0] == "owner@example.com"
    assert mine[0].kwargs["charge"] == "$20 a month"
    assert company_id not in [c["id"] for c in repository.companies_due_trial_reminder(48)]


@pytest.mark.asyncio
async def test_a_send_that_fails_is_tried_again_next_pass(tag):
    """Stamped only after the message is away, so a bad minute at the mail
    server does not cost someone their notice."""
    with get_session() as session:
        company_id = _company(session, tag=tag, ends_in_hours=24)

    with patch.object(email_otp_service, "is_configured", return_value=True), \
         patch.object(email_otp_service, "send_trial_ending_email",
                      side_effect=OSError("connection refused")), \
         patch.object(bot, "_has_card_on_file", return_value=True):
        await bot._send_trial_reminders_once()

    assert company_id in [c["id"] for c in repository.companies_due_trial_reminder(48)]


@pytest.mark.asyncio
async def test_nothing_is_marked_when_smtp_is_not_configured(tag):
    with get_session() as session:
        company_id = _company(session, tag=tag, ends_in_hours=24)

    with patch.object(email_otp_service, "is_configured", return_value=False), \
         patch.object(email_otp_service, "send_trial_ending_email") as send:
        await bot._send_trial_reminders_once()

    send.assert_not_called()
    assert company_id in [c["id"] for c in repository.companies_due_trial_reminder(48)]


def test_a_company_with_no_stripe_customer_has_no_card():
    assert bot._has_card_on_file(None, 1) is False


def test_an_unreachable_stripe_is_unknown_rather_than_assumed():
    with patch("services.stripe_service.list_payment_methods", side_effect=RuntimeError("down")):
        assert bot._has_card_on_file("cus_123", 1) is None
