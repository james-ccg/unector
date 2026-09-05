"""
Tests for setting a driver's Telegram group from the dashboard.

A group becomes a company's by somebody running /linkdriver inside it with
a code, which is what proves they are in the group. These endpoints only
move a group the company already holds, and the test that matters most is
the one saying a typed-in chat id gets nowhere: without it, any company
could start posting loads into a stranger's chat.
"""
import pytest

from db.database import init_db, get_session
from db import models, repository
from tests.conftest import unique_mc


@pytest.fixture
def setup_db():
    init_db()
    yield


@pytest.fixture
def company_with_two_drivers(setup_db):
    # drivers.telegram_group_id is unique across the whole table, so each
    # test needs its own chat id rather than a shared constant.
    mc = unique_mc()
    chat_id = -100_000_000 - int(mc[-6:] if mc[-6:].isdigit() else 1)
    with get_session() as session:
        company = models.Company(
            mc_number=mc,
            company_name=f"Group Test {mc}",
            telegram_group_prefix=f"G{mc}",
        )
        session.add(company)
        session.commit()
        session.refresh(company)

        first = models.Driver(
            company_id=company.id, driver_bot_id="D001", full_name="Driver One",
            telegram_group_id=chat_id, telegram_group_title="1001 - Driver One",
        )
        second = models.Driver(
            company_id=company.id, driver_bot_id="D002", full_name="Driver Two",
        )
        session.add_all([first, second])
        session.commit()
        session.refresh(first)
        session.refresh(second)
        return company.id, first.id, second.id, chat_id


def _group_of(driver_id):
    with get_session() as session:
        d = session.get(models.Driver, driver_id)
        return d.telegram_group_id, d.telegram_group_title


class TestUnlinking:
    def test_a_group_can_be_taken_off_a_driver(self, company_with_two_drivers):
        """The case a dashboard needs most: a truck sold on a Sunday, with
        nobody able to get into the group to run a command."""
        company_id, first, _, chat_id = company_with_two_drivers
        assert repository.set_driver_group(first, company_id, None) == (True, "ok")
        assert _group_of(first) == (None, None)

    def test_unlinking_a_driver_who_has_no_group_is_not_an_error(self, company_with_two_drivers):
        company_id, _, second, chat_id = company_with_two_drivers
        assert repository.set_driver_group(second, company_id, None) == (True, "ok")


class TestMoving:
    def test_a_group_moves_between_drivers_in_the_company(self, company_with_two_drivers):
        company_id, first, second, chat_id = company_with_two_drivers
        assert repository.set_driver_group(second, company_id, chat_id) == (True, "ok")
        assert _group_of(second) == (chat_id, "1001 - Driver One")
        assert _group_of(first) == (None, None)

    def test_a_driver_who_already_holds_it_keeps_it(self, company_with_two_drivers):
        company_id, first, _, chat_id = company_with_two_drivers
        assert repository.set_driver_group(first, company_id, chat_id) == (True, "ok")
        assert _group_of(first)[0] == chat_id


class TestAGroupCannotBeClaimedByTyping:
    def test_an_unknown_chat_id_is_refused(self, company_with_two_drivers):
        """The whole point of the restriction. Accepting this would let any
        company post loads into a chat it has never been in."""
        company_id, _, second, chat_id = company_with_two_drivers
        ok, reason = repository.set_driver_group(second, company_id, chat_id - 777)
        assert (ok, reason) == (False, "not_this_company")
        assert _group_of(second) == (None, None)

    def test_another_company_group_is_refused(self, company_with_two_drivers):
        company_id, _, second, chat_id = company_with_two_drivers
        mc = unique_mc()
        with get_session() as session:
            other = models.Company(
                mc_number=mc, company_name=f"Other {mc}", telegram_group_prefix=f"O{mc}",
            )
            session.add(other)
            session.commit()
            session.refresh(other)
            session.add(models.Driver(
                company_id=other.id, driver_bot_id="D001", full_name="Driver Three",
                telegram_group_id=chat_id - 555,
            ))
            session.commit()

        ok, reason = repository.set_driver_group(second, company_id, chat_id - 555)
        assert (ok, reason) == (False, "not_this_company")

    def test_another_company_driver_is_not_found(self, company_with_two_drivers):
        company_id, first, _, chat_id = company_with_two_drivers
        ok, reason = repository.set_driver_group(first, company_id + 9999, None)
        assert (ok, reason) == (False, "not_found")


