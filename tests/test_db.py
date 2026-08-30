"""
Test database models and repository functions.
"""
import itertools

import pytest
from db.database import init_db, get_session
from db import models, repository
from miniapp.auth import hash_password
from tests.conftest import unique_mc


# Unique identifiers for rows these tests create. Previously these were
# sliced off the front of a uuid4 integer (str(uuid.uuid4().int)[:4]), which
# looks random but is badly skewed: a uuid4 int is uniform over
# [0, 2**128), and 2**128 is ~3.4e38, so the decimal form nearly always
# starts with 1, 2 or 3 - measured, 65% of four-digit slices begin with 1
# or 2, and 200k draws only ever produced ~8,990 of the nominal 10,000
# values. Against the unique-constrained telegram_group_prefix that left
# roughly a 1-in-100 chance per run of an IntegrityError in whichever test
# happened to draw second, which is exactly the intermittent failure this
# replaces. A counter cannot collide by construction.
#
# The MC allocator lives in conftest so every suite draws from ONE sequence.
# Two modules each running their own counter produced identical numbers and
# reintroduced the very collision this was meant to end.
_ids = itertools.count(1)

_unique_mc = unique_mc


def _unique_prefix(mc: str) -> str:
    """Derived from the whole MC number, not a slice of it - a four-digit
    slice of a zero-padded counter would be "0000" for the first 10,000
    values, reintroducing the very collision this avoids."""
    return f"T{mc}"


def _unique_account_id() -> int:
    """A synthetic account/company id for tables that only store the id as a
    plain integer (credentials, 2FA). Offset well clear of the real
    auto-increment ids the other tests create, which start at 1."""
    return 9_000_000 + next(_ids)


@pytest.fixture(scope="module")
def setup_db():
    """Initialize test database"""
    init_db()
    yield


class TestDatabaseModels:
    """Test database models"""
    
    def test_create_company(self, setup_db):
        """Test creating a company"""
        unique_mc = _unique_mc()
        unique_prefix = _unique_prefix(unique_mc)
        
        with get_session() as session:
            company = models.Company(
                mc_number=unique_mc,
                company_name=f"Test Company {unique_mc}",
                telegram_group_prefix=unique_prefix,
                password_hash=hash_password("testpass123")
            )
            session.add(company)
            session.commit()
            session.refresh(company)
            
            assert company.id > 0
            assert company.mc_number == unique_mc
            assert company.password_hash is not None


class TestCompanyCredentials:
    """Regression coverage for save/get/delete_company_credential -
    get_company_credential used to fall off the end of the function with
    no return whenever a credential WAS found (only the "not found" path
    returned explicitly), so it always returned None even for a credential
    that existed; delete_company_credential had a stray line referencing
    an undefined variable that raised NameError after every delete. Both
    meant Gmail/Samsara "connect" silently never actually worked from the
    API's perspective, and "disconnect" always crashed."""

    def test_get_company_credential_returns_decrypted_value_when_present(self, setup_db):
        company_id = _unique_account_id()
        repository.save_company_credential(company_id, "gmail_refresh_token", "super-secret-token")

        result = repository.get_company_credential(company_id, "gmail_refresh_token")
        assert result == "super-secret-token"

    def test_get_company_credential_returns_none_when_absent(self, setup_db):
        result = repository.get_company_credential(999999999, "gmail_refresh_token")
        assert result is None

    def test_delete_company_credential_removes_it_without_raising(self, setup_db):
        company_id = _unique_account_id()
        repository.save_company_credential(company_id, "samsara_api_key", "some-api-key")
        assert repository.get_company_credential(company_id, "samsara_api_key") == "some-api-key"

        repository.delete_company_credential(company_id, "samsara_api_key")  # must not raise

        assert repository.get_company_credential(company_id, "samsara_api_key") is None


class TestRepository:
    """Test repository functions"""

    def test_get_company_by_mc(self, setup_db):
        """Test getting company by MC number"""
        unique_mc = _unique_mc()
        unique_prefix = _unique_prefix(unique_mc)
        
        # First create a test company
        with get_session() as session:
            company = models.Company(
                mc_number=unique_mc,
                company_name=f"Test Company {unique_mc}",
                telegram_group_prefix=unique_prefix,
                password_hash=hash_password("pass123")
            )
            session.add(company)
            session.commit()
        
        # Test repository function
        result = repository.get_company_by_mc(unique_mc)
        assert result is not None
        assert result.mc_number == unique_mc
    
    def test_get_nonexistent_company(self, setup_db):
        """Test getting non-existent company"""
        result = repository.get_company_by_mc("NOTEXIST999")
        assert result is None


