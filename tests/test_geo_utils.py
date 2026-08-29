"""
Tests for services/geo_utils.py - the distance math the location monitor
uses to decide when a driver is "near" a pickup/delivery, and the
address-narrowing geocode_address does before hitting Nominatim.

The proximity alerts in bot.py compare haversine_miles() against a
company's configured threshold, so an error here doesn't crash anything -
it silently fires alerts at the wrong distance, or never fires them.
"""
import math
from unittest.mock import MagicMock, patch

import pytest

from services import geo_utils


class TestHaversineMiles:
    # Reference distances, great-circle, accurate to well under the 1-mile
    # precision any alert threshold cares about.
    CHICAGO = (41.8781, -87.6298)
    DALLAS = (32.7767, -96.7970)
    NEW_YORK = (40.7128, -74.0060)
    LOS_ANGELES = (34.0522, -118.2437)

    def test_known_distance_chicago_to_dallas(self):
        miles = geo_utils.haversine_miles(*self.CHICAGO, *self.DALLAS)
        assert miles == pytest.approx(802, abs=5)

    def test_known_distance_coast_to_coast(self):
        miles = geo_utils.haversine_miles(*self.NEW_YORK, *self.LOS_ANGELES)
        assert miles == pytest.approx(2451, abs=10)

    def test_identical_points_are_zero_miles_apart(self):
        assert geo_utils.haversine_miles(*self.CHICAGO, *self.CHICAGO) == pytest.approx(0, abs=1e-9)

    def test_distance_is_symmetric(self):
        there = geo_utils.haversine_miles(*self.CHICAGO, *self.DALLAS)
        back = geo_utils.haversine_miles(*self.DALLAS, *self.CHICAGO)
        assert there == pytest.approx(back)

    def test_short_distance_is_accurate_enough_for_a_proximity_alert(self):
        """The tightest built-in alert fires around 5 miles out, so the
        sub-10-mile range is the one that actually has to be right."""
        # ~1 degree of longitude at Chicago's latitude is ~51.5 miles; a
        # tenth of that is a realistic "almost at the dock" distance.
        lat, lng = self.CHICAGO
        miles = geo_utils.haversine_miles(lat, lng, lat, lng + 0.1)
        assert miles == pytest.approx(5.15, abs=0.1)

    def test_crossing_the_antimeridian_is_not_treated_as_half_the_world(self):
        """Longitude wraps at +/-180; a naive implementation reports these
        two nearby points as most of the way around the globe instead."""
        miles = geo_utils.haversine_miles(0.0, 179.9, 0.0, -179.9)
        assert miles == pytest.approx(13.8, abs=1)

    def test_equator_quarter_circumference(self):
        """A quarter turn around the equator - a whole-globe sanity check
        that the earth radius constant and the formula agree."""
        miles = geo_utils.haversine_miles(0.0, 0.0, 0.0, 90.0)
        assert miles == pytest.approx(math.pi / 2 * 3958.8, rel=1e-6)


def _mock_nominatim(payload, status=200):
    """Stands in for the aiohttp request geocode_address makes, capturing
    the params it sends so the query-building can be asserted on."""
    captured = {}

    response = MagicMock()
    response.status = status

    async def json():
        return payload

    response.json = json
    response.__aenter__ = lambda self_: _async_return(response)
    response.__aexit__ = lambda self_, *a: _async_return(None)

    def get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return response

    session = MagicMock()
    session.get = get
    session.__aenter__ = lambda self_: _async_return(session)
    session.__aexit__ = lambda self_, *a: _async_return(None)

    return session, captured


def _async_return(value):
    async def _coro():
        return value
    return _coro()


class TestGeocodeAddress:
    """geocode_address narrows a multi-line RC address down to the part that
    actually geocodes well before sending it. Getting that wrong doesn't
    error - it just returns coordinates for the wrong place, or none at
    all, which silently disables that load's proximity alerts."""

    @pytest.mark.asyncio
    async def test_sends_only_the_last_two_lines(self):
        session, captured = _mock_nominatim([{"lat": "41.8781", "lon": "-87.6298"}])
        with patch("aiohttp.ClientSession", return_value=session):
            result = await geo_utils.geocode_address(
                "ACME Foods Distribution\n1200 W Industrial Dr\nChicago, IL 60601"
            )

        # The company name is deliberately dropped - it confuses the lookup.
        assert captured["params"]["q"] == "1200 W Industrial Dr, Chicago, IL 60601"
        assert result == (41.8781, -87.6298)

    @pytest.mark.asyncio
    async def test_single_line_address_is_sent_as_is(self):
        session, captured = _mock_nominatim([{"lat": "32.7767", "lon": "-96.7970"}])
        with patch("aiohttp.ClientSession", return_value=session):
            await geo_utils.geocode_address("Dallas, TX 75201")

        assert captured["params"]["q"] == "Dallas, TX 75201"

    @pytest.mark.asyncio
    async def test_blank_lines_are_ignored_when_picking_the_last_two(self):
        session, captured = _mock_nominatim([{"lat": "1", "lon": "2"}])
        with patch("aiohttp.ClientSession", return_value=session):
            await geo_utils.geocode_address("ACME\n\n  \n500 Main St\n\nAustin, TX 78701\n\n")

        assert captured["params"]["q"] == "500 Main St, Austin, TX 78701"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("address", ["", "   ", "\n\n", None])
    async def test_empty_address_returns_none_without_calling_out(self, address):
        with patch("aiohttp.ClientSession") as session_factory:
            assert await geo_utils.geocode_address(address) is None
        session_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_results_returns_none(self):
        session, _ = _mock_nominatim([])
        with patch("aiohttp.ClientSession", return_value=session):
            assert await geo_utils.geocode_address("Nowhere, XX 00000") is None

    @pytest.mark.asyncio
    async def test_non_200_response_returns_none_rather_than_raising(self):
        """Nominatim rate-limits and occasionally 503s. A failed geocode has
        to degrade to "no coordinates for this load", not take /dispatch down."""
        session, _ = _mock_nominatim([], status=429)
        with patch("aiohttp.ClientSession", return_value=session):
            assert await geo_utils.geocode_address("Chicago, IL") is None

    @pytest.mark.asyncio
    async def test_coordinates_are_returned_as_floats(self):
        """Nominatim returns them as strings; the callers do arithmetic."""
        session, _ = _mock_nominatim([{"lat": "41.8781", "lon": "-87.6298"}])
        with patch("aiohttp.ClientSession", return_value=session):
            lat, lng = await geo_utils.geocode_address("Chicago, IL")

        assert isinstance(lat, float) and isinstance(lng, float)
