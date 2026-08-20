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
import pytest
from fastapi.testclient import TestClient
import miniapp.api as api_module
from miniapp.api import app
from miniapp.auth import CSRF_COOKIE_NAME


@pytest.fixture(autouse=True)
def _disable_turnstile(monkeypatch):
    """Register/login call out to Cloudflare's live siteverify endpoint
    whenever TURNSTILE_SECRET_KEY is set - which breaks these tests (no
    token to send) as soon as a real key is configured in .env. Tests
    shouldn't depend on a live external service or on what's in .env, so
    force it off here regardless of the environment's actual config."""
    monkeypatch.setattr(api_module, "TURNSTILE_SECRET_KEY", None)


@pytest.fixture
def client():
    # Rate-limit counters live on the shared `app.state.limiter`, not per
    # TestClient instance - without resetting, tests would trip each
    # other's limits since they all originate from the same test IP.
    app.state.limiter.reset()
    return TestClient(app)


def _csrf_headers(client: TestClient) -> dict:
    """Reads the CSRF cookie the last login/register response set on this
    client and returns the header a mutating request must send alongside it."""
    token = client.cookies.get(CSRF_COOKIE_NAME)
    assert token, "no CSRF cookie set - must log in/register on this client first"
    return {"X-CSRF-Token": token}


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


class TestTenantIsolation:
    """SQLite has no row-level security, so tenant isolation is enforced
    entirely in miniapp/api.py. These tests lock in that every driver-scoped
    endpoint rejects access from a different company's owner, even with a
    valid, correctly-signed session cookie."""

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
        assert "uptime" in data
        assert isinstance(data["companies"], int)
        assert isinstance(data["uptime"], float)


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
