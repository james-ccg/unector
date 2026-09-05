"""
Connecting a Telegram account so notifications can reach it.

The rule this is all shaped around is Telegram's, not ours: a bot cannot
message somebody who has never opened a chat with it. sendMessage answers
403, and no API, permission or consent given on our site changes that. So
the goal is not to avoid the step - it cannot be avoided - but to make it
one tap, and to stop a switch that can never deliver from looking like one
that works.

Two things here would be quietly destructive if they went wrong, and both
have their own test: connecting must not disturb two-factor, and
disconnecting must not strip the id out from under a two-factor method that
is still relying on it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from db import models, repository
from db.database import get_session
from services import telegram_link
from tests.conftest import csrf_headers, unique_mc


@pytest.fixture
def account(setup_db_once):
    """An owner-shaped account id nothing else in the suite uses."""
    return "owner", 8_100_000 + int(unique_mc()[-5:] or 1)


@pytest.fixture
def setup_db_once():
    from db.database import init_db

    init_db()
    yield


def _row(account_type, account_id):
    with get_session() as session:
        return (
            session.query(models.TwoFactorSecret)
            .filter(
                models.TwoFactorSecret.account_type == account_type,
                models.TwoFactorSecret.account_id == account_id,
            )
            .first()
        )


class TestConnecting:
    def test_linking_records_where_to_send(self, account):
        account_type, account_id = account
        repository.link_telegram_account(account_type, account_id, 555001)
        assert repository.telegram_account_linked(account_type, account_id) is True
        assert _row(account_type, account_id).telegram_user_id == 555001

    def test_an_unlinked_account_reports_so(self, account):
        account_type, account_id = account
        assert repository.telegram_account_linked(account_type, account_id) is False

    def test_connecting_does_not_switch_two_factor_on(self, account):
        """Wanting news in Telegram is not consent to depend on Telegram to
        get in. Those are separate decisions on separate screens."""
        account_type, account_id = account
        repository.link_telegram_account(account_type, account_id, 555002)
        assert _row(account_type, account_id).telegram_otp_enabled is False

    def test_reconnecting_does_not_switch_two_factor_off(self, account):
        """The destructive version of the same mistake, and the reason this
        does not go through set_telegram_otp: that writes the flag too, so
        reconnecting for notifications would silently remove a second
        factor."""
        account_type, account_id = account
        repository.set_telegram_otp(account_type, account_id, 555003, enabled=True)

        repository.link_telegram_account(account_type, account_id, 555004)

        row = _row(account_type, account_id)
        assert row.telegram_user_id == 555004
        assert row.telegram_otp_enabled is True


class TestDisconnecting:
    def test_a_plain_connection_can_be_removed(self, account):
        account_type, account_id = account
        repository.link_telegram_account(account_type, account_id, 555005)

        assert repository.unlink_telegram_account(account_type, account_id) == (True, "ok")
        assert repository.telegram_account_linked(account_type, account_id) is False

    def test_removing_one_that_was_never_there_is_not_an_error(self, account):
        account_type, account_id = account
        assert repository.unlink_telegram_account(account_type, account_id) == (True, "ok")

    def test_it_refuses_while_two_factor_depends_on_it(self, account):
        """Clearing the id would leave that method pointing nowhere, and the
        way somebody finds out is being unable to sign in."""
        account_type, account_id = account
        repository.set_telegram_otp(account_type, account_id, 555006, enabled=True)

        ok, reason = repository.unlink_telegram_account(account_type, account_id)
        assert (ok, reason) == (False, "used_for_2fa")
        assert _row(account_type, account_id).telegram_user_id == 555006


class TestTheLink:
    def test_a_deep_link_carries_the_code(self, account, monkeypatch):
        account_type, account_id = account
        monkeypatch.setattr(telegram_link, "bot_username", lambda refresh=False: "Unector_bot")

        issued = telegram_link.issue_link(account_type, account_id)
        assert issued["url"] == f"https://t.me/Unector_bot?start={issued['code']}"

    def test_the_code_is_spendable_by_the_bot(self, account, monkeypatch):
        """Same token /verify2fa consumes - one thing to expire, one place a
        code can be spent."""
        account_type, account_id = account
        monkeypatch.setattr(telegram_link, "bot_username", lambda refresh=False: "Unector_bot")

        issued = telegram_link.issue_link(account_type, account_id)
        spent = repository.consume_telegram_link_token(issued["code"])
        assert spent["account_type"] == account_type
        assert spent["account_id"] == account_id

    def test_a_code_cannot_be_spent_twice(self, account, monkeypatch):
        account_type, account_id = account
        monkeypatch.setattr(telegram_link, "bot_username", lambda refresh=False: "Unector_bot")

        issued = telegram_link.issue_link(account_type, account_id)
        assert repository.consume_telegram_link_token(issued["code"]) is not None
        assert repository.consume_telegram_link_token(issued["code"]) is None

    def test_no_bot_username_means_no_link_rather_than_a_broken_one(self, account, monkeypatch):
        """A link to https://t.me/None would open nothing. The code and the
        command still work, so the caller shows those instead."""
        account_type, account_id = account
        monkeypatch.setattr(telegram_link, "bot_username", lambda refresh=False: None)

        issued = telegram_link.issue_link(account_type, account_id)
        assert issued["url"] is None
        assert issued["code"]

    def test_the_link_expires(self, account, monkeypatch):
        """Half an hour: long enough to walk to a phone, short enough that a
        tab left open overnight cannot connect somebody else's account."""
        assert telegram_link.LINK_TOKEN_MINUTES == 30

        account_type, account_id = account
        monkeypatch.setattr(telegram_link, "bot_username", lambda refresh=False: "Unector_bot")
        issued = telegram_link.issue_link(account_type, account_id)

        with get_session() as session:
            row = (
                session.query(models.TelegramLinkToken)
                .filter(models.TelegramLinkToken.code == issued["code"])
                .first()
            )
            assert row is not None
            expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert expires <= datetime.now(timezone.utc) + timedelta(minutes=31)


