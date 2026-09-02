"""
Test suite for Freight Pilot API endpoints.
Run: pytest tests/ -v

The session lives in an httpOnly cookie now (not a bearer token in the
response body), so each test gets its own fresh TestClient - otherwise
cookies set by one test's login would leak into the next test via the
client's persistent cookie jar. Mutating requests (POST/PATCH/DELETE made
by an already-logged-in caller) also need the CSRF header the double-submit
cookie pattern requires - see _csrf_headers().
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
import miniapp.api as api_module
from miniapp.api import app
from miniapp.auth import CSRF_COOKIE_NAME


# client and _disable_turnstile now live in conftest.py - more than one
# module drives the API, and a fixture defined in a test module is invisible
# to the others.
from tests.conftest import csrf_headers as _csrf_headers  # noqa: E402


class TestAuth:
    """Authentication endpoints test"""

    def test_register_success(self, client):
        """Test company registration"""
        response = client.post("/api/auth/register", json={
            "mc_number": "999999",
            "company_name": "Test Transport LLC",
            "email": "owner@testtransport.com",
            "password": "test12345678",
            "confirm_password": "test12345678"
        })
        assert response.status_code in [200, 400]  # 400 if already exists
        if response.status_code == 200:
            assert response.json()["company_id"]
            assert "token" not in response.json()  # session lives in an httpOnly cookie, not the body
            assert client.cookies.get("fp_session")
            assert client.cookies.get(CSRF_COOKIE_NAME)

    def test_register_password_mismatch(self, client):
        """Test registration with mismatched passwords"""
        response = client.post("/api/auth/register", json={
            "mc_number": "888888",
            "company_name": "Test Co",
            "email": "owner@testco.com",
            "password": "password123",
            "confirm_password": "different123"
        })
        assert response.status_code == 400
        assert "do not match" in response.json()["detail"].lower()

    def test_register_short_password(self, client):
        """Test registration with short password"""
        response = client.post("/api/auth/register", json={
            "mc_number": "777777",
            "company_name": "Test Co",
            "email": "owner@testco.com",
            "password": "short",
            "confirm_password": "short"
        })
        assert response.status_code == 400
        assert "8 characters" in response.json()["detail"].lower()

    def test_register_password_over_72_bytes_rejected(self, client):
        """bcrypt only hashes the first 72 bytes of a password - bcrypt>=5
        raises instead of silently truncating like older versions did, so
        this must be caught with a clear message before it ever reaches
        hash_password()."""
        long_password = "a" * 73
        response = client.post("/api/auth/register", json={
            "mc_number": "444555",
            "company_name": "Test Co",
            "email": "owner@longpasswordtest.com",
            "password": long_password,
            "confirm_password": long_password,
        })
        assert response.status_code == 400
        assert "72 bytes" in response.json()["detail"]

    def test_register_invalid_mc(self, client):
        """Test registration with non-numeric MC - rejected by request validation (422)"""
        response = client.post("/api/auth/register", json={
            "mc_number": "ABC123",
            "company_name": "Test Co",
            "email": "owner@testco.com",
            "password": "password123",
            "confirm_password": "password123"
        })
        assert response.status_code == 422
        assert "digits" in str(response.json()["detail"]).lower()

    def test_register_invalid_email(self, client):
        """Test registration with a malformed email - rejected by request validation (422)"""
        response = client.post("/api/auth/register", json={
            "mc_number": "666666",
            "company_name": "Test Co",
            "email": "not-an-email",
            "password": "password123",
            "confirm_password": "password123"
        })
        assert response.status_code == 422

    def test_register_missing_email(self, client):
        """Test registration with no email at all - rejected by request validation (422)"""
        response = client.post("/api/auth/register", json={
            "mc_number": "555555",
            "company_name": "Test Co",
            "password": "password123",
            "confirm_password": "password123"
        })
        assert response.status_code == 422

    def test_logout_clears_session(self, client):
        """Logging out must clear the cookie server-side - JS can't touch an httpOnly cookie itself."""
        client.post("/api/auth/register", json={
            "mc_number": "222222",
            "company_name": "Logout Test Co",
            "email": "owner@logouttest.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        assert client.cookies.get("fp_session")

        logout = client.post("/api/auth/logout", headers=_csrf_headers(client))
        assert logout.status_code == 200

        me = client.get("/api/me")
        assert me.status_code == 401


class TestPasswordReset:
    """/api/auth/forgot-password + /api/auth/reset-password - see
    PasswordResetToken's docstring for why this only covers owners."""

    def _register_owner(self, client, mc_number: str, email: str) -> None:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Reset Test Co {mc_number}",
            "email": email,
            "password": "originalpass123",
            "confirm_password": "originalpass123",
        })
        assert reg.status_code == 200, reg.text

    def _latest_token_for_mc(self, mc_number: str) -> str:
        from db.database import get_session
        from db import models

        with get_session() as session:
            company = session.query(models.Company).filter_by(mc_number=mc_number).first()
            row = (
                session.query(models.PasswordResetToken)
                .filter_by(account_type="owner", account_id=company.id)
                .order_by(models.PasswordResetToken.created_at.desc())
                .first()
            )
            return row.token

    def test_forgot_password_gives_same_response_for_unknown_mc(self, client):
        self._register_owner(client, "777001", "owner@resettest.com")
        client.post("/api/auth/logout", headers=_csrf_headers(client))

        known = client.post("/api/auth/forgot-password", json={"mc_number": "777001"})
        unknown = client.post("/api/auth/forgot-password", json={"mc_number": "777099"})

        assert known.status_code == 200
        assert unknown.status_code == 200
        assert known.json() == unknown.json()

    def test_reset_password_with_valid_token_changes_password(self, client):
        self._register_owner(client, "777002", "owner@resettest2.com")
        client.post("/api/auth/logout", headers=_csrf_headers(client))

        client.post("/api/auth/forgot-password", json={"mc_number": "777002"})
        token = self._latest_token_for_mc("777002")

        reset = client.post("/api/auth/reset-password", json={
            "token": token, "new_password": "brandnewpass123", "confirm_password": "brandnewpass123",
        })
        assert reset.status_code == 200, reset.text

        old_login = client.post("/api/auth/owner", json={"mc_number": "777002", "password": "originalpass123"})
        assert old_login.status_code == 401

        new_login = client.post("/api/auth/owner", json={"mc_number": "777002", "password": "brandnewpass123"})
        assert new_login.status_code == 200

    def test_reset_password_token_is_single_use(self, client):
        self._register_owner(client, "777003", "owner@resettest3.com")
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/forgot-password", json={"mc_number": "777003"})
        token = self._latest_token_for_mc("777003")

        first = client.post("/api/auth/reset-password", json={
            "token": token, "new_password": "firstnewpass123", "confirm_password": "firstnewpass123",
        })
        assert first.status_code == 200

        second = client.post("/api/auth/reset-password", json={
            "token": token, "new_password": "secondnewpass123", "confirm_password": "secondnewpass123",
        })
        assert second.status_code == 400

    def test_reset_password_rejects_unknown_token(self, client):
        response = client.post("/api/auth/reset-password", json={
            "token": "not-a-real-token", "new_password": "somepassword123", "confirm_password": "somepassword123",
        })
        assert response.status_code == 400

    def test_reset_password_rejects_mismatched_confirmation(self, client):
        self._register_owner(client, "777004", "owner@resettest4.com")
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/forgot-password", json={"mc_number": "777004"})
        token = self._latest_token_for_mc("777004")

        response = client.post("/api/auth/reset-password", json={
            "token": token, "new_password": "somepassword123", "confirm_password": "differentpassword123",
        })
        assert response.status_code == 400