class TestWebauthnChallengeRepository:
    """create_webauthn_challenge/consume_webauthn_challenge - the
    server-side, single-use challenge record WebAuthn's security model
    requires (see models.WebauthnChallenge's docstring)."""

    def test_consume_returns_the_stored_challenge_once(self, setup_db):
        account_id = _unique_account_id()
        repository.create_webauthn_challenge("owner", account_id, "register", "abc123challenge")

        first = repository.consume_webauthn_challenge("owner", account_id, "register")
        assert first == "abc123challenge"

        second = repository.consume_webauthn_challenge("owner", account_id, "register")
        assert second is None

    def test_consume_is_scoped_to_account_and_purpose(self, setup_db):
        account_id = _unique_account_id()
        # From the counter, not account_id + 1 - the next id the counter
        # hands out IS account_id + 1, so deriving it that way would alias a
        # later test's account.
        other_account_id = _unique_account_id()
        repository.create_webauthn_challenge("owner", account_id, "register", "for-registration")
        repository.create_webauthn_challenge("owner", account_id, "login", "for-login")

        # Wrong account - nothing to consume.
        assert repository.consume_webauthn_challenge("owner", other_account_id, "register") is None
        # Wrong purpose - nothing to consume, and the real one is untouched.
        assert repository.consume_webauthn_challenge("dispatcher", account_id, "register") is None

        assert repository.consume_webauthn_challenge("owner", account_id, "register") == "for-registration"
        assert repository.consume_webauthn_challenge("owner", account_id, "login") == "for-login"

    def test_consume_with_no_challenge_ever_issued_returns_none(self, setup_db):
        account_id = _unique_account_id()
        assert repository.consume_webauthn_challenge("owner", account_id, "register") is None


class TestDriverDetailsTotalLoads:
    """get_driver_details' total_loads used to be len(loads) - but that list
    is capped at 50 rows for the history table, so a driver with more than
    50 loads showed a "total loads" figure stuck at 50 forever. See
    db/repository.py's get_driver_details."""

    def test_total_loads_counts_beyond_the_50_row_history_cap(self, setup_db):
        unique_mc = _unique_mc()
        with get_session() as session:
            company = models.Company(
                mc_number=unique_mc,
                company_name=f"Total Loads Test {unique_mc}",
                telegram_group_prefix=_unique_prefix(unique_mc),
            )
            session.add(company)
            session.commit()
            session.refresh(company)

            driver = models.Driver(company_id=company.id, driver_bot_id="D001", full_name="Test Driver")
            session.add(driver)
            session.commit()
            session.refresh(driver)

            for i in range(55):
                session.add(models.Load(company_id=company.id, driver_id=driver.id, load_id=f"L{i}"))
            session.commit()

            company_id, driver_id = company.id, driver.id

        details = repository.get_driver_details(driver_id, company_id)
        assert details["total_loads"] == 55
        assert len(details["loads"]) == 50  # the history table itself stays capped


class TestDriverRepository:
    """create_driver (self-service driver creation) and link_driver_group
    (the /linkdriver half of the code-based Telegram group linking flow -
    see bot.py's handle_linkdriver and miniapp/api.py's POST /api/drivers)."""

    def _make_company_id(self) -> int:
        unique_mc = _unique_mc()
        with get_session() as session:
            company = models.Company(
                mc_number=unique_mc,
                company_name=f"Driver Repo Test {unique_mc}",
                telegram_group_prefix=_unique_prefix(unique_mc),
            )
            session.add(company)
            session.commit()
            session.refresh(company)
            return company.id

    def test_create_driver_auto_assigns_sequential_bot_id(self, setup_db):
        company_id = self._make_company_id()

        first = repository.create_driver(company_id, "Alice")
        second = repository.create_driver(company_id, "Bob")

        assert first["driver_bot_id"] == "D001"
        assert second["driver_bot_id"] == "D002"
        assert first["telegram_group_id"] is None
        assert first["subscription_active"] is True

    def test_link_driver_group_sets_group_fields(self, setup_db):
        company_id = self._make_company_id()
        driver = repository.create_driver(company_id, "Carol")

        result = repository.link_driver_group(driver["id"], -100555, "Carol's Truck")
        assert result == "ok"

        linked = repository.get_driver_by_group(-100555)
        assert linked is not None
        assert linked.id == driver["id"]
        assert linked.telegram_group_title == "Carol's Truck"

    def test_link_driver_group_rejects_group_already_used_by_another_driver(self, setup_db):
        company_id = self._make_company_id()
        driver_a = repository.create_driver(company_id, "Dave")
        driver_b = repository.create_driver(company_id, "Erin")
        repository.link_driver_group(driver_a["id"], -100777, "Dave's Truck")

        result = repository.link_driver_group(driver_b["id"], -100777, "Erin's Truck")
        assert result == "already_linked_elsewhere"

        # Dave's link must be untouched by Erin's failed attempt.
        still_daves = repository.get_driver_by_group(-100777)
        assert still_daves.id == driver_a["id"]

    def test_link_driver_group_returns_not_found_for_missing_driver(self, setup_db):
        result = repository.link_driver_group(999999999, -100888, "Ghost")
        assert result == "not_found"

    def test_relinking_same_driver_to_same_group_is_idempotent(self, setup_db):
        company_id = self._make_company_id()
        driver = repository.create_driver(company_id, "Frank")

        first = repository.link_driver_group(driver["id"], -100999, "Frank's Truck")
        second = repository.link_driver_group(driver["id"], -100999, "Frank's Truck (renamed)")

        assert first == "ok"
        assert second == "ok"
        linked = repository.get_driver_by_group(-100999)
        assert linked.telegram_group_title == "Frank's Truck (renamed)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