class TestOverHTTP:
    def _owner(self, client):
        mc = unique_mc()
        response = client.post("/api/auth/register", json={
            "mc_number": mc,
            "company_name": f"Connect {mc}",
            "email": f"owner{mc}@example.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert response.status_code == 200, response.text
        return mc

    def test_the_endpoints_need_a_session(self, client):
        assert client.post("/api/notifications/telegram/link").status_code == 401
        assert client.delete("/api/notifications/telegram/link").status_code == 401

    def test_preferences_say_whether_telegram_can_be_reached(self, client):
        """A switch turned on with nowhere to send to looks exactly like one
        that is working, until the message nobody got."""
        self._owner(client)
        body = client.get("/api/notifications/preferences").json()
        assert body["telegram"] == {"connected": False, "username": None, "blocked": False}

    def test_a_link_can_be_issued_and_then_reports_connected(self, client, monkeypatch):
        monkeypatch.setattr(telegram_link, "bot_username", lambda refresh=False: "Unector_bot")
        self._owner(client)

        issued = client.post(
            "/api/notifications/telegram/link", headers=csrf_headers(client),
        )
        assert issued.status_code == 200, issued.text
        body = issued.json()
        assert body["url"].startswith("https://t.me/Unector_bot?start=")
        assert body["bot_command"] == f"/start {body['code']}"

        # What the bot does when Start is pressed.
        spent = repository.consume_telegram_link_token(body["code"])
        repository.link_telegram_account(
            spent["account_type"], spent["account_id"], 777001, "night_desk",
        )

        prefs = client.get("/api/notifications/preferences").json()
        assert prefs["telegram"]["connected"] is True
        assert prefs["telegram"]["blocked"] is False

    def test_disconnecting_is_refused_while_two_factor_needs_it(self, client, monkeypatch):
        monkeypatch.setattr(telegram_link, "bot_username", lambda refresh=False: "Unector_bot")
        mc = self._owner(client)

        with get_session() as session:
            company_id = (
                session.query(models.Company)
                .filter(models.Company.mc_number == mc)
                .first().id
            )
        repository.set_telegram_otp("owner", company_id, 777002, enabled=True)

        response = client.delete(
            "/api/notifications/telegram/link", headers=csrf_headers(client),
        )
        assert response.status_code == 409, response.text
        assert "two-factor" in response.json()["detail"]
