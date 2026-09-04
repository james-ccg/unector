"""
Two small, dependency-light helpers used by the Samsara location monitor:
1. geocode_address() - turns a text address (as extracted from the RC) into
   (latitude, longitude), using OpenStreetMap's free Nominatim service.
2. haversine_miles() - great-circle distance between two lat/lng points,
   in miles. Pure math, no external service needed.
"""
import math

import aiohttp

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim's usage policy requires a descriptive User-Agent identifying the
# application - requests without one get blocked. Also: max ~1 request/second,
# which is fine here since we only geocode once per load (at /dispatch time).
HEADERS = {"User-Agent": "UnectorBot/1.0 (dispatch automation)"}


async def geocode_address(address_text: str) -> tuple[float, float] | None:
    """Looks up a free-text address and returns (lat, lng), or None if it
    couldn't be found. Takes just the last line or two of a multi-line address
    block (city/state/zip) since that's what geocodes most reliably - full
    company names in the first line often confuse the lookup."""
    if not address_text:
        return None

    # Use the last 1-2 lines (city, state, zip) - most reliable for geocoding.
    lines = [l.strip() for l in address_text.strip().splitlines() if l.strip()]
    query = ", ".join(lines[-2:]) if len(lines) >= 2 else (lines[-1] if lines else "")
    if not query:
        return None

    params = {"q": query, "format": "json", "limit": 1}

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(NOMINATIM_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            results = await resp.json()

    if not results:
        return None

    return float(results[0]["lat"]), float(results[0]["lon"])


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points, in miles."""
    R = 3958.8  # Earth's radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
