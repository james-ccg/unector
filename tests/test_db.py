"""
Test database models and repository functions.
"""
import pytest
import uuid
from db.database import init_db, get_session
from db import models, repository
from miniapp.auth import hash_password


@pytest.fixture(scope="module")
def setup_db():
    """Initialize test database"""
    init_db()
    yield


class TestDatabaseModels:
    """Test database models"""
    
    def test_create_company(self, setup_db):
        """Test creating a company"""
        unique_mc = str(uuid.uuid4().int)[:6]  # Unique MC number
        unique_prefix = f"T{unique_mc[:4]}"
        
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
        company_id = int(str(uuid.uuid4().int)[:8])
        repository.save_company_credential(company_id, "gmail_refresh_token", "super-secret-token")

        result = repository.get_company_credential(company_id, "gmail_refresh_token")
        assert result == "super-secret-token"

    def test_get_company_credential_returns_none_when_absent(self, setup_db):
        result = repository.get_company_credential(999999999, "gmail_refresh_token")
        assert result is None

    def test_delete_company_credential_removes_it_without_raising(self, setup_db):
        company_id = int(str(uuid.uuid4().int)[:8])
        repository.save_company_credential(company_id, "samsara_api_key", "some-api-key")
        assert repository.get_company_credential(company_id, "samsara_api_key") == "some-api-key"

        repository.delete_company_credential(company_id, "samsara_api_key")  # must not raise

        assert repository.get_company_credential(company_id, "samsara_api_key") is None


class TestRepository:
    """Test repository functions"""

    def test_get_company_by_mc(self, setup_db):
        """Test getting company by MC number"""
        unique_mc = str(uuid.uuid4().int)[:6]
        unique_prefix = f"T{unique_mc[:4]}"
        
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
        account_id = int(str(uuid.uuid4().int)[:8])
        repository.create_webauthn_challenge("owner", account_id, "register", "abc123challenge")

        first = repository.consume_webauthn_challenge("owner", account_id, "register")
        assert first == "abc123challenge"

        second = repository.consume_webauthn_challenge("owner", account_id, "register")
        assert second is None

    def test_consume_is_scoped_to_account_and_purpose(self, setup_db):
        account_id = int(str(uuid.uuid4().int)[:8])
        other_account_id = account_id + 1
        repository.create_webauthn_challenge("owner", account_id, "register", "for-registration")
        repository.create_webauthn_challenge("owner", account_id, "login", "for-login")

        # Wrong account - nothing to consume.
        assert repository.consume_webauthn_challenge("owner", other_account_id, "register") is None
        # Wrong purpose - nothing to consume, and the real one is untouched.
        assert repository.consume_webauthn_challenge("dispatcher", account_id, "register") is None

        assert repository.consume_webauthn_challenge("owner", account_id, "register") == "for-registration"
        assert repository.consume_webauthn_challenge("owner", account_id, "login") == "for-login"

    def test_consume_with_no_challenge_ever_issued_returns_none(self, setup_db):
        account_id = int(str(uuid.uuid4().int)[:8])
        assert repository.consume_webauthn_challenge("owner", account_id, "register") is None


class TestDriverDetailsTotalLoads:
    """get_driver_details' total_loads used to be len(loads) - but that list
    is capped at 50 rows for the history table, so a driver with more than
    50 loads showed a "total loads" figure stuck at 50 forever. See
    db/repository.py's get_driver_details."""

    def test_total_loads_counts_beyond_the_50_row_history_cap(self, setup_db):
        unique_mc = str(uuid.uuid4().int)[:6]
        with get_session() as session:
            company = models.Company(
                mc_number=unique_mc,
                company_name=f"Total Loads Test {unique_mc}",
                telegram_group_prefix=f"T{unique_mc[:4]}",
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
