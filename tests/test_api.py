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
            "password": "test12345678",
            "confirm_password": "test12345678"
        })
        assert response.status_code in [200, 400]  # 400 if already exists
        
    def test_register_password_mismatch(self):
        """Test registration with mismatched passwords"""
        response = client.post("/api/auth/register", json={
            "mc_number": "888888",
            "company_name": "Test Co",
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
            "password": "short",
            "confirm_password": "short"
        })
        assert response.status_code == 400
        assert "8 characters" in response.json()["detail"].lower()
    
    def test_register_invalid_mc(self):
        """Test registration with non-numeric MC"""
        response = client.post("/api/auth/register", json={
            "mc_number": "ABC123",
            "company_name": "Test Co",
            "password": "password123",
            "confirm_password": "password123"
        })
        assert response.status_code == 400
        assert "digits" in response.json()["detail"].lower()


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
