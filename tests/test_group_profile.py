"""The truck/driver details a dispatch group's bio carries.

Two things are worth holding still here: what the reader is allowed to make
of a bio, and the rule that nothing reaches Driver or Truck until a person
confirms it - from either side, once.
"""
import pytest

from db import models, repository
from db.database import get_session
from services import group_profile


@pytest.fixture
def company_and_driver(request):
    # A fresh carrier per test - mc_number and the group prefix are unique
    # per company, so tests sharing one would collide on the second insert.
    tag = f"BIO{abs(hash(request.node.name)) % 100000}"
    with get_session() as session:
        company = models.Company(
            mc_number=f"MC-{tag}",
            company_name="Bio Test Carrier",
            telegram_group_prefix=tag,
        )
        session.add(company)
        session.commit()
        driver = models.Driver(company_id=company.id, driver_bot_id="D900")
        session.add(driver)
        session.commit()
        return company.id, driver.id


# ------------------------------------------------------------------
# Reading the bio
# ------------------------------------------------------------------

def test_empty_and_placeholder_values_are_dropped():
    fields = group_profile.clean_fields({
        "truck_number": " 3001 ",
        "trailer_number": "",
        "driver_name": "Fareedullah",
        "vin": "N/A",
        "driver_email": None,
        "co_driver_name": "  ",
    })
    assert fields == {"truck_number": "3001", "driver_name": "Fareedullah"}


def test_unknown_keys_never_survive():
    """A field the app has nowhere to put must not reach the proposal."""
    assert group_profile.clean_fields({"tablet": "T-11", "dispatcher": "Sam"}) == {}


def test_a_bio_that_disagrees_with_the_records_says_so():
    conflicts = group_profile.find_conflicts(
        {"truck_number": "3001", "driver_name": "Hamza"},
        {"truck_unit_number": "3004", "full_name": "Fareedullah"},
    )
    assert any("3001" in c and "3004" in c for c in conflicts)
    assert any("Hamza" in c and "Fareedullah" in c for c in conflicts)


def test_a_bio_that_agrees_reports_nothing():
    assert group_profile.find_conflicts(
        {"truck_number": "3001", "driver_name": "hamza"},
        {"truck_unit_number": "3001", "full_name": "Hamza"},
    ) == []


def test_a_driver_with_no_name_on_file_is_not_a_conflict():
    assert group_profile.find_conflicts(
        {"driver_name": "Hamza"}, {"full_name": None, "truck_unit_number": None}
    ) == []


def test_a_vin_that_is_not_a_vin_is_flagged():
    conflicts = group_profile.find_conflicts({"vin": "3AKJHHDR1PSLK340"}, {})  # 16 characters
    assert conflicts and "VIN" in conflicts[0]


def test_a_real_vin_passes():
    assert group_profile.find_conflicts({"vin": "3AKJHHDR1PSLK3404"}, {}) == []


def test_a_short_phone_is_flagged():
    conflicts = group_profile.find_conflicts({"driver_phone": "8384338"}, {})
    assert conflicts and "short" in conflicts[0]


def test_a_formatted_phone_passes():
    assert group_profile.find_conflicts({"driver_phone": "410-800-3954"}, {}) == []


# ------------------------------------------------------------------
# Confirming it
# ------------------------------------------------------------------

def test_a_proposal_writes_nothing_until_it_is_confirmed(company_and_driver):
    company_id, driver_id = company_and_driver
    repository.save_group_profile_proposal(
        company_id, driver_id, -100900001,
        title="ODM 3001", description="Driver: Fareedullah",
        fields={"truck_number": "3001", "driver_name": "Fareedullah"},
    )
    assert repository.get_driver_identity(driver_id, company_id)["full_name"] is None


def test_confirming_saves_the_driver_the_truck_and_the_trailer(company_and_driver):
    company_id, driver_id = company_and_driver
    proposal = repository.save_group_profile_proposal(
        company_id, driver_id, -100900002,
        title="ODM 3004 | HAMZA TRL# A016756",
        description="Driver: HAMZA / Phone# 8384338554",
        fields={
            "truck_number": "3004",
            "trailer_number": "A016756",
            "driver_name": "HAMZA",
            "driver_phone": "8384338554",
            "vin": "3AKJHHDR1PSLK3404",
            "driver_email": "Hamzazani@hotmail.com",
        },
    )
    ok, reason = repository.apply_group_profile_proposal(proposal["id"], "telegram")
    assert (ok, reason) == (True, "ok")

    identity = repository.get_driver_identity(driver_id, company_id)
    assert identity["full_name"] == "HAMZA"
    assert identity["phone"] == "8384338554"
    assert identity["email"] == "Hamzazani@hotmail.com"
    assert identity["truck_unit_number"] == "3004"

    with get_session() as session:
        driver = session.get(models.Driver, driver_id)
        assert driver.truck.vin == "3AKJHHDR1PSLK3404"
        assert driver.truck.trailer.unit_number == "A016756"