class TestListing:
    def test_only_linked_groups_are_listed(self, company_with_two_drivers):
        company_id, first, _, chat_id = company_with_two_drivers
        groups = repository.company_groups(company_id)
        assert [g["telegram_group_id"] for g in groups] == [chat_id]
        assert groups[0]["driver_id"] == first
        assert groups[0]["driver_bot_id"] == "D001"

    def test_a_company_with_no_groups_gets_an_empty_list(self, setup_db):
        mc = unique_mc()
        with get_session() as session:
            company = models.Company(
                mc_number=mc, company_name=f"Empty {mc}", telegram_group_prefix=f"E{mc}",
            )
            session.add(company)
            session.commit()
            session.refresh(company)
            company_id = company.id
        assert repository.company_groups(company_id) == []


# ------------------------------------------------------------------
# The same rules over HTTP.
# ------------------------------------------------------------------
from fastapi.testclient import TestClient  # noqa: E402

from miniapp.api import app  # noqa: E402
from tests.conftest import csrf_headers  # noqa: E402


def _register_owner(client, mc_number: str) -> None:
    reg = client.post("/api/auth/register", json={
        "mc_number": mc_number,
        "company_name": f"Group Co {mc_number}",
        "email": f"owner{mc_number}@example.com",
        "password": "ownerpass123",
        "confirm_password": "ownerpass123",
    })
    assert reg.status_code == 200, reg.text


class TestOverHTTP:
    def test_the_endpoints_need_a_session(self, client):
        assert client.get("/api/groups").status_code == 401
        assert client.put("/api/drivers/1/group", json={"telegram_group_id": None}).status_code == 401

    def test_a_company_with_no_groups_sees_none(self, client):
        _register_owner(client, unique_mc())
        assert client.get("/api/groups").json() == {"groups": []}

    def test_unlinking_a_driver_succeeds(self, client):
        _register_owner(client, unique_mc())
        created = client.post(
            "/api/drivers", json={"full_name": "Driver One"}, headers=csrf_headers(client),
        )
        assert created.status_code == 200, created.text
        driver_id = created.json()["id"]

        response = client.put(
            f"/api/drivers/{driver_id}/group",
            json={"telegram_group_id": None},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text

    def test_a_chat_id_the_company_has_never_been_in_is_refused_and_says_why(self, client):
        """403 with the actual reason, not a bare failure - the fix is a
        Telegram step, and the message has to name it."""
        _register_owner(client, unique_mc())
        created = client.post(
            "/api/drivers", json={"full_name": "Driver One"}, headers=csrf_headers(client),
        )
        driver_id = created.json()["id"]

        response = client.put(
            f"/api/drivers/{driver_id}/group",
            json={"telegram_group_id": -100123123123},
            headers=csrf_headers(client),
        )
        assert response.status_code == 403, response.text
        assert "/linkdriver" in response.json()["detail"]

    def test_another_company_driver_is_not_found(self, client):
        _register_owner(client, unique_mc())
        created = client.post(
            "/api/drivers", json={"full_name": "Driver One"}, headers=csrf_headers(client),
        )
        driver_id = created.json()["id"]

        second = TestClient(app)
        _register_owner(second, unique_mc())
        response = second.put(
            f"/api/drivers/{driver_id}/group",
            json={"telegram_group_id": None},
            headers=csrf_headers(second),
        )
        assert response.status_code == 404, response.text
