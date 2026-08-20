"""
Samsara integration. Each company connects its own Samsara account by
generating an API token in the Samsara dashboard (Settings > API Tokens)
and running samsara_setup.py, which stores it encrypted in the DB
(cred_type="samsara_api_key") - same pattern as the Gmail refresh token.

This module only does ONE thing for now: fetch a vehicle's last known GPS
location. Real-time push (webhooks) needs a public HTTPS server, which isn't
available until the bot is deployed to a VPS - so bot.py polls this
periodically instead. Swapping to webhooks later only means adding a
FastAPI endpoint and removing the polling loop; this function stays the same.
"""
import aiohttp

from config import SAMSARA_TEST_MODE
from db.repository import get_company_credential

API_BASE = "https://api.samsara.com"


async def get_vehicle_location(company_id: int, vehicle_id: str) -> dict | None:
    """Returns {"lat": float, "lng": float, "updated_at": str} for a vehicle,
    or None if the vehicle has no recent GPS fix or the request fails."""
    locations = await get_fleet_locations(company_id, [vehicle_id])
    return locations.get(vehicle_id)


async def get_fleet_locations(company_id: int, vehicle_ids: list[str]) -> dict[str, dict]:
    """Same as get_vehicle_location, but for many vehicles in ONE request -
    Samsara's stats endpoint accepts a comma-separated vehicleIds filter, so
    checking a whole fleet doesn't need one HTTP round-trip per truck. Used
    by the location monitor and the /api/monitoring dashboard.

    Returns {vehicle_id: {"lat":..., "lng":..., "updated_at":...}} - vehicles
    with no recent GPS fix are simply absent from the result."""
    if not vehicle_ids:
        return {}

    if SAMSARA_TEST_MODE:
        from services import samsara_test_mode
        return await samsara_test_mode.get_fleet_locations(vehicle_ids)

    api_key = get_company_credential(company_id, "samsara_api_key")
    if not api_key:
        raise NotImplementedError(
            f"No Samsara account connected for company_id={company_id}. "
            "Run samsara_setup.py to connect a Samsara API key for this company."
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"types": "gps", "vehicleIds": ",".join(vehicle_ids)}

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(
            f"{API_BASE}/fleet/vehicles/stats", params=params, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                return {}
            payload = await resp.json()

    result = {}
    for vehicle in payload.get("data", []):
        vid, gps = vehicle.get("id"), vehicle.get("gps")
        if not vid or not gps:
            continue
        result[vid] = {
            "lat": gps.get("latitude"),
            "lng": gps.get("longitude"),
            "updated_at": gps.get("time"),
        }
    return result
