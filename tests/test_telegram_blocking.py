"""
Blocking the bot, and what must not happen because of it.

Telegram reports a block and an unblock the same way - a my_chat_member
update on the private chat, with the new status "kicked" or "member". That
is the only way to learn either; a bot cannot ask, and the alternative is
finding out from a 403 on the message that mattered.

The rule this file exists to hold: **blocking never disconnects anything**.
Unblocking should resume delivery on its own, and requiring somebody to
re-link after every block is a chore they would skip - which leaves the
channel dead while the settings screen still says connected, the exact
failure the whole feature was built to stop.
"""
import pytest

from db import models, repository
from db.database import get_session, init_db
from tests.conftest import unique_mc


@pytest.fixture
def db():
    init_db()
    yield


@pytest.fixture
def account(db):
    return "owner", 8_300_000 + int(unique_mc()[-5:] or 1)


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


class TestBlocking:
    def test_a_block_is_recorded(self, account):
        account_type, account_id = account
        repository.link_telegram_account(account_type, account_id, 991001, "someone")

        assert repository.set_telegram_blocked(991001, True) == 1
        assert repository.telegram_presence(account_type, account_id)["blocked"] is True

    def test_a_block_does_not_disconnect(self, account):
        """The point of the whole file. Delivery stops; the connection does
        not, so unblocking is all it takes."""
        account_type, account_id = account
        repository.link_telegram_account(account_type, account_id, 991002, "someone")
        repository.set_telegram_blocked(991002, True)

        presence = repository.telegram_presence(account_type, account_id)
        assert presence["connected"] is True
        assert presence["username"] == "someone"
        assert _row(account_type, account_id).telegram_user_id == 991002

    def test_unblocking_clears_it(self, account):
        account_type, account_id = account
        repository.link_telegram_account(account_type, account_id, 991003, "someone")
        repository.set_telegram_blocked(991003, True)

        repository.set_telegram_blocked(991003, False)
        assert repository.telegram_presence(account_type, account_id)["blocked"] is False

    def test_a_block_does_not_touch_two_factor(self, account):
        """Blocking the bot is not a request to change how you sign in."""
        account_type, account_id = account
        repository.set_telegram_otp(account_type, account_id, 991004, enabled=True)

        repository.set_telegram_blocked(991004, True)
        row = _row(account_type, account_id)
        assert row.telegram_otp_enabled is True
        assert row.telegram_user_id == 991004

    def test_one_person_connected_twice_is_updated_everywhere(self, db):
        """Somebody can be an owner at their own company and a dispatcher at
        another. One Telegram account, two rows, and blocking makes both
        equally unreachable - which is why this is keyed by Telegram id."""
        first = ("owner", 8_400_001)
        second = ("dispatcher", 8_400_002)
        repository.link_telegram_account(*first, 991005, "someone")
        repository.link_telegram_account(*second, 991005, "someone")

        assert repository.set_telegram_blocked(991005, True) == 2
        assert repository.telegram_presence(*first)["blocked"] is True
        assert repository.telegram_presence(*second)["blocked"] is True

    def test_a_stranger_blocking_changes_nothing(self, db):
        """Anybody can open the bot and block it without ever connecting."""
        assert repository.set_telegram_blocked(999_999_999, True) == 0

    def test_connecting_again_clears_a_block(self, account):
        """Somebody who blocked, unblocked, and came back through the link
        should not still read as blocked afterwards."""
        account_type, account_id = account
        repository.link_telegram_account(account_type, account_id, 991006, "someone")
        repository.set_telegram_blocked(991006, True)

        repository.link_telegram_account(account_type, account_id, 991006, "someone")
        assert repository.telegram_presence(account_type, account_id)["blocked"] is False


class TestWhichAccountIsConnected:
    def test_the_username_is_remembered(self, account):
        """"Connected" says nothing about whose Telegram, and somebody with
        two accounts cannot tell from it whether it is the one they meant."""
        account_type, account_id = account
        repository.link_telegram_account(account_type, account_id, 991007, "night_desk")
        assert repository.telegram_presence(account_type, account_id)["username"] == "night_desk"

    def test_an_unconnected_account_reports_nothing(self, account):
        account_type, account_id = account
        assert repository.telegram_presence(account_type, account_id) == {
            "connected": False, "username": None, "blocked": False,
        }


class TestDispatchersHaveNoEmail:
    """One company, one mailbox - the owner's, because that is the one broker
    email is sent from. A dispatcher's two-factor address is for getting in,
    not for company news, and giving mail a second place to land would make
    "which address did that go to" a question with no good answer."""

    def _company_with_dispatcher(self):
        mc = unique_mc()
        with get_session() as session:
            company = models.Company(
                mc_number=mc,
                company_name=f"No Mail {mc}",
                telegram_group_prefix=f"NM{mc}",
                email=f"owner{mc}@example.com",
            )
            session.add(company)
            session.commit()
            session.refresh(company)

            dispatcher = models.Dispatcher(
                company_id=company.id, username=f"disp{mc}", password_hash="x",
            )
            session.add(dispatcher)
            session.commit()
            session.refresh(dispatcher)
            return company.id, dispatcher.id

    def test_the_owner_still_has_one(self, db):
        company_id, _ = self._company_with_dispatcher()
        owner = next(
            p for p in repository.office_recipients(company_id) if p["account_type"] == "owner"
        )
        assert owner["email"]

    def test_a_dispatcher_never_does(self, db):
        company_id, dispatcher_id = self._company_with_dispatcher()
        dispatcher = next(
            p for p in repository.office_recipients(company_id)
            if p["account_type"] == "dispatcher"
        )
        assert dispatcher["email"] is None

    def test_not_even_their_two_factor_address(self, db):
        """That address exists so they can receive a sign-in code. It is not
        an inbox for company news, and reusing it as one is how it became a
        second company mailbox by accident."""
        company_id, dispatcher_id = self._company_with_dispatcher()
        repository.set_email_otp("dispatcher", dispatcher_id, "personal@example.com", enabled=True)

        dispatcher = next(
            p for p in repository.office_recipients(company_id)
            if p["account_type"] == "dispatcher"
        )
        assert dispatcher["email"] is None
