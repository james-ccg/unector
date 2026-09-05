"""
What /api/me says about the company has to be current.

The session token carries a copy of the company name, stamped when the token
was minted. /api/me used to hand that back untouched, so renaming a company
left the header showing the old name while every screen that reads the
database showed the new one - the same account, named two different things
on one page, until the session happened to expire.

A token is for identity. company_id is the part that is signed and the part
that decides what anyone can reach; a display name is not authorisation, so
it gets read rather than trusted.
"""
import pytest

from db import models
from db.database import get_session
from miniapp.auth import SESSION_COOKIE_NAME, SESSION_PURPOSE, decode_token
from tests.conftest import unique_mc


def _register(client) -> tuple[str, int]:
    mc = unique_mc()
    response = client.post("/api/auth/register", json={
        "mc_number": mc,
        "company_name": f"Before {mc}",
        "email": f"owner{mc}@example.com",
        "password": "ownerpass123",
        "confirm_password": "ownerpass123",
    })
    assert response.status_code == 200, response.text
    with get_session() as session:
        company_id = (
            session.query(models.Company)
            .filter(models.Company.mc_number == mc)
            .first().id
        )
    return mc, company_id


def _rename(company_id: int, name: str) -> None:
    with get_session() as session:
        session.get(models.Company, company_id).company_name = name
        session.commit()


def test_the_name_starts_out_matching(client):
    mc, _ = _register(client)
    assert client.get("/api/me").json()["company_name"] == f"Before {mc}"


def test_a_rename_shows_up_without_signing_in_again(client):
    """The bug this file exists for. The session is untouched - only the
    company row changed - and the answer has to change with it."""
    mc, company_id = _register(client)
    _rename(company_id, f"After {mc}")

    assert client.get("/api/me").json()["company_name"] == f"After {mc}"


def test_the_token_still_carries_the_old_copy(client):
    """Deliberate: the fix is that the copy is no longer *believed*, not
    that it was removed. Minting a fresh token on every rename would mean
    reissuing a session from a request that is not a sign-in."""
    mc, company_id = _register(client)
    _rename(company_id, f"After {mc}")

    claims = decode_token(client.cookies.get(SESSION_COOKIE_NAME), purpose=SESSION_PURPOSE)
    assert claims["company_name"] == f"Before {mc}"
    assert client.get("/api/me").json()["company_name"] == f"After {mc}"


def test_the_header_and_the_team_list_agree(client):
    """The two surfaces in the screenshot that reported this: one read the
    token, the other read the database."""
    mc, company_id = _register(client)
    _rename(company_id, f"Renamed {mc}")

    me = client.get("/api/me").json()
    owner_row = next(m for m in client.get("/api/team").json() if m["role"] == "owner")
    assert me["company_name"] == owner_row["name"] == f"Renamed {mc}"


def test_identity_is_still_taken_from_the_signed_token(client):
    """company_id decides what the session can reach, and it keeps coming
    from the token rather than from anything the response looked up."""
    _, company_id = _register(client)
    assert client.get("/api/me").json()["company_id"] == company_id


def test_a_dispatcher_sees_the_current_company_name(client):
    """They carry the same copy in their own token."""
    mc, company_id = _register(client)
    from tests.conftest import csrf_headers

    created = client.post(
        "/api/dispatchers",
        json={"username": f"disp{mc}", "password": "dispatcherpass1"},
        headers=csrf_headers(client),
    )
    assert created.status_code == 200, created.text
    client.post("/api/auth/logout", headers=csrf_headers(client))
    client.post(
        "/api/auth/dispatcher",
        json={"username": f"disp{mc}", "password": "dispatcherpass1"},
    )

    _rename(company_id, f"Renamed {mc}")
    assert client.get("/api/me").json()["company_name"] == f"Renamed {mc}"


def test_a_company_that_no_longer_exists_does_not_crash_the_call(client):
    """/api/me is on every page load. It failing outright would lock
    somebody out of the app rather than show them a stale name."""
    _, company_id = _register(client)
    with get_session() as session:
        session.query(models.Company).filter(models.Company.id == company_id).delete()
        session.commit()

    response = client.get("/api/me")
    assert response.status_code == 200, response.text
