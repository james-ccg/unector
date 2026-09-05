"""
Every way into a session has to answer with the same thing.

There are four: registering, a password login, finishing 2FA, and finishing
WebAuthn - plus the check the app makes on every page load. Each of them was
assembling the reply by hand, and three left out the avatar and the status.
Signing in therefore showed a blank profile picture until something happened
to call /api/me and fill it in, which pressing F5 does. That is the tell: the
data was always there, it just was not in the reply that mattered.

So these tests are about shape rather than values. A field that /api/me
returns and a login does not is the same bug again, whatever the field turns
out to be next time.
"""
import pytest

from db import models, repository
from db.database import get_session
from tests.conftest import csrf_headers, unique_mc

PIXEL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _register(client) -> tuple[str, dict]:
    mc = unique_mc()
    response = client.post("/api/auth/register", json={
        "mc_number": mc,
        "company_name": f"Shape {mc}",
        "email": f"owner{mc}@example.com",
        "password": "ownerpass123",
        "confirm_password": "ownerpass123",
    })
    assert response.status_code == 200, response.text
    return mc, response.json()


def _company_id(mc: str) -> int:
    with get_session() as session:
        return (
            session.query(models.Company).filter(models.Company.mc_number == mc).first().id
        )


class TestSigningInAnswersInFull:
    def test_a_password_login_carries_the_avatar(self, client):
        """The bug this file exists for: the picture was there all along and
        only appeared after a refresh."""
        mc, _ = _register(client)
        repository.set_account_avatar("owner", _company_id(mc), PIXEL)
        client.post("/api/auth/logout", headers=csrf_headers(client))

        signed_in = client.post(
            "/api/auth/owner", json={"mc_number": mc, "password": "ownerpass123"},
        )
        assert signed_in.status_code == 200, signed_in.text
        assert signed_in.json()["avatar"] == PIXEL

    def test_a_password_login_carries_the_status(self, client):
        """Same reply, same omission - nobody had noticed this half yet."""
        mc, _ = _register(client)
        company_id = _company_id(mc)
        repository.set_account_status("owner", company_id, "🚚", "On the road", None)
        client.post("/api/auth/logout", headers=csrf_headers(client))

        body = client.post(
            "/api/auth/owner", json={"mc_number": mc, "password": "ownerpass123"},
        ).json()
        assert body["status"]["text"] == "On the road"

    def test_a_dispatcher_login_carries_theirs_too(self, client):
        mc, _ = _register(client)
        created = client.post(
            "/api/dispatchers",
            json={"username": f"disp{mc}", "password": "dispatcherpass1"},
            headers=csrf_headers(client),
        )
        assert created.status_code == 200, created.text
        repository.set_account_avatar("dispatcher", created.json()["id"], PIXEL)
        client.post("/api/auth/logout", headers=csrf_headers(client))

        body = client.post(
            "/api/auth/dispatcher",
            json={"username": f"disp{mc}", "password": "dispatcherpass1"},
        ).json()
        assert body["avatar"] == PIXEL


class TestTheShapesMatch:
    """What a login returns and what the page-load check returns have to be
    the same set of keys. Comparing keys rather than values is deliberate -
    the next field somebody adds to /api/me will be forgotten in exactly the
    same three places."""

    def test_a_password_login_matches_the_page_load_check(self, client):
        mc, _ = _register(client)
        repository.set_account_avatar("owner", _company_id(mc), PIXEL)
        client.post("/api/auth/logout", headers=csrf_headers(client))

        login = client.post(
            "/api/auth/owner", json={"mc_number": mc, "password": "ownerpass123"},
        ).json()
        me = client.get("/api/me").json()
        assert set(login) == set(me)
        assert login == me

    def test_registering_matches_it_as_well(self, client):
        """mc_number is the one extra - the signup flow shows it back, and
        nothing else needs it."""
        _, registered = _register(client)
        me = client.get("/api/me").json()
        assert set(registered) - set(me) == {"mc_number"}
        assert set(me) - set(registered) == set()

    @pytest.mark.parametrize("field", ["purpose", "sid", "exp"])
    def test_the_token_s_own_bookkeeping_stays_out_of_the_reply(self, client, field):
        """These describe how the token keeps itself honest, not the account.
        `sid` in particular is the session id the CSRF token is bound to, and
        the cookie carrying it is httpOnly precisely so page scripts cannot
        read it - handing it over in JSON gave that away for nothing."""
        _register(client)
        assert field not in client.get("/api/me").json()

    @pytest.mark.parametrize("field", ["role", "company_id", "company_name", "status", "avatar"])
    def test_the_fields_a_header_needs_are_all_there(self, client, field):
        """Named individually so a failure says which one went missing
        rather than printing two sets and leaving the diff to the reader."""
        mc, _ = _register(client)
        client.post("/api/auth/logout", headers=csrf_headers(client))
        body = client.post(
            "/api/auth/owner", json={"mc_number": mc, "password": "ownerpass123"},
        ).json()
        assert field in body
