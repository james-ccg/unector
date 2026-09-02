"""A token issued for one purpose must not work as a login session.

miniapp.auth.create_token mints JWTs for several jobs - the login session
itself, the 2FA handshake, OAuth `state`, password reset - all signed with
the same key. get_current_user only checked the signature and the expiry,
so any of those was accepted as `fp_session`.

The 2FA handshake token is the dangerous one: the login endpoint hands it
straight back to the caller in the "requires_2fa" response body, before any
second factor has been supplied. Setting it as the session cookie skipped
2FA entirely.
"""
import pyotp

from miniapp.auth import SESSION_COOKIE_NAME
from tests.conftest import csrf_headers, unique_mc


def _owner_with_totp(client):
    """Registers an owner, turns TOTP on, and returns (mc, password)."""
    mc = unique_mc()
    password = "correct-horse-battery-staple-9"
    response = client.post("/api/auth/register", json={
        "mc_number": mc,
        "company_name": "Scope Test Freight",
        "email": f"scope{mc}@example.com",
        "password": password,
        "confirm_password": password,
    })
    assert response.status_code == 200, response.text

    secret = client.post("/api/2fa/totp/setup", headers=csrf_headers(client)).json()["secret"]
    confirmed = client.post(
        "/api/2fa/totp/verify",
        json={"channel": "totp", "code": pyotp.TOTP(secret).now()},
        headers=csrf_headers(client),
    )
    assert confirmed.status_code == 200, confirmed.text
    client.cookies.clear()
    return mc, password


class TestTokenPurposeIsEnforced:
    def test_2fa_pending_token_is_not_a_session(self, client):
        """Knowing the password must not be enough when 2FA is on."""
        mc, password = _owner_with_totp(client)

        login = client.post("/api/auth/owner", json={"mc_number": mc, "password": password})
        body = login.json()
        assert body.get("requires_2fa") is True, body
        pending_token = body["pending_token"]

        # The attacker has the handshake token and nothing else.
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE_NAME, pending_token)
        assert client.get("/api/me").status_code == 401

    def test_oauth_state_token_is_not_a_session(self, client):
        """The `state` in an OAuth redirect is public - it travels through
        Google and lands in a URL. It carries company_id, so before the
        purpose check it authenticated as that company."""
        from miniapp.auth import create_token

        state = create_token(
            {"company_id": 1, "role": "owner", "purpose": "gmail_oauth", "return_to": "settings"},
            lifetime_seconds=600,
        )
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE_NAME, state)
        assert client.get("/api/me").status_code == 401

    def test_a_real_session_still_works(self, client):
        """The check must not lock out the ordinary path."""
        mc = unique_mc()
        password = "correct-horse-battery-staple-9"
        client.post("/api/auth/register", json={
            "mc_number": mc,
            "company_name": "Scope Test Freight",
            "email": f"ok{mc}@example.com",
            "password": password,
            "confirm_password": password,
        })
        assert client.get("/api/me").status_code == 200

        client.cookies.clear()
        login = client.post("/api/auth/owner", json={"mc_number": mc, "password": password})
        assert login.status_code == 200, login.text
        assert client.get("/api/me").status_code == 200


class TestCsrfIsBoundToTheSession:
    """A CSRF token proves the request came from our page, but only if it
    cannot be minted by whoever sent it. See csrf_token_for in
    miniapp/auth.py for why matching halves are not enough on their own."""

    def _register(self, client):
        mc = unique_mc()
        password = "correct-horse-battery-staple-9"
        response = client.post("/api/auth/register", json={
            "mc_number": mc,
            "company_name": "CSRF Test Freight",
            "email": f"csrf{mc}@example.com",
            "password": password,
            "confirm_password": password,
        })
        assert response.status_code == 200, response.text
        return mc, password

    def test_a_token_from_another_session_is_rejected(self, client):
        from fastapi.testclient import TestClient
        from miniapp.api import app
        from miniapp.auth import CSRF_COOKIE_NAME

        self._register(client)
        victim_csrf = client.cookies.get(CSRF_COOKIE_NAME)

        # A second, unrelated account - its CSRF token is validly formed and
        # its two halves match, they are simply not this session's.
        other = TestClient(app)
        self._register(other)
        attacker_csrf = other.cookies.get(CSRF_COOKIE_NAME)
        assert attacker_csrf and attacker_csrf != victim_csrf

        client.cookies.set(CSRF_COOKIE_NAME, attacker_csrf)
        response = client.put(
            "/api/me/status",
            json={"emoji": None, "text": "on the road", "expires_at": None},
            headers={"X-CSRF-Token": attacker_csrf},
        )
        assert response.status_code == 403, response.text

    def test_a_forged_token_is_rejected(self, client):
        """Writing both halves is exactly what a cookie-injection attack
        buys, and it must not be enough."""
        from miniapp.auth import CSRF_COOKIE_NAME

        self._register(client)
        forged = "deadbeef" * 8 + ".0123456789abcdef"
        client.cookies.set(CSRF_COOKIE_NAME, forged)
        response = client.put(
            "/api/me/status",
            json={"emoji": None, "text": "on the road", "expires_at": None},
            headers={"X-CSRF-Token": forged},
        )
        assert response.status_code == 403, response.text

    def test_the_real_token_still_works(self, client):
        self._register(client)
        response = client.put(
            "/api/me/status",
            json={"emoji": None, "text": "on the road", "expires_at": None},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
