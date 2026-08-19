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

from db.repository import get_company_credential

API_BASE = "https://api.samsara.com"


async def get_vehicle_location(company_id: int, vehicle_id: str) -> dict | None:
    """Returns {"lat": float, "lng": float, "updated_at": str} for a vehicle,
    or None if the vehicle has no recent GPS fix or the request fails."""
    api_key = get_company_credential(company_id, "samsara_api_key")
    if not api_key:
        raise NotImplementedError(
            f"No Samsara account connected for company_id={company_id}. "
            "Run samsara_setup.py to connect a Samsara API key for this company."
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"types": "gps", "vehicleIds": vehicle_id}

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(
            f"{API_BASE}/fleet/vehicles/stats", params=params, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                return None
            payload = await resp.json()

    vehicles = payload.get("data", [])
    if not vehicles:
        return None

    gps = vehicles[0].get("gps")
    if not gps:
        return None

    return {
        "lat": gps.get("latitude"),
        "lng": gps.get("longitude"),
        "updated_at": gps.get("time"),
    }
