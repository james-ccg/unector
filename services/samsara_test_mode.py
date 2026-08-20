"""
Test-mode stand-in for services/samsara_service.py's real Samsara API calls.
Active when SAMSARA_TEST_MODE=true in .env - lets the whole location-alert
pipeline (bot.py's monitor loop, distance thresholds, custom messages,
per-company batching) be exercised end to end with no Samsara account and
no real trucks.

How it works: for each vehicle_id asked about, looks up that driver's
currently active load and simulates a truck driving in a straight line
toward whichever leg is current (pickup, then delivery) - starting
SAMSARA_TEST_START_MILES out and closing the distance at
SAMSARA_TEST_SPEED_MPH (defaults to a fast 600mph so a multi-hour trip
plays out in a few real minutes instead of literal hours).

Setup: set SAMSARA_TEST_MODE=true in .env and restart the bot - every
company shows as "Samsara connected" while this is on, no real API key
needed. Give your test driver ANY samsara_vehicle_id via the bot's
/setvehicle command, then /dispatch a load with a real, geocodable
address and watch your configured alert rules fire in the Telegram group
as the simulated distance counts down.
"""
import time

from config import SAMSARA_TEST_START_MILES, SAMSARA_TEST_SPEED_MPH
from db.repository import get_active_loads_for_monitoring

# vehicle_id -> (load_id, time.monotonic() when this load's approach started).
# In-memory only, by design - a bot restart or a fresh /dispatch both
# naturally restart the simulated approach from SAMSARA_TEST_START_MILES out.
_sim_started_at: dict[str, tuple[int, float]] = {}


def _simulated_point(target_lat: float, target_lng: float, distance_miles: float) -> dict:
    """A synthetic GPS point ~distance_miles due south of the target. Not
    meant to look like a real road - just accurate enough (~0.1%) that
    geo_utils.haversine_miles measures back out to the intended distance,
    which is all the alert-threshold math actually cares about."""
    lat = target_lat - (distance_miles / 69.0)  # ~69 miles per degree of latitude
    return {"lat": lat, "lng": target_lng, "updated_at": None}


async def get_fleet_locations(vehicle_ids: list[str]) -> dict[str, dict]:
    if not vehicle_ids:
        return {}

    wanted = set(vehicle_ids)
    loads_by_vehicle = {
        ld.samsara_vehicle_id: ld
        for ld in get_active_loads_for_monitoring()
        if ld.samsara_vehicle_id in wanted
    }

    now = time.monotonic()
    result: dict[str, dict] = {}

    for vehicle_id in vehicle_ids:
        load = loads_by_vehicle.get(vehicle_id)
        if not load:
            continue

        if load.status == "dispatched" and load.pu_lat is not None:
            target_lat, target_lng = load.pu_lat, load.pu_lng
        elif load.status in ("loaded", "bol_ok") and load.del_lat is not None:
            target_lat, target_lng = load.del_lat, load.del_lng
        else:
            continue

        state = _sim_started_at.get(vehicle_id)
        if not state or state[0] != load.id:
            state = (load.id, now)
            _sim_started_at[vehicle_id] = state
        _, started_at = state

        elapsed_hours = (now - started_at) / 3600.0
        distance = max(0.0, SAMSARA_TEST_START_MILES - SAMSARA_TEST_SPEED_MPH * elapsed_hours)
        result[vehicle_id] = _simulated_point(target_lat, target_lng, distance)

    return result
