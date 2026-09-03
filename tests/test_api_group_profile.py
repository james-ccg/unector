"""
The dashboard half of confirming what a truck group's description says.

The same proposal is confirmable from Telegram, which is what most of these
cover: one company must not see or confirm another's reading, and the side
that gets there second must be told so rather than shown a failure.
"""
import pytest

from db import models, repository
from db.database import get_session
from tests.conftest import csrf_headers, unique_mc


@pytest.fixture
def owner(client):
    mc = unique_mc()
    response = client.post("/api/auth/register", json={
        "mc_number": mc,
        "company_name": f"Bio Carrier {mc}",
        "email": f"owner{mc}@example.com",
        "password": "correcthorse123",
        "confirm_password": "correcthorse123",
    })
    assert response.status_code == 200, response.text

    with get_session() as session:
        company = session.query(models.Company).filter_by(mc_number=mc).first()
        driver = models.Driver(company_id=company.id, driver_bot_id="D700")
        session.add(driver)
        session.commit()
        return {"client": client, "company_id": company.id, "driver_id": driver.id}


def _propose(owner, **overrides):
    fields = {"truck_number": "1001", "driver_name": "Test Driver", "driver_phone": "410-555-0142"}
    fields.update(overrides)
    return repository.save_group_profile_proposal(
        owner["company_id"], owner["driver_id"], -100700001,
        title="UNIT 1001", description="Driver: Test Driver", fields=fields,
    )


class TestListing:
    def test_pending_readings_are_listed_with_their_source_text(self, owner):
        _propose(owner)
        response = owner["client"].get("/api/group-profiles")
        assert response.status_code == 200

        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["fields"]["truck_number"] == "1001"
        assert rows[0]["source_description"] == "Driver: Test Driver"

    def test_a_confirmed_reading_drops_off_the_list(self, owner):
        proposal = _propose(owner)
        client = owner["client"]
        client.post(f"/api/group-profiles/{proposal['id']}/confirm",
                    json={}, headers=csrf_headers(client))
        assert client.get("/api/group-profiles").json() == []

    def test_signing_in_is_required(self, client):
        assert client.get("/api/group-profiles").status_code == 401


class TestConfirming:
    def test_confirming_saves_the_details(self, owner):
        proposal = _propose(owner)
        client = owner["client"]
        response = client.post(f"/api/group-profiles/{proposal['id']}/confirm",
                               json={}, headers=csrf_headers(client))
        assert response.status_code == 200

        identity = repository.get_driver_identity(owner["driver_id"], owner["company_id"])
        assert identity["full_name"] == "Test Driver"
        assert identity["truck_unit_number"] == "1001"

    def test_a_corrected_value_is_what_gets_saved(self, owner):
        """A misread digit should be fixed in the form, not thrown away."""
        proposal = _propose(owner)
        client = owner["client"]
        response = client.post(
            f"/api/group-profiles/{proposal['id']}/confirm",
            json={"fields": {"truck_number": "1004"}},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200

        identity = repository.get_driver_identity(owner["driver_id"], owner["company_id"])
        assert identity["truck_unit_number"] == "1004"
        assert identity["full_name"] == "Test Driver"  # untouched fields survive

    def test_a_field_the_app_has_nowhere_to_put_is_ignored(self, owner):
        proposal = _propose(owner)
        client = owner["client"]
        response = client.post(
            f"/api/group-profiles/{proposal['id']}/confirm",
            json={"fields": {"driver_bot_id": "HACKED", "subscription_active": "false"}},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200

        with get_session() as session:
            driver = session.get(models.Driver, owner["driver_id"])
            assert driver.driver_bot_id == "D700"
            assert driver.subscription_active is True

    def test_telegram_getting_there_first_is_a_409_not_a_failure(self, owner):
        proposal = _propose(owner)
        repository.apply_group_profile_proposal(proposal["id"], "telegram")

        client = owner["client"]
        response = client.post(f"/api/group-profiles/{proposal['id']}/confirm",
                               json={}, headers=csrf_headers(client))
        assert response.status_code == 409
        assert "already confirmed" in response.json()["detail"]

    def test_another_company_cannot_confirm_this_reading(self, owner, client):
        proposal = _propose(owner)

        mc = unique_mc()
        other = client
        assert other.post("/api/auth/register", json={
            "mc_number": mc, "company_name": "Someone Else", "email": f"x{mc}@example.com",
            "password": "correcthorse123", "confirm_password": "correcthorse123",
        }).status_code == 200

        response = other.post(f"/api/group-profiles/{proposal['id']}/confirm",
                              json={}, headers=csrf_headers(other))
        assert response.status_code == 404

    def test_confirming_needs_the_csrf_header(self, owner):
        proposal = _propose(owner)
        response = owner["client"].post(f"/api/group-profiles/{proposal['id']}/confirm", json={})
        assert response.status_code == 403


class TestDismissing:
    def test_dismissing_leaves_the_driver_untouched(self, owner):
        proposal = _propose(owner)
        client = owner["client"]
        assert client.post(f"/api/group-profiles/{proposal['id']}/dismiss",
                           headers=csrf_headers(client)).status_code == 200

        identity = repository.get_driver_identity(owner["driver_id"], owner["company_id"])
        assert identity["full_name"] is None


class TestTypingItInByHand:
    def test_details_can_be_saved_with_no_reading_involved(self, owner):
        client = owner["client"]
        response = client.patch(
            f"/api/drivers/{owner['driver_id']}/details",
            json={"driver_name": "Co Driver", "driver_phone": "619-555-0175",
                  "truck_number": "1010", "trailer_number": "A000123"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200

        identity = repository.get_driver_identity(owner["driver_id"], owner["company_id"])
        assert identity["full_name"] == "Co Driver"
        assert identity["truck_unit_number"] == "1010"

    def test_an_empty_body_is_a_400(self, owner):
        client = owner["client"]
        response = client.patch(f"/api/drivers/{owner['driver_id']}/details",
                                json={}, headers=csrf_headers(client))
        assert response.status_code == 400

    def test_another_company_cannot_write_to_this_driver(self, owner, client):
        mc = unique_mc()
        assert client.post("/api/auth/register", json={
            "mc_number": mc, "company_name": "Someone Else", "email": f"y{mc}@example.com",
            "password": "correcthorse123", "confirm_password": "correcthorse123",
        }).status_code == 200

        response = client.patch(
            f"/api/drivers/{owner['driver_id']}/details",
            json={"driver_name": "Not Theirs"}, headers=csrf_headers(client),
        )
        assert response.status_code == 404
