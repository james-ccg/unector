"""
Tests for services/samsara_test_mode.py - the SAMSARA_TEST_MODE simulator
that stands in for the real Samsara API so the location-alert pipeline can
be tested with no Samsara account and no real trucks (see the module's
docstring for the full setup). Verifies the simulated truck starts at the
configured distance, closes in on the right target for the load's current
status, resets on a new load, and never reports a negative distance.
"""
from unittest.mock import patch

import pytest

from db.repository import MonitoredLoad
from services import geo_utils, samsara_test_mode


def _make_load(**overrides) -> MonitoredLoad:
    defaults = dict(
        id=1,
        company_id=1,
        load_id="11111",
        status="dispatched",
        telegram_group_id=555,
        samsara_vehicle_id="veh-1",
        pu_lat=40.0, pu_lng=-75.0,
        del_lat=41.0, del_lng=-76.0,
        notified_pu_near=False,
        notified_del_near=False,
        alerted_rule_ids=[],
    )
    defaults.update(overrides)
    return MonitoredLoad(**defaults)


@pytest.fixture(autouse=True)
def _clear_sim_state():
    samsara_test_mode._sim_started_at.clear()
    yield
    samsara_test_mode._sim_started_at.clear()


@pytest.mark.asyncio
async def test_no_vehicle_ids_returns_empty():
    assert await samsara_test_mode.get_fleet_locations([]) == {}


@pytest.mark.asyncio
async def test_vehicle_with_no_active_load_is_absent():
    with patch.object(samsara_test_mode, "get_active_loads_for_monitoring", return_value=[]):
        result = await samsara_test_mode.get_fleet_locations(["veh-unknown"])
    assert result == {}


@pytest.mark.asyncio
async def test_starts_at_configured_distance_from_pickup():
    load = _make_load(status="dispatched")

    with patch.object(samsara_test_mode, "get_active_loads_for_monitoring", return_value=[load]), \
         patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_START_MILES", 60.0):
        result = await samsara_test_mode.get_fleet_locations(["veh-1"])

    point = result["veh-1"]
    distance = geo_utils.haversine_miles(point["lat"], point["lng"], load.pu_lat, load.pu_lng)
    assert distance == pytest.approx(60.0, abs=0.5)


@pytest.mark.asyncio
async def test_distance_closes_in_over_simulated_time():
    load = _make_load(status="dispatched")

    with patch.object(samsara_test_mode, "get_active_loads_for_monitoring", return_value=[load]), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_START_MILES", 60.0), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_SPEED_MPH", 600.0):
        with patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0):
            first = await samsara_test_mode.get_fleet_locations(["veh-1"])
        # 6 simulated minutes later at 600mph -> 60 miles closer.
        with patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0 + 6 * 60):
            second = await samsara_test_mode.get_fleet_locations(["veh-1"])

    d1 = geo_utils.haversine_miles(first["veh-1"]["lat"], first["veh-1"]["lng"], load.pu_lat, load.pu_lng)
    d2 = geo_utils.haversine_miles(second["veh-1"]["lat"], second["veh-1"]["lng"], load.pu_lat, load.pu_lng)
    assert d1 == pytest.approx(60.0, abs=0.5)
    assert d2 == pytest.approx(0.0, abs=0.5)


@pytest.mark.asyncio
async def test_distance_never_goes_negative():
    load = _make_load(status="dispatched")

    with patch.object(samsara_test_mode, "get_active_loads_for_monitoring", return_value=[load]), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_START_MILES", 60.0), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_SPEED_MPH", 600.0):
        with patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0):
            await samsara_test_mode.get_fleet_locations(["veh-1"])
        # Way past arrival.
        with patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0 + 100 * 3600):
            result = await samsara_test_mode.get_fleet_locations(["veh-1"])

    distance = geo_utils.haversine_miles(result["veh-1"]["lat"], result["veh-1"]["lng"], load.pu_lat, load.pu_lng)
    assert distance == pytest.approx(0.0, abs=0.5)


@pytest.mark.asyncio
async def test_loaded_status_targets_delivery_not_pickup():
    # Pickup and delivery are far enough apart that "close to delivery" and
    # "close to pickup" can't be mixed up by coincidence.
    load = _make_load(status="loaded", pu_lat=40.0, pu_lng=-75.0, del_lat=48.0, del_lng=-95.0)

    with patch.object(samsara_test_mode, "get_active_loads_for_monitoring", return_value=[load]), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_START_MILES", 60.0), \
         patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0):
        result = await samsara_test_mode.get_fleet_locations(["veh-1"])

    point = result["veh-1"]
    dist_to_del = geo_utils.haversine_miles(point["lat"], point["lng"], load.del_lat, load.del_lng)
    dist_to_pu = geo_utils.haversine_miles(point["lat"], point["lng"], load.pu_lat, load.pu_lng)
    assert dist_to_del == pytest.approx(60.0, abs=0.5)
    assert dist_to_pu > dist_to_del


@pytest.mark.asyncio
async def test_new_load_id_resets_the_approach():
    load_a = _make_load(id=1, load_id="11111", status="dispatched")

    with patch.object(samsara_test_mode, "get_active_loads_for_monitoring", return_value=[load_a]), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_START_MILES", 60.0), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_SPEED_MPH", 600.0):
        with patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0):
            await samsara_test_mode.get_fleet_locations(["veh-1"])
        # Nearly arrived on load A.
        with patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0 + 6 * 60):
            almost_arrived = await samsara_test_mode.get_fleet_locations(["veh-1"])

    d_almost = geo_utils.haversine_miles(
        almost_arrived["veh-1"]["lat"], almost_arrived["veh-1"]["lng"], load_a.pu_lat, load_a.pu_lng
    )
    assert d_almost == pytest.approx(0.0, abs=0.5)

    # A new load (different id) on the same vehicle should restart the approach.
    load_b = _make_load(id=2, load_id="22222", status="dispatched", pu_lat=50.0, pu_lng=-80.0)
    with patch.object(samsara_test_mode, "get_active_loads_for_monitoring", return_value=[load_b]), \
         patch.object(samsara_test_mode, "SAMSARA_TEST_START_MILES", 60.0), \
         patch.object(samsara_test_mode.time, "monotonic", return_value=1000.0 + 6 * 60 + 1):
        restarted = await samsara_test_mode.get_fleet_locations(["veh-1"])

    d_restarted = geo_utils.haversine_miles(
        restarted["veh-1"]["lat"], restarted["veh-1"]["lng"], load_b.pu_lat, load_b.pu_lng
    )
    assert d_restarted == pytest.approx(60.0, abs=0.5)