class TestAccountStatus:
    """PUT/DELETE /api/me/status - the "what's happening" status shown in
    the profile menu, and its expiry handling."""

    def _register_owner(self, client, mc_number: str) -> None:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Status Test Co {mc_number}",
            "email": f"owner{mc_number}@statustest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

    def test_me_has_no_status_by_default(self, client):
        self._register_owner(client, "781111")
        response = client.get("/api/me")
        assert response.json()["status"] is None

    def test_set_status_reflects_in_me(self, client):
        self._register_owner(client, "782222")
        set_resp = client.put(
            "/api/me/status", json={"emoji": "🌴", "text": "On vacation", "expires_in_minutes": None},
            headers=_csrf_headers(client),
        )
        assert set_resp.status_code == 200, set_resp.text

        me = client.get("/api/me").json()
        assert me["status"] == {"emoji": "🌴", "text": "On vacation", "expires_at": None}

    def test_clear_status_removes_it(self, client):
        self._register_owner(client, "783333")
        client.put(
            "/api/me/status", json={"emoji": None, "text": "Busy", "expires_in_minutes": None},
            headers=_csrf_headers(client),
        )
        client.delete("/api/me/status", headers=_csrf_headers(client))

        assert client.get("/api/me").json()["status"] is None

    def test_expired_status_reads_as_none(self, client):
        self._register_owner(client, "784444")
        client.put(
            "/api/me/status", json={"emoji": None, "text": "Back in 5", "expires_in_minutes": 30},
            headers=_csrf_headers(client),
        )

        # Force it into the past directly, rather than waiting 30 minutes.
        from db.database import get_session
        from db import models

        with get_session() as session:
            company = session.query(models.Company).filter_by(mc_number="784444").first()
            row = (
                session.query(models.AccountStatus)
                .filter_by(account_type="owner", account_id=company.id)
                .first()
            )
            row.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            session.commit()

        assert client.get("/api/me").json()["status"] is None

    def test_set_status_rejects_blank_text(self, client):
        self._register_owner(client, "785555")
        response = client.put(
            "/api/me/status", json={"emoji": None, "text": "   ", "expires_in_minutes": None},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 422

    def test_dispatcher_status_is_independent_of_owner(self, client):
        self._register_owner(client, "786666")
        client.post(
            "/api/dispatchers", json={"username": "status_dispatcher", "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )
        client.put(
            "/api/me/status", json={"emoji": None, "text": "Owner status", "expires_in_minutes": None},
            headers=_csrf_headers(client),
        )

        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "status_dispatcher", "password": "dispatcherpass123"})

        assert client.get("/api/me").json()["status"] is None


class TestAccountAvatar:
    """PUT/DELETE /api/me/avatar - the profile picture shown in the profile
    menu and to teammates via GET /api/team. See AccountAvatar in
    db/models.py."""

    _FAKE_DATA_URL = "data:image/png;base64,iVBORw0KGgo="

    def _register_owner(self, client, mc_number: str) -> None:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Avatar Test Co {mc_number}",
            "email": f"owner{mc_number}@avatartest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

    def test_me_has_no_avatar_by_default(self, client):
        self._register_owner(client, "791111")
        assert client.get("/api/me").json()["avatar"] is None

    def test_set_avatar_reflects_in_me(self, client):
        self._register_owner(client, "792222")
        set_resp = client.put(
            "/api/me/avatar", json={"data_url": self._FAKE_DATA_URL}, headers=_csrf_headers(client),
        )
        assert set_resp.status_code == 200, set_resp.text
        assert client.get("/api/me").json()["avatar"] == self._FAKE_DATA_URL

    def test_clear_avatar_removes_it(self, client):
        self._register_owner(client, "793333")
        client.put("/api/me/avatar", json={"data_url": self._FAKE_DATA_URL}, headers=_csrf_headers(client))
        client.delete("/api/me/avatar", headers=_csrf_headers(client))
        assert client.get("/api/me").json()["avatar"] is None

    def test_set_avatar_rejects_non_image_data_url(self, client):
        self._register_owner(client, "794444")
        response = client.put(
            "/api/me/avatar", json={"data_url": "not-an-image"}, headers=_csrf_headers(client),
        )
        assert response.status_code == 422

    def test_set_avatar_rejects_oversized_payload(self, client):
        self._register_owner(client, "795555")
        oversized = "data:image/png;base64," + ("A" * 400_000)
        response = client.put(
            "/api/me/avatar", json={"data_url": oversized}, headers=_csrf_headers(client),
        )
        assert response.status_code == 422

    def test_dispatcher_avatar_is_independent_of_owner(self, client):
        self._register_owner(client, "796666")
        client.post(
            "/api/dispatchers", json={"username": "avatar_dispatcher", "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )
        client.put("/api/me/avatar", json={"data_url": self._FAKE_DATA_URL}, headers=_csrf_headers(client))

        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "avatar_dispatcher", "password": "dispatcherpass123"})

        assert client.get("/api/me").json()["avatar"] is None


class TestTeamRoster:
    """GET /api/team - lets an owner and their dispatchers see each other's
    display name and avatar, regardless of which one of them is logged in
    (unlike GET /api/dispatchers, which is owner-only CRUD data)."""

    _FAKE_DATA_URL = "data:image/png;base64,iVBORw0KGgo="

    def _register_owner_and_dispatcher(self, client, mc_number: str, username: str) -> None:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Team Test Co {mc_number}",
            "email": f"owner{mc_number}@teamtest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        created = client.post(
            "/api/dispatchers", json={"username": username, "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )
        assert created.status_code == 200, created.text

    def test_team_lists_owner_and_dispatchers(self, client):
        self._register_owner_and_dispatcher(client, "797777", "team_dispatcher_1")
        team = client.get("/api/team").json()
        assert {m["role"]: m["name"] for m in team} == {
            "owner": "Team Test Co 797777", "dispatcher": "team_dispatcher_1",
        }

    def test_dispatcher_sees_owners_avatar_via_team(self, client):
        self._register_owner_and_dispatcher(client, "798888", "team_dispatcher_2")
        client.put("/api/me/avatar", json={"data_url": self._FAKE_DATA_URL}, headers=_csrf_headers(client))

        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "team_dispatcher_2", "password": "dispatcherpass123"})

        team = client.get("/api/team").json()
        owner_entry = next(m for m in team if m["role"] == "owner")
        assert owner_entry["avatar"] == self._FAKE_DATA_URL

    def test_owner_sees_dispatchers_avatar_via_team(self, client):
        self._register_owner_and_dispatcher(client, "799999", "team_dispatcher_3")
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "team_dispatcher_3", "password": "dispatcherpass123"})
        client.put("/api/me/avatar", json={"data_url": self._FAKE_DATA_URL}, headers=_csrf_headers(client))

        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/owner", json={"mc_number": "799999", "password": "ownerpass123"})

        team = client.get("/api/team").json()
        dispatcher_entry = next(m for m in team if m["role"] == "dispatcher")
        assert dispatcher_entry["avatar"] == self._FAKE_DATA_URL


