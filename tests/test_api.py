"""
Test suite for Freight Pilot API endpoints.
Run: pytest tests/ -v
"""
import pytest
from fastapi.testclient import TestClient
from miniapp.api import app

client = TestClient(app)


class TestAuth:
    """Authentication endpoints test"""
    
    def test_register_success(self):
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

    def test_register_password_mismatch(self):
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

    def test_register_short_password(self):
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

    def test_register_invalid_mc(self):
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

    def test_register_invalid_email(self):
        """Test registration with a malformed email - rejected by request validation (422)"""
        response = client.post("/api/auth/register", json={
            "mc_number": "666666",
            "company_name": "Test Co",
            "email": "not-an-email",
            "password": "password123",
            "confirm_password": "password123"
        })
        assert response.status_code == 422

    def test_register_missing_email(self):
        """Test registration with no email at all - rejected by request validation (422)"""
        response = client.post("/api/auth/register", json={
            "mc_number": "555555",
            "company_name": "Test Co",
            "password": "password123",
            "confirm_password": "password123"
        })
        assert response.status_code == 422


class TestDispatcherAuth:
    """Regression test: dispatcher logins used to omit dispatcher_id from the
    JWT, which crashed every 2FA endpoint for a dispatcher account (they all
    resolve "self" via user["dispatcher_id"])."""

    def _register_owner_and_dispatcher(self, mc_number: str, dispatcher_username: str):
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": "Dispatcher Test Co",
            "email": "owner@dispatchertest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        owner_token = reg.json()["token"]

        created = client.post(
            "/api/dispatchers",
            json={"username": dispatcher_username, "password": "dispatcherpass123"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert created.status_code == 200, created.text
        return owner_token

    def test_dispatcher_login_includes_dispatcher_id(self):
        self._register_owner_and_dispatcher("444444", "dispatcher_regress_1")

        login = client.post("/api/auth/dispatcher", json={
            "username": "dispatcher_regress_1",
            "password": "dispatcherpass123",
        })
        assert login.status_code == 200, login.text
        body = login.json()
        assert body.get("dispatcher_id"), "login response must include dispatcher_id"

    def test_dispatcher_can_load_2fa_status_without_500(self):
        self._register_owner_and_dispatcher("333333", "dispatcher_regress_2")

        login = client.post("/api/auth/dispatcher", json={
            "username": "dispatcher_regress_2",
            "password": "dispatcherpass123",
        })
        dispatcher_token = login.json()["token"]

        status = client.get("/api/2fa/status", headers={"Authorization": f"Bearer {dispatcher_token}"})
        assert status.status_code == 200, status.text


class TestTenantIsolation:
    """SQLite has no row-level security, so tenant isolation is enforced
    entirely in miniapp/api.py. These tests lock in that every driver-scoped
    endpoint rejects access from a different company's owner, even with a
    valid, correctly-signed session token."""

    def _register_owner(self, mc_number: str) -> tuple[str, int]:
        reg = client.post("/api/auth/register", json={
            "mc_number": mc_number,
            "company_name": f"Tenant Test Co {mc_number}",
            "email": f"owner{mc_number}@tenanttest.com",
            "password": "ownerpass123",
            "confirm_password": "ownerpass123",
        })
        assert reg.status_code == 200, reg.text
        body = reg.json()
        return body["token"], body["company_id"]

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
        _, company_a_id = self._register_owner("211111")
        owner_b_token, _ = self._register_owner("311111")
        driver_a_id = self._create_driver(company_a_id)

        response = client.get(
            f"/api/drivers/{driver_a_id}",
            headers={"Authorization": f"Bearer {owner_b_token}"},
        )
        assert response.status_code == 403

    def test_cross_tenant_subscription_toggle_forbidden(self):
        _, company_a_id = self._register_owner("411111")
        owner_b_token, _ = self._register_owner("511111")
        driver_a_id = self._create_driver(company_a_id)

        response = client.patch(
            f"/api/drivers/{driver_a_id}/subscription",
            json={"active": False},
            headers={"Authorization": f"Bearer {owner_b_token}"},
        )
        assert response.status_code == 403

    def test_own_tenant_driver_details_allowed(self):
        owner_token, company_id = self._register_owner("611111")
        driver_id = self._create_driver(company_id)

        response = client.get(
            f"/api/drivers/{driver_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert response.status_code == 200


class TestPublicAPI:
    """Public API endpoints test"""
    
    def test_get_stats(self):
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
    
    def test_dashboard_unauthorized(self):
        """Test dashboard without auth"""
        response = client.get("/api/dashboard")
        assert response.status_code == 401
    
    def test_drivers_unauthorized(self):
        """Test drivers list without auth"""
        response = client.get("/api/drivers")
        assert response.status_code == 401
    
    def test_billing_unauthorized(self):
        """Test billing without auth"""
        response = client.get("/api/billing")
        assert response.status_code == 401


class TestHealthCheck:
    """Basic health checks"""
    
    def test_root_returns_html(self):
        """Test root path returns React app"""
        response = client.get("/")
        assert response.status_code == 200
        # Should serve React app HTML
        assert "<!DOCTYPE html>" in response.text or "<!doctype html>" in response.text
    
    def test_favicon_exists(self):
        """Test favicon is accessible"""
        response = client.get("/favicon.svg")
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