def test_a_team_truck_keeps_both_drivers(company_and_driver):
    company_id, driver_id = company_and_driver
    proposal = repository.save_group_profile_proposal(
        company_id, driver_id, -100900003,
        title="ODM 3001", description="CO-driver:Khalid Mandozai / 619-635-1092",
        fields={
            "driver_name": "Fareedullah",
            "co_driver_name": "Khalid Mandozai",
            "co_driver_phone": "619-635-1092",
        },
    )
    repository.apply_group_profile_proposal(proposal["id"], "dashboard")
    identity = repository.get_driver_identity(driver_id, company_id)
    assert identity["co_driver_name"] == "Khalid Mandozai"
    assert identity["co_driver_phone"] == "619-635-1092"


def test_a_field_the_bio_does_not_mention_is_left_alone(company_and_driver):
    """A bio with no trailer must not wipe the trailer already on file."""
    company_id, driver_id = company_and_driver
    first = repository.save_group_profile_proposal(
        company_id, driver_id, -100900004, title="t", description="d",
        fields={"truck_number": "5000", "trailer_number": "TR-1", "driver_phone": "410-800-3954"},
    )
    repository.apply_group_profile_proposal(first["id"], "dashboard")

    second = repository.save_group_profile_proposal(
        company_id, driver_id, -100900004, title="t", description="d",
        fields={"driver_name": "Fareedullah"},
    )
    repository.apply_group_profile_proposal(second["id"], "dashboard")

    identity = repository.get_driver_identity(driver_id, company_id)
    assert identity["full_name"] == "Fareedullah"
    assert identity["phone"] == "410-800-3954"
    with get_session() as session:
        driver = session.get(models.Driver, driver_id)
        assert driver.truck.trailer.unit_number == "TR-1"


def test_confirming_twice_says_it_is_already_done(company_and_driver):
    """Both sides can confirm. The second one is told, not failed."""
    company_id, driver_id = company_and_driver
    proposal = repository.save_group_profile_proposal(
        company_id, driver_id, -100900005, title="t", description="d",
        fields={"driver_name": "Hamza"},
    )
    assert repository.apply_group_profile_proposal(proposal["id"], "telegram") == (True, "ok")
    assert repository.apply_group_profile_proposal(proposal["id"], "dashboard") == (
        False, "already_resolved",
    )


def test_a_re_read_supersedes_the_pending_one(company_and_driver):
    """An edited bio makes the earlier reading stale, not a second choice."""
    company_id, driver_id = company_and_driver
    old = repository.save_group_profile_proposal(
        company_id, driver_id, -100900006, title="t", description="old",
        fields={"driver_name": "Old Name"},
    )
    new = repository.save_group_profile_proposal(
        company_id, driver_id, -100900006, title="t", description="new",
        fields={"driver_name": "New Name"},
    )
    pending = repository.get_pending_proposal_for_group(-100900006)
    assert pending["id"] == new["id"]
    assert repository.apply_group_profile_proposal(old["id"], "telegram") == (
        False, "already_resolved",
    )


def test_a_proposal_belongs_to_its_company(company_and_driver):
    company_id, driver_id = company_and_driver
    proposal = repository.save_group_profile_proposal(
        company_id, driver_id, -100900007, title="t", description="d",
        fields={"driver_name": "Hamza"},
    )
    assert repository.apply_group_profile_proposal(
        proposal["id"], "dashboard", company_id=company_id + 999
    ) == (False, "not_found")


def test_dismissing_leaves_the_records_untouched(company_and_driver):
    company_id, driver_id = company_and_driver
    proposal = repository.save_group_profile_proposal(
        company_id, driver_id, -100900008, title="t", description="d",
        fields={"driver_name": "Hamza", "truck_number": "9999"},
    )
    assert repository.dismiss_group_profile_proposal(proposal["id"], "telegram") == (True, "ok")
    identity = repository.get_driver_identity(driver_id, company_id)
    assert identity["full_name"] is None
    assert identity["truck_unit_number"] is None
    assert repository.get_pending_proposal_for_group(-100900008) is None