class TestGmailFirstRegistration:
    """Registration is Gmail-first: connect Gmail, confirm you own that
    inbox (code or link), THEN fill in company details - a Company row is
    only ever created at the final /api/auth/register call, and only if a
    verified pending_token is attached. See PendingRegistration's docstring.

    These tests create PendingRegistration rows directly rather than
    exercising the real OAuth callback, which would need a live Google API
    call - that part (services/gmail_service.exchange_code_for_refresh_token
    and get_email_address) is exercised by hand against a real account
    instead, same as the rest of this codebase's Gmail integration."""

    def _create_pending_registration(self, *, verified: bool, gmail_email: str = "owner@gmail.com") -> tuple[str, str, str]:
        """Returns (pending_token, plaintext_code, link_token)."""
        import secrets
        from datetime import timedelta
        from db.database import get_session
        from db import models
        from config import encrypt_value
        from services import twofactor_service

        pending_token = secrets.token_urlsafe(16)
        code = "123456"
        link_token = secrets.token_urlsafe(16)

        with get_session() as session:
            session.add(models.PendingRegistration(
                token=pending_token,
                gmail_email=gmail_email,
                gmail_refresh_token_encrypted=encrypt_value("fake-refresh-token"),
                verify_code_hash=twofactor_service.hash_otp_code(code),
                verify_link_token=link_token,
                email_verified_at=datetime.now(timezone.utc) if verified else None,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ))
            session.commit()
        return pending_token, code, link_token

    def test_pending_status_returns_email_and_verified_flag(self, client):
        pending_token, _code, _link = self._create_pending_registration(verified=False, gmail_email="pending@gmail.com")
        response = client.get(f"/api/auth/register/pending-status?pending_token={pending_token}")
        assert response.status_code == 200
        assert response.json() == {"gmail_email": "pending@gmail.com", "email_verified": False}

    def test_pending_status_unknown_token_404s(self, client):
        response = client.get("/api/auth/register/pending-status?pending_token=not-a-real-token")
        assert response.status_code == 404

    def test_verify_code_marks_pending_registration_verified(self, client):
        pending_token, code, _link = self._create_pending_registration(verified=False)
        response = client.post("/api/auth/register/verify-code", json={"pending_token": pending_token, "code": code})
        assert response.status_code == 200
        assert response.json() == {"verified": True}

        status = client.get(f"/api/auth/register/pending-status?pending_token={pending_token}")
        assert status.json()["email_verified"] is True

    def test_verify_code_wrong_code_rejected(self, client):
        pending_token, _code, _link = self._create_pending_registration(verified=False)
        response = client.post("/api/auth/register/verify-code", json={"pending_token": pending_token, "code": "000000"})
        assert response.status_code == 400

    def test_verify_link_marks_verified_and_redirects_with_pending_token(self, client):
        pending_token, _code, link_token = self._create_pending_registration(verified=False)
        response = client.get(f"/api/auth/register/verify-link?token={link_token}", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert f"pending_token={pending_token}" in response.headers["location"]
        assert "verified=1" in response.headers["location"]

    def test_verify_link_unknown_token_redirects_with_error(self, client):
        response = client.get("/api/auth/register/verify-link?token=not-a-real-link-token", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert "verify=error" in response.headers["location"]

    def test_register_with_verified_pending_token_attaches_gmail(self, client):
        pending_token, _code, _link = self._create_pending_registration(verified=True, gmail_email="verified@gmail.com")

        response = client.post("/api/auth/register", json={
            "mc_number": "761111",
            "company_name": "Gmail First Co",
            "email": "owner@gmailfirstco.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
            "pending_token": pending_token,
        })
        assert response.status_code == 200, response.text
        assert response.json()["gmail_connected"] is True

        # The pending registration is one-time use - gone after consumption.
        status = client.get(f"/api/auth/register/pending-status?pending_token={pending_token}")
        assert status.status_code == 404

    def test_register_with_unverified_pending_token_rejected_and_creates_no_company(self, client):
        pending_token, _code, _link = self._create_pending_registration(verified=False)

        response = client.post("/api/auth/register", json={
            "mc_number": "762222",
            "company_name": "Should Not Exist Co",
            "email": "owner@shouldnotexist.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
            "pending_token": pending_token,
        })
        assert response.status_code == 400

        # Confirm no company was created - the MC number is still free.
        second_attempt = client.post("/api/auth/register", json={
            "mc_number": "762222",
            "company_name": "Should Not Exist Co",
            "email": "owner@shouldnotexist.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert second_attempt.status_code == 200, second_attempt.text

    def test_register_with_invalid_pending_token_rejected(self, client):
        response = client.post("/api/auth/register", json={
            "mc_number": "763333",
            "company_name": "Invalid Token Co",
            "email": "owner@invalidtokenco.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
            "pending_token": "not-a-real-pending-token",
        })
        assert response.status_code == 400

    def test_register_without_pending_token_still_works(self, client):
        """Backward-compat: pending_token is optional, so existing
        integrations that never touch the Gmail-first flow are unaffected."""
        response = client.post("/api/auth/register", json={
            "mc_number": "764444",
            "company_name": "No Gmail Co",
            "email": "owner@nogmailco.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert response.status_code == 200, response.text
        assert response.json()["gmail_connected"] is False


class TestRegisterMcPrefixCollision:
    """Regression test: telegram_group_prefix used to be derived from just the
    first 4 digits of the MC number, so two companies whose MC numbers shared
    that prefix (e.g. "555000" and "555001") collided on the column's UNIQUE
    constraint - the second registration raised an unhandled IntegrityError
    that the endpoint's broad except turned into an opaque 500."""

    def test_companies_with_colliding_mc_prefix_both_register(self, client):
        first = client.post("/api/auth/register", json={
            "mc_number": "555000",
            "company_name": "Prefix Collision Co A",
            "email": "ownerA@prefixcollision.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        assert first.status_code == 200, first.text

        second_client = TestClient(app)
        second = second_client.post("/api/auth/register", json={
            "mc_number": "555001",
            "company_name": "Prefix Collision Co B",
            "email": "ownerB@prefixcollision.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        assert second.status_code == 200, second.text
        assert second.json()["company_id"] != first.json()["company_id"]


class TestCsrfProtection:
    """State-changing requests must present a matching X-CSRF-Token header,
    even with a fully valid session cookie - otherwise a cross-site request
    riding the ambient session cookie could perform actions on the user's
    behalf."""

    def test_mutating_request_without_csrf_header_rejected(self, client):
        client.post("/api/auth/register", json={
            "mc_number": "112233",
            "company_name": "CSRF Test Co",
            "email": "owner@csrftest.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        # Valid session cookie present, but no X-CSRF-Token header at all.
        response = client.post("/api/dispatchers", json={"username": "nope", "password": "password123"})
        assert response.status_code == 403

    def test_mutating_request_with_wrong_csrf_token_rejected(self, client):
        client.post("/api/auth/register", json={
            "mc_number": "223344",
            "company_name": "CSRF Test Co 2",
            "email": "owner2@csrftest.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        response = client.post(
            "/api/dispatchers",
            json={"username": "nope", "password": "password123"},
            headers={"X-CSRF-Token": "not-the-real-token"},
        )
        assert response.status_code == 403

    def test_mutating_request_with_correct_csrf_token_allowed(self, client):
        client.post("/api/auth/register", json={
            "mc_number": "334455",
            "company_name": "CSRF Test Co 3",
            "email": "owner3@csrftest.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        response = client.post(
            "/api/dispatchers",
            json={"username": "csrf_ok_dispatcher", "password": "password123"},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 200


class TestTurnstile:
    """Turnstile is off by default (no TURNSTILE_SECRET_KEY in the test
    env) so every other test's register/login calls work with no token -
    these tests turn it on temporarily to prove the enforcement path
    itself is wired correctly, without making a real network call to
    Cloudflare."""

    def test_register_blocked_without_token_when_turnstile_configured(self, client, monkeypatch):
        monkeypatch.setattr("miniapp.api.TURNSTILE_SECRET_KEY", "fake-secret-for-test")
        response = client.post("/api/auth/register", json={
            "mc_number": "800000",
            "company_name": "Turnstile Test Co",
            "email": "owner@turnstiletest.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        assert response.status_code == 400
        assert "bot verification" in response.json()["detail"].lower()

    def test_register_allowed_with_valid_token_when_turnstile_configured(self, client, monkeypatch):
        monkeypatch.setattr("miniapp.api.TURNSTILE_SECRET_KEY", "fake-secret-for-test")

        class _FakeResponse:
            def json(self):
                return {"success": True}

        monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse())

        response = client.post("/api/auth/register", json={
            "mc_number": "800002",
            "company_name": "Turnstile Test Co 2",
            "email": "owner2@turnstiletest.com",
            "password": "password123",
            "confirm_password": "password123",
            "turnstile_token": "a-real-looking-token",
        })
        assert response.status_code == 200, response.text


class TestRateLimiting:
    """Login/register/OTP endpoints are rate-limited per IP to blunt brute
    force and account-creation abuse - see the @limiter.limit(...)
    decorators in miniapp/api.py."""

    def test_owner_login_rate_limited_after_threshold(self, client):
        # login_owner is limited to 5/minute; wrong credentials still count
        # against the limit since the check happens before the 401.
        responses = [
            client.post("/api/auth/owner", json={"mc_number": "000000", "password": "wrong"})
            for _ in range(6)
        ]
        statuses = [r.status_code for r in responses]
        assert statuses[:5] == [401, 401, 401, 401, 401]
        assert statuses[5] == 429


class TestDispatcherAuth:
    """Regression test: dispatcher logins used to omit dispatcher_id from the
    JWT, which crashed every 2FA endpoint for a dispatcher account (they all
    resolve "self" via user["dispatcher_id"])."""

    def _register_owner_and_dispatcher(self, client, mc_number: str, dispatcher_username: str):
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": "Dispatcher Test Co",
            "email": "owner@dispatchertest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

        created = client.post(
            "/api/dispatchers",
            json={"username": dispatcher_username, "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )
        assert created.status_code == 200, created.text

    def test_dispatcher_login_includes_dispatcher_id(self, client):
        self._register_owner_and_dispatcher(client, "444444", "dispatcher_regress_1")
        client.post("/api/auth/logout", headers=_csrf_headers(client))

        login = client.post("/api/auth/dispatcher", json={
            "username": "dispatcher_regress_1",
            "password": "dispatcherpass123",
        })
        assert login.status_code == 200, login.text
        body = login.json()
        assert body.get("dispatcher_id"), "login response must include dispatcher_id"

    def test_dispatcher_can_load_2fa_status_without_500(self, client):
        self._register_owner_and_dispatcher(client, "333333", "dispatcher_regress_2")
        client.post("/api/auth/logout", headers=_csrf_headers(client))

        login = client.post("/api/auth/dispatcher", json={
            "username": "dispatcher_regress_2",
            "password": "dispatcherpass123",
        })
        assert login.status_code == 200, login.text

        status = client.get("/api/2fa/status")
        assert status.status_code == 200, status.text

    def test_add_dispatcher_rejects_password_over_72_bytes(self, client):
        reg = client.post("/api/auth/register", json={
            "mc_number": "445566",
            "company_name": "Long Dispatcher Password Co",
            "email": "owner@longdispatcherpass.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

        response = client.post(
            "/api/dispatchers",
            json={"username": "long_password_dispatcher", "password": "a" * 73},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 400
        assert "72 bytes" in response.json()["detail"]


class TestDispatcherAccountManagement:
    """PATCH/DELETE /api/dispatchers/{id} - lets an owner change a
    dispatcher's username/password or remove the login entirely."""

    def _register_owner_with_dispatcher(self, client, mc_number: str, username: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Dispatcher Mgmt Co {mc_number}",
            "email": f"owner{mc_number}@dispatchermgmt.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

        created = client.post(
            "/api/dispatchers", json={"username": username, "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )
        assert created.status_code == 200, created.text
        return created.json()["id"]

    def test_owner_can_update_dispatcher_username_and_password(self, client):
        dispatcher_id = self._register_owner_with_dispatcher(client, "751111", "mgmt_dispatcher_1")

        update = client.patch(
            f"/api/dispatchers/{dispatcher_id}",
            json={"username": "renamed_dispatcher_1", "password": "newpassword123"},
            headers=_csrf_headers(client),
        )
        assert update.status_code == 200, update.text

        old_login = client.post("/api/auth/dispatcher", json={"username": "mgmt_dispatcher_1", "password": "dispatcherpass123"})
        assert old_login.status_code == 401

        new_login = client.post("/api/auth/dispatcher", json={"username": "renamed_dispatcher_1", "password": "newpassword123"})
        assert new_login.status_code == 200

    def test_update_rejects_username_already_taken(self, client):
        dispatcher_id = self._register_owner_with_dispatcher(client, "752222", "mgmt_dispatcher_2")
        client.post(
            "/api/dispatchers", json={"username": "mgmt_dispatcher_2b", "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )

        response = client.patch(
            f"/api/dispatchers/{dispatcher_id}", json={"username": "mgmt_dispatcher_2b"},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 400

    def test_owner_can_delete_a_dispatcher(self, client):
        dispatcher_id = self._register_owner_with_dispatcher(client, "753333", "mgmt_dispatcher_3")

        delete = client.delete(f"/api/dispatchers/{dispatcher_id}", headers=_csrf_headers(client))
        assert delete.status_code == 200, delete.text

        login = client.post("/api/auth/dispatcher", json={"username": "mgmt_dispatcher_3", "password": "dispatcherpass123"})
        assert login.status_code == 401

    def test_cannot_manage_another_companys_dispatcher(self, client):
        dispatcher_id = self._register_owner_with_dispatcher(client, "754444", "mgmt_dispatcher_4")

        other_client = TestClient(app)
        other_client.post("/api/auth/register", json={
            "mc_number": "754445",
            "company_name": "Other Co",
            "email": "owner@othermgmtco.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })

        response = other_client.patch(
            f"/api/dispatchers/{dispatcher_id}", json={"username": "hijacked"},
            headers=_csrf_headers(other_client),
        )
        assert response.status_code == 404


class TestTenantIsolation:
    """SQLite has no row-level security, so tenant isolation is enforced
    entirely in miniapp/api.py. These tests lock in that every driver-scoped
    endpoint rejects access from a different company's owner, even with a
    valid, correctly-signed session cookie."""

    @pytest.fixture(autouse=True)
    def _reset_limiter(self):
        # This class builds its own TestClient pairs (it needs two logged-in
        # clients at once, which the shared `client` fixture doesn't support)
        # instead of using the `client` fixture - so it misses that fixture's
        # own app.state.limiter.reset(), and accumulates rate-limit state
        # from every other test that ran first in the same session.
        app.state.limiter.reset()

    def _register_owner(self, client, mc_number: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Tenant Test Co {mc_number}",
            "email": f"owner{mc_number}@tenanttest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        return reg.json()["company_id"]

    def _create_driver(self, company_id: int) -> int:
        from db.database import get_session
        from db import models

        with get_session() as session:
            driver = models.Driver(company_id=company_id, driver_bot_id=f"D{company_id}", full_name="Test Driver")
            session.add(driver)
            session.commit()
            session.refresh(driver)
            return driver.id

    def test_cross_tenant_driver_details_forbidden(self):
        client_a = TestClient(app)
        client_b = TestClient(app)
        company_a_id = self._register_owner(client_a, "211111")
        self._register_owner(client_b, "311111")
        driver_a_id = self._create_driver(company_a_id)

        response = client_b.get(f"/api/drivers/{driver_a_id}")
        assert response.status_code == 403

    def test_cross_tenant_subscription_toggle_forbidden(self):
        client_a = TestClient(app)
        client_b = TestClient(app)
        company_a_id = self._register_owner(client_a, "411111")
        self._register_owner(client_b, "511111")
        driver_a_id = self._create_driver(company_a_id)

        response = client_b.patch(
            f"/api/drivers/{driver_a_id}/subscription",
            json={"active": False},
            headers=_csrf_headers(client_b),
        )
        assert response.status_code == 403

    def test_own_tenant_driver_details_allowed(self, client):
        company_id = self._register_owner(client, "611111")
        driver_id = self._create_driver(company_id)

        response = client.get(f"/api/drivers/{driver_id}")
        assert response.status_code == 200


class TestDriverActivationBillingGuard:
    """PATCH /api/drivers/{id}/subscription's cap check used to key off
    subscription_tier alone - a company stuck in "past_due" (a failed
    renewal Stripe is still retrying, which can take weeks before it
    actually cancels) kept its paid-tier limit the whole time, since tier
    isn't downgraded until the subscription is actually deleted. It must
    fall back to the free-tier cap for any NEW activation while a
    subscription isn't in good standing - see update_subscription in
    miniapp/api.py."""

    def _register_owner(self, client, mc_number: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Billing Guard Co {mc_number}",
            "email": f"owner{mc_number}@billingguard.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        return reg.json()["company_id"]

    def _create_driver(self, company_id: int) -> int:
        from db.database import get_session
        from db import models

        with get_session() as session:
            # subscription_active defaults to True - explicitly OFF here so
            # the PATCH .../subscription {"active": true} calls below
            # actually exercise the "turning on a currently-inactive
            # driver" cap-check path, not a no-op on an already-active one.
            driver = models.Driver(
                company_id=company_id, driver_bot_id=f"D{company_id}-{id(object())}",
                full_name="Test Driver", subscription_active=False,
            )
            session.add(driver)
            session.commit()
            session.refresh(driver)
            return driver.id

    def _set_billing_state(self, company_id: int, tier: str, status: str) -> None:
        from db.database import get_session
        from db import models

        with get_session() as session:
            company = session.get(models.Company, company_id)
            company.subscription_tier = tier
            company.subscription_status = status
            session.commit()

    def test_past_due_subscription_caps_new_activations_at_free_tier(self, client):
        company_id = self._register_owner(client, "721111")
        driver_1_id = self._create_driver(company_id)
        driver_2_id = self._create_driver(company_id)
        self._set_billing_state(company_id, tier="pro", status="past_due")

        # First activation stays within the free-tier fallback limit (1) -
        # must still succeed even while the subscription isn't in good
        # standing.
        first = client.patch(
            f"/api/drivers/{driver_1_id}/subscription", json={"active": True}, headers=_csrf_headers(client),
        )
        assert first.status_code == 200, first.text

        # A second activation would be fine under the "pro" tier's real
        # limit (5), but must be blocked here since the subscription is
        # past_due, not active/trialing.
        second = client.patch(
            f"/api/drivers/{driver_2_id}/subscription", json={"active": True}, headers=_csrf_headers(client),
        )
        assert second.status_code == 402
        assert "up to 1" in second.json()["detail"]

    def test_active_pro_subscription_allows_up_to_its_real_limit(self, client):
        company_id = self._register_owner(client, "722222")
        driver_1_id = self._create_driver(company_id)
        driver_2_id = self._create_driver(company_id)
        self._set_billing_state(company_id, tier="pro", status="active")

        for driver_id in (driver_1_id, driver_2_id):
            response = client.patch(
                f"/api/drivers/{driver_id}/subscription", json={"active": True}, headers=_csrf_headers(client),
            )
            assert response.status_code == 200, response.text


class TestDispatcherSubscriptionToggle:
    """Both roles can pause a driver, but activating one is owner-only -
    it commits the company to another billable driver. See
    update_subscription in miniapp/api.py."""

    def _register_owner_and_dispatcher(self, client, mc_number: str, username: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Dispatcher Toggle Co {mc_number}",
            "email": f"owner{mc_number}@dispatchertoggle.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        company_id = reg.json()["company_id"]

        created = client.post(
            "/api/dispatchers", json={"username": username, "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )
        assert created.status_code == 200, created.text
        return company_id

    def _create_active_driver(self, company_id: int) -> int:
        from db.database import get_session
        from db import models

        with get_session() as session:
            driver = models.Driver(
                company_id=company_id, driver_bot_id=f"D{company_id}", full_name="Test Driver",
                subscription_active=True,
            )
            session.add(driver)
            session.commit()
            session.refresh(driver)
            return driver.id

    def test_dispatcher_can_deactivate_a_driver(self, client):
        company_id = self._register_owner_and_dispatcher(client, "731111", "toggle_dispatcher_1")
        driver_id = self._create_active_driver(company_id)

        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "toggle_dispatcher_1", "password": "dispatcherpass123"})

        response = client.patch(
            f"/api/drivers/{driver_id}/subscription", json={"active": False}, headers=_csrf_headers(client),
        )
        assert response.status_code == 200, response.text

    def test_dispatcher_cannot_activate_a_driver(self, client):
        company_id = self._register_owner_and_dispatcher(client, "732222", "toggle_dispatcher_2")
        driver_id = self._create_active_driver(company_id)

        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "toggle_dispatcher_2", "password": "dispatcherpass123"})
        client.patch(f"/api/drivers/{driver_id}/subscription", json={"active": False}, headers=_csrf_headers(client))

        response = client.patch(
            f"/api/drivers/{driver_id}/subscription", json={"active": True}, headers=_csrf_headers(client),
        )
        assert response.status_code == 403


class TestFleetStatus:
    """The dashboard's fleet view - one row per truck currently on a load,
    with the rows needing attention sorted to the top. See get_fleet_status
    in db/repository.py."""

    def _register_owner(self, client, mc_number: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Fleet Status Co {mc_number}",
            "email": f"owner{mc_number}@fleetstatus.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        return reg.json()["company_id"]

    def _add_load(self, company_id: int, driver_name: str, **load_fields) -> None:
        from db.database import get_session
        from db import models

        with get_session() as session:
            driver = models.Driver(
                company_id=company_id, driver_bot_id=f"D{driver_name}", full_name=driver_name,
                subscription_active=True,
            )
            session.add(driver)
            session.commit()
            session.refresh(driver)

            session.add(models.Load(
                company_id=company_id, driver_id=driver.id, **load_fields,
            ))
            session.commit()

    def test_open_loads_appear_and_finished_ones_do_not(self, client):
        company_id = self._register_owner(client, "870101")
        self._add_load(company_id, "Running", load_id="L-OPEN", status="loaded")
        self._add_load(company_id, "Finished", load_id="L-DONE", status="pod_sent")

        fleet = client.get("/api/dashboard").json()["fleet"]
        assert [row["load_id"] for row in fleet] == ["L-OPEN"]

    def test_driver_with_no_load_is_omitted(self, client):
        company_id = self._register_owner(client, "870202")
        from db.database import get_session
        from db import models

        with get_session() as session:
            session.add(models.Driver(
                company_id=company_id, driver_bot_id="DIDLE", full_name="Idle", subscription_active=True,
            ))
            session.commit()

        assert client.get("/api/dashboard").json()["fleet"] == []

    def test_detention_is_flagged_and_sorted_first(self, client):
        company_id = self._register_owner(client, "870303")
        # Added in the order that would sort WRONG if attention were ignored:
        # "dispatched" is the earliest stage and would otherwise lead.
        self._add_load(company_id, "Quiet", load_id="L-QUIET", status="dispatched")
        self._add_load(
            company_id, "Waiting", load_id="L-DETAINED", status="loaded",
            detention_requested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        fleet = client.get("/api/dashboard").json()["fleet"]
        assert fleet[0]["load_id"] == "L-DETAINED"
        assert fleet[0]["attention"] == ["detention"]
        assert fleet[1]["attention"] == []

    def test_load_past_its_delivery_date_is_flagged_overdue(self, client):
        company_id = self._register_owner(client, "870404")
        self._add_load(company_id, "Late", load_id="L-LATE", status="loaded", del_date="01/02/2020")

        fleet = client.get("/api/dashboard").json()["fleet"]
        assert fleet[0]["attention"] == ["overdue"]

    def test_unparseable_delivery_date_is_not_flagged(self, client):
        # del_date is free text straight off the rate confirmation - a broker
        # writing "ASAP" must not be read as an overdue load.
        company_id = self._register_owner(client, "870505")
        self._add_load(company_id, "Vague", load_id="L-VAGUE", status="loaded", del_date="ASAP")

        fleet = client.get("/api/dashboard").json()["fleet"]
        assert fleet[0]["attention"] == []

    def test_future_delivery_date_is_not_flagged(self, client):
        company_id = self._register_owner(client, "870606")
        self._add_load(company_id, "OnTime", load_id="L-FUTURE", status="loaded", del_date="12/31/2099")

        fleet = client.get("/api/dashboard").json()["fleet"]
        assert fleet[0]["attention"] == []

    def test_calm_rows_sort_by_earliest_stage(self, client):
        company_id = self._register_owner(client, "870707")
        self._add_load(company_id, "AtBol", load_id="L-BOL", status="bol_ok")
        self._add_load(company_id, "AtDispatch", load_id="L-DISPATCHED", status="dispatched")

        fleet = client.get("/api/dashboard").json()["fleet"]
        assert [row["load_id"] for row in fleet] == ["L-DISPATCHED", "L-BOL"]

    def test_fleet_is_scoped_to_the_callers_company(self, client):
        other_company = self._register_owner(client, "870808")
        self._add_load(other_company, "Theirs", load_id="L-THEIRS", status="loaded")
        client.post("/api/auth/logout", headers=_csrf_headers(client))

        self._register_owner(client, "870909")
        assert client.get("/api/dashboard").json()["fleet"] == []


class TestGmailReconnectWarning:
    """A Gmail connection whose refresh token Google has stopped accepting
    is reported so the dashboard can warn about it - the bot silently stops
    finding rate confirmations otherwise. See gmail_service's
    _tracking_token_state."""

    def _register_owner(self, client, mc_number: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Gmail Warn Co {mc_number}",
            "email": f"owner{mc_number}@gmailwarn.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        return reg.json()["company_id"]

    def test_not_flagged_when_no_gmail_is_connected(self, client):
        self._register_owner(client, "766100")
        assert client.get("/api/settings").json()["gmail_needs_reconnect"] is False

    def test_not_flagged_while_the_token_still_works(self, client):
        from db.repository import save_company_credential

        company_id = self._register_owner(client, "766101")
        save_company_credential(company_id, "gmail_refresh_token", "a-working-token")
        assert client.get("/api/settings").json()["gmail_needs_reconnect"] is False

    def test_flagged_after_a_refresh_failure(self, client):
        from db.repository import save_company_credential
        from services import gmail_service

        company_id = self._register_owner(client, "766102")
        save_company_credential(company_id, "gmail_refresh_token", "a-dead-token")
        gmail_service.mark_token_invalid(company_id)

        assert client.get("/api/settings").json()["gmail_needs_reconnect"] is True
        assert client.get("/api/dashboard").json()["gmail_needs_reconnect"] is True

    def test_a_refresh_error_marks_it_and_other_errors_do_not(self, client):
        """The distinction that matters: only an auth failure means
        "reconnect", a quota or transient API error must not."""
        from google.auth.exceptions import RefreshError
        from services import gmail_service

        company_id = self._register_owner(client, "766103")

        def _boom(exc):
            def _call():
                raise exc
            return _call

        with pytest.raises(RefreshError):
            gmail_service._tracking_token_state(company_id, _boom(RefreshError("expired")))
        assert gmail_service.token_invalid_since(company_id) is not None

        gmail_service.clear_token_invalid(company_id)
        with pytest.raises(RuntimeError):
            gmail_service._tracking_token_state(company_id, _boom(RuntimeError("quota exceeded")))
        assert gmail_service.token_invalid_since(company_id) is None

    def test_a_later_success_clears_the_warning(self, client):
        from db.repository import save_company_credential
        from services import gmail_service

        company_id = self._register_owner(client, "766104")
        save_company_credential(company_id, "gmail_refresh_token", "token")
        gmail_service.mark_token_invalid(company_id)
        assert client.get("/api/settings").json()["gmail_needs_reconnect"] is True

        gmail_service._tracking_token_state(company_id, lambda: "ok")
        assert client.get("/api/settings").json()["gmail_needs_reconnect"] is False

    def test_disconnecting_clears_the_warning(self, client):
        from db.repository import save_company_credential
        from services import gmail_service

        company_id = self._register_owner(client, "766105")
        save_company_credential(company_id, "gmail_refresh_token", "token")
        gmail_service.mark_token_invalid(company_id)

        client.delete("/api/settings/gmail", headers=_csrf_headers(client))
        assert gmail_service.token_invalid_since(company_id) is None


class TestFleetAssets:
    """Trucks and trailers - the fleet's own assets. Both roles manage them,
    since swapping a trailer or moving a driver between trucks is routine
    dispatch work. See models.Truck for why the truck, not the driver, is
    the unit the board is organised around."""

    def _register_owner(self, client, mc_number: str) -> None:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Fleet Co {mc_number}",
            "email": f"owner{mc_number}@fleettest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

    def _as_dispatcher(self, client, username: str) -> None:
        created = client.post(
            "/api/dispatchers", json={"username": username, "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )
        assert created.status_code == 200, created.text
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": username, "password": "dispatcherpass123"})

    def test_truck_and_trailer_roundtrip(self, client):
        self._register_owner(client, "766000")
        truck = client.post("/api/trucks", json={"unit_number": "3001"}, headers=_csrf_headers(client))
        assert truck.status_code == 200, truck.text
        trailer = client.post("/api/trailers", json={"unit_number": "373783"}, headers=_csrf_headers(client))
        assert trailer.status_code == 200, trailer.text

        listed = client.get("/api/trucks").json()
        assert [t["unit_number"] for t in listed] == ["3001"]
        assert listed[0]["trailer"] is None and listed[0]["driver"] is None

    def test_duplicate_unit_number_is_rejected(self, client):
        self._register_owner(client, "766001")
        client.post("/api/trucks", json={"unit_number": "4001"}, headers=_csrf_headers(client))
        again = client.post("/api/trucks", json={"unit_number": "4001"}, headers=_csrf_headers(client))
        assert again.status_code == 400

    def test_assigning_driver_and_trailer_shows_on_the_truck(self, client):
        self._register_owner(client, "766002")
        truck = client.post("/api/trucks", json={"unit_number": "5001"}, headers=_csrf_headers(client)).json()
        trailer = client.post("/api/trailers", json={"unit_number": "9001"}, headers=_csrf_headers(client)).json()
        driver = client.post("/api/drivers", json={"full_name": "Rustam"}, headers=_csrf_headers(client)).json()

        assigned = client.patch(
            f"/api/trucks/{truck['id']}",
            json={"driver_id": driver["id"], "trailer_id": trailer["id"]},
            headers=_csrf_headers(client),
        )
        assert assigned.status_code == 200, assigned.text

        row = client.get("/api/trucks").json()[0]
        assert row["trailer"]["unit_number"] == "9001"
        assert row["driver"]["full_name"] == "Rustam"

    def test_null_unhooks_but_omitted_field_is_left_alone(self, client):
        self._register_owner(client, "766003")
        truck = client.post("/api/trucks", json={"unit_number": "5002"}, headers=_csrf_headers(client)).json()
        trailer = client.post("/api/trailers", json={"unit_number": "9002"}, headers=_csrf_headers(client)).json()
        driver = client.post("/api/drivers", json={"full_name": "Jasur"}, headers=_csrf_headers(client)).json()
        client.patch(
            f"/api/trucks/{truck['id']}",
            json={"driver_id": driver["id"], "trailer_id": trailer["id"]},
            headers=_csrf_headers(client),
        )

        # Explicit null drops the trailer; driver_id isn't sent, so it stays.
        client.patch(
            f"/api/trucks/{truck['id']}", json={"trailer_id": None}, headers=_csrf_headers(client),
        )
        row = client.get("/api/trucks").json()[0]
        assert row["trailer"] is None
        assert row["driver"]["full_name"] == "Jasur"

    def test_dispatcher_can_manage_the_fleet(self, client):
        self._register_owner(client, "766004")
        self._as_dispatcher(client, "fleet_dispatcher")

        truck = client.post("/api/trucks", json={"unit_number": "6001"}, headers=_csrf_headers(client))
        assert truck.status_code == 200, truck.text
        trailer = client.post("/api/trailers", json={"unit_number": "8001"}, headers=_csrf_headers(client))
        assert trailer.status_code == 200, trailer.text
        assert client.delete(
            f"/api/trailers/{trailer.json()['id']}", headers=_csrf_headers(client)
        ).status_code == 200

    def test_deleting_a_truck_frees_its_driver(self, client):
        self._register_owner(client, "766005")
        truck = client.post("/api/trucks", json={"unit_number": "7001"}, headers=_csrf_headers(client)).json()
        driver = client.post("/api/drivers", json={"full_name": "Sardor"}, headers=_csrf_headers(client)).json()
        client.patch(
            f"/api/trucks/{truck['id']}", json={"driver_id": driver["id"]}, headers=_csrf_headers(client),
        )

        assert client.delete(f"/api/trucks/{truck['id']}", headers=_csrf_headers(client)).status_code == 200
        # The driver must survive - only the truck was deleted.
        detail = client.get(f"/api/drivers/{driver['id']}").json()
        assert detail["truck"] is None

    def test_driver_with_loads_cannot_be_deleted(self, client):
        """Loads carry the company's gross figures; cascading them away on a
        driver delete would silently rewrite past weeks."""
        self._register_owner(client, "766006")
        driver = client.post("/api/drivers", json={"full_name": "Otabek"}, headers=_csrf_headers(client)).json()

        from db.database import get_session
        from db import models

        with get_session() as session:
            company = session.query(models.Company).filter_by(mc_number="766006").first()
            session.add(models.Load(
                company_id=company.id, driver_id=driver["id"], load_id="L-766006", status="dispatched",
            ))
            session.commit()

        refused = client.delete(f"/api/drivers/{driver['id']}", headers=_csrf_headers(client))
        assert refused.status_code == 409
        assert "deactivate" in refused.json()["detail"].lower()

    def test_driver_without_loads_can_be_deleted(self, client):
        self._register_owner(client, "766007")
        driver = client.post("/api/drivers", json={"full_name": "Bobur"}, headers=_csrf_headers(client)).json()
        assert client.delete(f"/api/drivers/{driver['id']}", headers=_csrf_headers(client)).status_code == 200
        assert client.get("/api/drivers").json() == []

    def test_fleet_is_scoped_to_the_company(self, client):
        self._register_owner(client, "766008")
        client.post("/api/trucks", json={"unit_number": "TENANT-A"}, headers=_csrf_headers(client))
        client.post("/api/auth/logout", headers=_csrf_headers(client))

        self._register_owner(client, "766009")
        assert client.get("/api/trucks").json() == []


class TestGoogleSignIn:
    """"Continue with Google" - /api/auth/google/start and its callback.
    Google itself is stubbed out; what's covered here is the account
    matching and the failure paths, which is where the security-relevant
    decisions actually live."""

    def _register(self, client, mc_number: str, email: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Google Signin Co {mc_number}",
            "email": email,
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        return reg.json()["company_id"]

    def _state(self) -> str:
        from miniapp.auth import create_token
        return create_token({"purpose": "google_login"})

    def test_start_returns_a_consent_url(self, client, monkeypatch):
        monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "fake-client-id")
        monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "fake-secret")
        monkeypatch.setattr(
            "services.google_identity_service.build_authorization_url",
            lambda redirect_uri, state, login_hint=None: (
                f"https://accounts.google.com/o/oauth2/auth?state={state}"
                + (f"&login_hint={login_hint}" if login_hint else "")
            ),
        )
        response = client.get("/api/auth/google/start")
        assert response.status_code == 200, response.text
        assert response.json()["auth_url"].startswith("https://accounts.google.com/")
        # Nothing signed in from this browser yet, so nothing to suggest.
        assert response.json()["hinted_account"] is None

    def test_start_hints_the_account_this_browser_last_used(self, client, monkeypatch):
        """Someone who signed out recently should land on their own account,
        not on Google's "choose an account" list."""
        from miniapp.auth import LAST_ACCOUNT_COOKIE_NAME

        monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "fake-client-id")
        monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "fake-secret")
        monkeypatch.setattr(
            "services.google_identity_service.build_authorization_url",
            lambda redirect_uri, state, login_hint=None: (
                f"https://accounts.google.com/o/oauth2/auth?state={state}"
                + (f"&login_hint={login_hint}" if login_hint else "")
            ),
        )
        client.cookies.set(LAST_ACCOUNT_COOKIE_NAME, "dave@example.com")

        body = client.get("/api/auth/google/start").json()
        assert body["hinted_account"] == "dave@example.com"
        assert "login_hint=dave@example.com" in body["auth_url"]

    def test_switching_account_drops_the_hint_and_forgets_it(self, client, monkeypatch):
        """A suggestion nobody can get out of is not a convenience."""
        from miniapp.auth import LAST_ACCOUNT_COOKIE_NAME

        monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "fake-client-id")
        monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "fake-secret")
        monkeypatch.setattr(
            "services.google_identity_service.build_authorization_url",
            lambda redirect_uri, state, login_hint=None: (
                f"https://accounts.google.com/o/oauth2/auth?state={state}"
                + (f"&login_hint={login_hint}" if login_hint else "")
            ),
        )
        client.cookies.set(LAST_ACCOUNT_COOKIE_NAME, "dave@example.com")

        response = client.get("/api/auth/google/start?switch_account=true")
        body = response.json()
        assert body["hinted_account"] is None
        assert "login_hint" not in body["auth_url"]
        # Asserted on the header rather than the jar: the test client sets
        # its seeded cookie with no domain, so an expiry for this host does
        # not match it there even though a real browser drops it.
        expiry = [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]
        assert any(LAST_ACCOUNT_COOKIE_NAME in v and "Max-Age=0" in v for v in expiry), expiry

    def test_start_is_unavailable_when_google_is_not_configured(self, client, monkeypatch):
        monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", None)
        assert client.get("/api/auth/google/start").status_code == 503

    def test_callback_signs_in_the_matching_owner(self, client, monkeypatch):
        self._register(client, "765000", "gsignin1@example.com")
        monkeypatch.setattr(
            "services.google_identity_service.exchange_code_for_email",
            lambda code, redirect_uri: "gsignin1@example.com",
        )

        response = client.get(
            f"/api/auth/google/callback?code=x&state={self._state()}", follow_redirects=False,
        )
        assert response.status_code in (302, 307), response.text
        assert "/dashboard" in response.headers["location"]
        # The session cookie must survive onto the redirect, or the browser
        # arrives at /dashboard still logged out.
        assert client.get("/api/me").status_code == 200

    def test_callback_rejects_an_unknown_address(self, client, monkeypatch):
        monkeypatch.setattr(
            "services.google_identity_service.exchange_code_for_email",
            lambda code, redirect_uri: "nobody-here@example.com",
        )
        response = client.get(
            f"/api/auth/google/callback?code=x&state={self._state()}", follow_redirects=False,
        )
        assert "google=no_account" in response.headers["location"]
        assert client.get("/api/me").status_code == 401

    def test_callback_refuses_a_forged_state(self, client, monkeypatch):
        monkeypatch.setattr(
            "services.google_identity_service.exchange_code_for_email",
            lambda code, redirect_uri: "gsignin1@example.com",
        )
        response = client.get(
            "/api/auth/google/callback?code=x&state=not-a-real-token", follow_redirects=False,
        )
        assert "google=error" in response.headers["location"]
        assert client.get("/api/me").status_code == 401

    def test_callback_refuses_when_the_address_maps_to_two_accounts(self, client, monkeypatch):
        self._register(client, "765001", "shared@example.com")
        self._register(client, "765002", "shared@example.com")
        monkeypatch.setattr(
            "services.google_identity_service.exchange_code_for_email",
            lambda code, redirect_uri: "shared@example.com",
        )
        response = client.get(
            f"/api/auth/google/callback?code=x&state={self._state()}", follow_redirects=False,
        )
        assert "google=ambiguous" in response.headers["location"]
        assert client.get("/api/me").status_code == 401

    def test_matching_is_case_insensitive(self, client, monkeypatch):
        self._register(client, "765003", "MixedCase@Example.com")
        monkeypatch.setattr(
            "services.google_identity_service.exchange_code_for_email",
            lambda code, redirect_uri: "mixedcase@example.com",
        )
        response = client.get(
            f"/api/auth/google/callback?code=x&state={self._state()}", follow_redirects=False,
        )
        assert "/dashboard" in response.headers["location"]


class TestDispatcherBillingAccess:
    """Billing/subscription management isn't owner-only: in many companies
    the dispatcher is the one actually paying, so they can view the plan
    and reach checkout/portal too. See the billing endpoints in
    miniapp/api.py, all switched from require_owner to get_current_user."""

    def _register_owner_and_dispatcher(self, client, mc_number: str, username: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Dispatcher Billing Co {mc_number}",
            "email": f"owner{mc_number}@dispatcherbilling.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        company_id = reg.json()["company_id"]

        created = client.post(
            "/api/dispatchers", json={"username": username, "password": "dispatcherpass123"},
            headers=_csrf_headers(client),
        )
        assert created.status_code == 200, created.text
        return company_id

    def test_dispatcher_can_view_billing(self, client):
        self._register_owner_and_dispatcher(client, "741111", "billing_dispatcher_1")
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "billing_dispatcher_1", "password": "dispatcherpass123"})

        response = client.get("/api/billing")
        assert response.status_code == 200, response.text
        assert response.json()["tier"] == "free"

    def test_dispatcher_can_reach_checkout(self, client, monkeypatch):
        # Mocks Stripe out entirely (this environment happens to have a real
        # test-mode STRIPE_SECRET_KEY configured, which would otherwise make
        # this a live network call) - what matters here is only that the
        # dispatcher reaches stripe_service at all instead of being blocked
        # by require_owner, not what Stripe itself does with the request.
        from services import stripe_service

        monkeypatch.setattr(
            stripe_service, "create_checkout_session",
            lambda company_id, tier, interval: "https://checkout.stripe.com/fake",
        )

        self._register_owner_and_dispatcher(client, "742222", "billing_dispatcher_2")
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "billing_dispatcher_2", "password": "dispatcherpass123"})

        response = client.post(
            "/api/billing/checkout", json={"tier": "pro", "interval": "month"}, headers=_csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        assert response.json()["url"] == "https://checkout.stripe.com/fake"

    def test_dispatcher_can_reach_billing_portal(self, client):
        self._register_owner_and_dispatcher(client, "743333", "billing_dispatcher_3")
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "billing_dispatcher_3", "password": "dispatcherpass123"})

        response = client.post("/api/billing/portal", headers=_csrf_headers(client))
        assert response.status_code != 403


class TestAlertRules:
    """Customizable per-scenario location alert rules (Settings > Alerts) -
    CRUD, validation, and tenant isolation. The bot-side firing logic
    (defaults vs. custom thresholds) is covered separately in
    tests/test_bot_alert_rules.py."""

    def _register_owner(self, client, mc_number: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Alert Rules Test Co {mc_number}",
            "email": f"owner{mc_number}@alertruletest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        return reg.json()["company_id"]

    def test_create_list_update_delete_roundtrip(self, client):
        self._register_owner(client, "811111")

        created = client.post(
            "/api/settings/alert-rules",
            json={"scenario": "pu_near", "distance_miles": 50, "message_template": "{miles}mi to PU on #{load_id}"},
            headers=_csrf_headers(client),
        )
        assert created.status_code == 200, created.text
        rule = created.json()
        assert rule["scenario"] == "pu_near"
        assert rule["distance_miles"] == 50.0
        assert rule["enabled"] is True

        listed = client.get("/api/settings/alert-rules")
        assert listed.status_code == 200
        assert [r["id"] for r in listed.json()] == [rule["id"]]

        updated = client.patch(
            f"/api/settings/alert-rules/{rule['id']}",
            json={"distance_miles": 25, "enabled": False},
            headers=_csrf_headers(client),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["distance_miles"] == 25.0
        assert updated.json()["enabled"] is False
        # Untouched field should survive the partial update.
        assert updated.json()["message_template"] == "{miles}mi to PU on #{load_id}"

        deleted = client.delete(f"/api/settings/alert-rules/{rule['id']}", headers=_csrf_headers(client))
        assert deleted.status_code == 200
        assert client.get("/api/settings/alert-rules").json() == []

    def test_invalid_scenario_rejected(self, client):
        self._register_owner(client, "821111")
        response = client.post(
            "/api/settings/alert-rules",
            json={"scenario": "not_a_real_scenario", "distance_miles": 10},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 422

    def test_out_of_range_distance_rejected(self, client):
        self._register_owner(client, "831111")
        response = client.post(
            "/api/settings/alert-rules",
            json={"scenario": "pu_near", "distance_miles": 0},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 422

    def test_dispatcher_cannot_create_rules(self, client):
        self._register_owner(client, "841111")
        client.post(
            "/api/dispatchers",
            json={"username": "alertrule_dispatcher", "password": "password123"},
            headers=_csrf_headers(client),
        )
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "alertrule_dispatcher", "password": "password123"})

        response = client.post(
            "/api/settings/alert-rules",
            json={"scenario": "pu_near", "distance_miles": 10},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 403

    def test_cross_tenant_update_and_delete_forbidden(self):
        client_a = TestClient(app)
        client_b = TestClient(app)
        self._register_owner(client_a, "851111")
        self._register_owner(client_b, "861111")

        created = client_a.post(
            "/api/settings/alert-rules",
            json={"scenario": "del_near", "distance_miles": 10},
            headers=_csrf_headers(client_a),
        )
        rule_id = created.json()["id"]

        update = client_b.patch(
            f"/api/settings/alert-rules/{rule_id}",
            json={"distance_miles": 1},
            headers=_csrf_headers(client_b),
        )
        assert update.status_code == 404

        delete = client_b.delete(f"/api/settings/alert-rules/{rule_id}", headers=_csrf_headers(client_b))
        assert delete.status_code == 404

        # Company A's rule is untouched by B's attempts.
        still_there = client_a.get("/api/settings/alert-rules").json()
        assert still_there[0]["distance_miles"] == 10.0


class TestDriverCreation:
    """Self-service driver creation (owner only) - see miniapp/api.py's
    add_driver/regenerate_driver_link_code. The Telegram group-linking half
    (consuming the code) is covered by bot.py's handle_linkdriver, tested in
    tests/test_bot_linkdriver.py."""

    def _register_owner(self, client, mc_number: str) -> int:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Driver Creation Co {mc_number}",
            "email": f"owner{mc_number}@drivercreation.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        return reg.json()["company_id"]

    def test_create_driver_returns_link_code_and_appears_in_list(self, client):
        self._register_owner(client, "911111")

        created = client.post("/api/drivers", json={"full_name": "Jasur"}, headers=_csrf_headers(client))
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["full_name"] == "Jasur"
        assert body["driver_bot_id"] == "D001"
        assert body["telegram_group_id"] is None
        assert body["link_code"]
        assert body["bot_command"] == f"/linkdriver {body['link_code']}"

        listed = client.get("/api/drivers").json()
        assert len(listed) == 1
        assert listed[0]["full_name"] == "Jasur"

    def test_blank_name_rejected(self, client):
        self._register_owner(client, "921111")
        response = client.post("/api/drivers", json={"full_name": "   "}, headers=_csrf_headers(client))
        assert response.status_code == 422

    def test_dispatcher_can_create_driver(self, client):
        """Adding a driver is day-to-day dispatch work, not an ownership
        decision - drivers turn over constantly, and routing every hire
        through the owner would stall the board."""
        self._register_owner(client, "931111")
        client.post(
            "/api/dispatchers",
            json={"username": "driver_creation_dispatcher", "password": "password123"},
            headers=_csrf_headers(client),
        )
        client.post("/api/auth/logout", headers=_csrf_headers(client))
        client.post("/api/auth/dispatcher", json={"username": "driver_creation_dispatcher", "password": "password123"})

        response = client.post("/api/drivers", json={"full_name": "Nope"}, headers=_csrf_headers(client))
        assert response.status_code == 200, response.text

    def test_create_driver_requires_csrf(self, client):
        self._register_owner(client, "941111")
        response = client.post("/api/drivers", json={"full_name": "No CSRF"})
        assert response.status_code == 403

    def test_free_plan_cap_blocks_a_second_driver(self, client):
        self._register_owner(client, "951111")  # a brand-new company defaults to the free tier (limit 1)
        first = client.post("/api/drivers", json={"full_name": "First"}, headers=_csrf_headers(client))
        assert first.status_code == 200, first.text

        second = client.post("/api/drivers", json={"full_name": "Second"}, headers=_csrf_headers(client))
        assert second.status_code == 402
        assert "plan allows up to" in second.json()["detail"].lower()

    def test_link_token_regeneration_returns_a_fresh_code(self, client):
        self._register_owner(client, "961111")
        created = client.post("/api/drivers", json={"full_name": "Regen"}, headers=_csrf_headers(client))
        driver_id = created.json()["id"]

        regen = client.post(f"/api/drivers/{driver_id}/link-token", headers=_csrf_headers(client))
        assert regen.status_code == 200, regen.text
        assert regen.json()["code"]
        assert regen.json()["bot_command"] == f"/linkdriver {regen.json()['code']}"

    def test_link_token_regeneration_cross_tenant_forbidden(self):
        client_a = TestClient(app)
        client_b = TestClient(app)
        self._register_owner(client_a, "971111")
        self._register_owner(client_b, "981111")

        created = client_a.post("/api/drivers", json={"full_name": "Tenant A driver"}, headers=_csrf_headers(client_a))
        driver_id = created.json()["id"]

        response = client_b.post(f"/api/drivers/{driver_id}/link-token", headers=_csrf_headers(client_b))
        assert response.status_code == 403

    def test_link_code_can_be_consumed_to_complete_linking(self, client):
        """End-to-end: the code POST /api/drivers issues is a real
        TelegramLinkToken row that consume_telegram_link_token/
        link_driver_group (bot.py's handle_linkdriver) can actually redeem -
        not just three independently-mocked layers that happen to agree."""
        from db.repository import consume_telegram_link_token, link_driver_group

        self._register_owner(client, "991111")
        created = client.post("/api/drivers", json={"full_name": "Round Trip"}, headers=_csrf_headers(client))
        driver_id = created.json()["id"]
        code = created.json()["link_code"]

        result = consume_telegram_link_token(code)
        assert result == {"account_type": "driver_group", "account_id": driver_id}

        status = link_driver_group(result["account_id"], -100123456789, "Round Trip's Group")
        assert status == "ok"

        listed = client.get("/api/drivers").json()
        linked = next(d for d in listed if d["id"] == driver_id)
        assert linked["telegram_group_id"] == -100123456789
        assert linked["telegram_group_title"] == "Round Trip's Group"

        # The code is single-use - consuming it again must fail, exactly
        # like a driver re-sending /linkdriver with the same code twice.
        assert consume_telegram_link_token(code) is None


class TestSamsaraTestMode:
    """SAMSARA_TEST_MODE simulates GPS without a real Samsara account - see
    services/samsara_test_mode.py. Confirms the "Connected" status this
    unlocks in Settings/Monitoring doesn't depend on a saved credential."""

    def test_samsara_reports_disconnected_without_test_mode_or_credential(self, client):
        client.post("/api/auth/register", json={
            "mc_number": "871111",
            "company_name": "Samsara Test Mode Co",
            "email": "owner@samsaratestmode.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert client.get("/api/settings").json()["samsara_connected"] is False

    def test_test_mode_reports_connected_without_a_credential(self, client, monkeypatch):
        client.post("/api/auth/register", json={
            "mc_number": "881111",
            "company_name": "Samsara Test Mode Co 2",
            "email": "owner@samsaratestmode2.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        monkeypatch.setattr(api_module, "SAMSARA_TEST_MODE", True)
        assert client.get("/api/settings").json()["samsara_connected"] is True


class FakeSamsaraResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class TestWebauthnChallengeReplayProtection:
    """WebAuthn registration/login-verify used to trust a client-supplied
    challenge with no server-side record of what was actually issued - so
    a captured (credential_json, challenge) pair could be replayed
    indefinitely, completely defeating the "freshness" guarantee WebAuthn
    depends on. The challenge is now tracked server-side and consumed
    (single-use) on the first successful verify - see
    db/repository.py's create_webauthn_challenge/consume_webauthn_challenge
    and miniapp/api.py's webauthn_register_verify."""

    def _register_owner(self, client, mc_number: str):
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Webauthn Test Co {mc_number}",
            "email": f"owner{mc_number}@webauthntest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

    def test_verify_with_no_prior_options_call_is_rejected(self, client):
        self._register_owner(client, "955555")

        response = client.post(
            "/api/2fa/webauthn/register/verify",
            json={"credential_json": "{}", "label": "Test key"},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 400
        assert "expired" in response.json()["detail"].lower()

    def test_replaying_a_captured_verify_request_fails_the_second_time(self, client, monkeypatch):
        # Bypass real FIDO2 crypto verification - only the server-side
        # challenge plumbing is under test here, not the `webauthn`
        # library's own signature checking.
        monkeypatch.setattr(
            api_module.webauthn_service, "verify_registration",
            lambda credential_json, expected_challenge: {
                "credential_id": "cred-1", "public_key": "fake-pk", "sign_count": 0,
            },
        )
        self._register_owner(client, "952222")

        options = client.post("/api/2fa/webauthn/register/options", headers=_csrf_headers(client))
        assert options.status_code == 200
        assert "challenge" not in options.json()  # no longer handed to the client at all

        first = client.post(
            "/api/2fa/webauthn/register/verify",
            json={"credential_json": "captured-response", "label": "Test key"},
            headers=_csrf_headers(client),
        )
        assert first.status_code == 200, first.text

        # An attacker replaying the exact same captured request must not
        # succeed a second time - the challenge was already consumed.
        replay = client.post(
            "/api/2fa/webauthn/register/verify",
            json={"credential_json": "captured-response", "label": "Test key"},
            headers=_csrf_headers(client),
        )
        assert replay.status_code == 400
        assert "expired" in replay.json()["detail"].lower()

    def test_response_body_no_longer_accepts_a_client_supplied_challenge_field(self, client, monkeypatch):
        """Pydantic must reject/ignore a "challenge" field on the request -
        it's not part of WebAuthnVerifyRequest anymore, so there's no way
        for a client to influence which challenge gets verified against."""
        captured = {}

        def fake_verify(credential_json, expected_challenge):
            captured["expected_challenge"] = expected_challenge
            return {"credential_id": "cred-2", "public_key": "fake-pk", "sign_count": 0}

        monkeypatch.setattr(api_module.webauthn_service, "verify_registration", fake_verify)
        self._register_owner(client, "953333")
        client.post("/api/2fa/webauthn/register/options", headers=_csrf_headers(client))

        client.post(
            "/api/2fa/webauthn/register/verify",
            # Even if a client tries to smuggle its own "challenge", the
            # server-stored one must be what's actually used.
            json={"credential_json": "x", "challenge": "attacker-supplied-value", "label": "Test key"},
            headers=_csrf_headers(client),
        )
        assert captured["expected_challenge"] != "attacker-supplied-value"


class TestOtpSendErrorHandling:
    """POST /api/2fa/otp/send used to let a delivery failure (e.g.
    email_otp_service.send_otp_email's NotImplementedError when SMTP isn't
    configured) propagate uncaught, surfacing as a bare, detail-less 500 -
    now it's a clear 400/502 depending on the failure, and no pending_otp
    row is left behind for a code that was never actually sent. See
    otp_send in miniapp/api.py."""

    def _register_owner(self, client, mc_number: str):
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Otp Send Test Co {mc_number}",
            "email": f"owner{mc_number}@otpsendtest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

    def test_unconfigured_email_channel_returns_400_not_bare_500(self, client, monkeypatch):
        monkeypatch.setattr(api_module.email_otp_service, "is_configured", lambda: False)
        self._register_owner(client, "944444")

        response = client.post(
            "/api/2fa/otp/send",
            json={"channel": "email", "contact": "driver@example.com"},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 400
        assert "isn't configured" in response.json()["detail"].lower()

    def test_unconfigured_email_channel_does_not_persist_a_pending_otp(self, client, monkeypatch):
        from db.database import get_session
        from db import models

        monkeypatch.setattr(api_module.email_otp_service, "is_configured", lambda: False)
        self._register_owner(client, "942222")
        company_id = client.get("/api/me").json()["company_id"]

        client.post(
            "/api/2fa/otp/send",
            json={"channel": "email", "contact": "driver@example.com"},
            headers=_csrf_headers(client),
        )

        with get_session() as session:
            rows = (
                session.query(models.PendingOtp)
                .filter(
                    models.PendingOtp.account_type == "owner",
                    models.PendingOtp.account_id == company_id,
                    models.PendingOtp.channel == "email",
                    models.PendingOtp.purpose == "enroll",
                )
                .all()
            )
        assert rows == []

    def test_unexpected_send_error_returns_502_not_bare_500(self, client, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("simulated SMTP connection failure")

        monkeypatch.setattr(api_module.email_otp_service, "is_configured", lambda: True)
        monkeypatch.setattr(api_module.email_otp_service, "send_otp_email", _boom)
        self._register_owner(client, "943333")

        response = client.post(
            "/api/2fa/otp/send",
            json={"channel": "email", "contact": "driver@example.com"},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 502


class TestConnectSamsaraValidation:
    """POST /api/settings/samsara checks the token against the real API
    before saving, so a copy-pasted/revoked token doesn't just sit there
    looking "Connected" - see connect_samsara's docstring in miniapp/api.py.
    Only a clear 401/403 is a hard failure; anything else (including the API
    being unreachable) fails open and saves the token anyway."""

    def _register_owner(self, client, mc_number: str):
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Samsara Validation Co {mc_number}",
            "email": f"owner{mc_number}@samsaravalidation.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text

    def test_valid_token_is_saved(self, client, monkeypatch):
        self._register_owner(client, "891111")
        monkeypatch.setattr("requests.get", lambda *a, **k: FakeSamsaraResponse(200))

        resp = client.post(
            "/api/settings/samsara", json={"api_key": "good-token"}, headers=_csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        assert client.get("/api/settings").json()["samsara_connected"] is True

    def test_rejected_token_is_not_saved(self, client, monkeypatch):
        self._register_owner(client, "892222")
        monkeypatch.setattr("requests.get", lambda *a, **k: FakeSamsaraResponse(401))

        resp = client.post(
            "/api/settings/samsara", json={"api_key": "bad-token"}, headers=_csrf_headers(client),
        )
        assert resp.status_code == 400
        assert client.get("/api/settings").json()["samsara_connected"] is False

    def test_validation_request_failure_still_saves(self, client, monkeypatch):
        """A Samsara outage/timeout must not block someone from connecting a good key."""
        import requests

        def _raise(*a, **k):
            raise requests.ConnectionError("simulated network failure")

        self._register_owner(client, "893333")
        monkeypatch.setattr("requests.get", _raise)

        resp = client.post(
            "/api/settings/samsara", json={"api_key": "some-token"}, headers=_csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        assert client.get("/api/settings").json()["samsara_connected"] is True


class TestMandatoryGmailOnboarding:
    """Gmail connection is mandatory for owners - the bot's core feature
    (pulling rate confirmations from email) depends on it. The frontend
    enforces the redirect-to-onboarding gate, but the underlying signal
    it relies on (gmail_connected on every auth response) is what these
    tests lock in."""

    def test_fresh_registration_reports_gmail_not_connected(self, client):
        response = client.post("/api/auth/register", json={
            "mc_number": "710000",
            "company_name": "Onboarding Test Co",
            "email": "owner@onboardingtest.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        assert response.status_code == 200
        assert response.json()["gmail_connected"] is False

    def test_me_reflects_gmail_connected_after_credential_saved(self, client):
        reg = client.post("/api/auth/register", json={
            "mc_number": "720000",
            "company_name": "Onboarding Test Co 2",
            "email": "owner2@onboardingtest.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        company_id = reg.json()["company_id"]
        assert client.get("/api/me").json()["gmail_connected"] is False

        from db.repository import save_company_credential
        save_company_credential(company_id, "gmail_refresh_token", "fake-refresh-token-for-test")

        assert client.get("/api/me").json()["gmail_connected"] is True

    def test_dispatcher_response_has_no_gmail_connected_field(self, client):
        client.post("/api/auth/register", json={
            "mc_number": "730000",
            "company_name": "Onboarding Test Co 3",
            "email": "owner3@onboardingtest.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        client.post(
            "/api/dispatchers",
            json={"username": "onboarding_dispatcher", "password": "password123"},
            headers=_csrf_headers(client),
        )
        client.post("/api/auth/logout", headers=_csrf_headers(client))

        login = client.post("/api/auth/dispatcher", json={
            "username": "onboarding_dispatcher", "password": "password123",
        })
        assert "gmail_connected" not in login.json()
        assert "gmail_connected" not in client.get("/api/me").json()


class TestSecurityHeaders:
    def test_object_src_is_locked_down(self, client):
        """<object>/<embed> load plugin content and nothing here uses them.
        default-src covers it by fallback, but hardening guides ask for it
        to be stated, and a later default-src change must not quietly
        re-open it."""
        csp = client.get("/").headers["Content-Security-Policy"]
        assert "object-src 'none'" in csp

    def test_an_oversized_body_is_refused(self, client):
        """Starlette reads the whole body into memory before any validator
        sees it, so a per-field length check does not stop someone posting
        a gigabyte at an endpoint."""
        from miniapp.api import MAX_REQUEST_BODY_BYTES

        response = client.post(
            "/api/auth/owner",
            content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert "too large" in response.json()["detail"]

    def test_an_ordinary_body_still_gets_through(self, client):
        """The limit must sit well above anything real - a 401/422 here
        means the request reached the endpoint, which is the point."""
        response = client.post("/api/auth/owner", json={"mc_number": "999999", "password": "nope"})
        assert response.status_code != 413

    def test_security_headers_present_on_every_response(self, client):
        response = client.get("/api/public/stats")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


class TestPublicAPI:
    """Public API endpoints test"""

    def test_get_stats(self, client):
        """Test public statistics endpoint"""
        response = client.get("/api/public/stats")
        assert response.status_code == 200
        data = response.json()
        assert "companies" in data
        assert "active_trucks" in data
        assert "loads_delivered" in data
        assert "loads_value" in data
        # No "uptime" - there's no real monitoring to compute one from, and
        # this endpoint promises real database numbers, not fabricated ones.
        assert "uptime" not in data
        assert isinstance(data["companies"], int)


class TestProtectedEndpoints:
    """Protected endpoints (require authentication)"""

    def test_dashboard_unauthorized(self, client):
        """Test dashboard without auth"""
        response = client.get("/api/dashboard")
        assert response.status_code == 401

    def test_drivers_unauthorized(self, client):
        """Test drivers list without auth"""
        response = client.get("/api/drivers")
        assert response.status_code == 401

    def test_billing_unauthorized(self, client):
        """Test billing without auth"""
        response = client.get("/api/billing")
        assert response.status_code == 401


class TestHealthCheck:
    """Basic health checks"""

    def test_root_returns_html(self, client):
        """Test root path returns React app"""
        response = client.get("/")
        assert response.status_code == 200
        # Should serve React app HTML
        assert "<!DOCTYPE html>" in response.text or "<!doctype html>" in response.text

    def test_favicon_exists(self, client):
        """Test favicon is accessible"""
        response = client.get("/favicon.svg")
        assert response.status_code == 200

    def test_unknown_api_path_is_404_json(self, client):
        """An /api path with no route must not fall through to the SPA.

        The catch-all that serves index.html used to answer these 200 with a
        page of HTML, so a caller saw a success, found no JSON to parse, and
        continued with an empty object rather than being told the endpoint
        does not exist."""
        response = client.get("/api/definitely-not-a-real-endpoint")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert "definitely-not-a-real-endpoint" in response.json()["detail"]

    def test_unknown_page_path_still_serves_the_app(self, client):
        """Only /api is affected - React Router still handles its own routes."""
        response = client.get("/pages/some-client-side-route")
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.text or "<!doctype html>" in response.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
