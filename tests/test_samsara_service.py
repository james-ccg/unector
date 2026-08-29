"""
Tests for services/samsara_service.py - the batched GPS fetch that feeds
both the Monitoring page and bot.py's proximity-alert loop.

The real API is mocked out here; what matters is the request this builds
(one batched call, not one per truck) and how it treats a response, since a
vehicle with no GPS fix must simply be absent rather than crash the fleet
view or the alert loop.
"""
from unittest.mock import MagicMock, patch

import pytest

from services import samsara_service


def _mock_session(payload, status=200):
    """Stands in for the aiohttp session, capturing the outgoing params."""
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

    def factory(*args, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return session

    return factory, captured


def _async_return(value):
    async def _coro():
        return value
    return _coro()


VEHICLE_PAYLOAD = {
    "data": [
        {"id": "v1", "gps": {"latitude": 41.8781, "longitude": -87.6298, "time": "2026-08-29T12:00:00Z"}},
        {"id": "v2", "gps": {"latitude": 32.7767, "longitude": -96.7970, "time": "2026-08-29T12:01:00Z"}},
    ]
}


@pytest.fixture(autouse=True)
def _live_mode(monkeypatch):
    """These tests exercise the real API path, so make sure the test-mode
    simulator isn't what answers - it's a separate module with its own tests."""
    monkeypatch.setattr(samsara_service, "SAMSARA_TEST_MODE", False)


class TestGetFleetLocations:
    @pytest.mark.asyncio
    async def test_returns_a_map_keyed_by_vehicle_id(self):
        factory, _ = _mock_session(VEHICLE_PAYLOAD)
        with patch.object(samsara_service, "get_company_credential", return_value="key"), \
             patch("aiohttp.ClientSession", factory):
            result = await samsara_service.get_fleet_locations(1, ["v1", "v2"])

        assert result == {
            "v1": {"lat": 41.8781, "lng": -87.6298, "updated_at": "2026-08-29T12:00:00Z"},
            "v2": {"lat": 32.7767, "lng": -96.7970, "updated_at": "2026-08-29T12:01:00Z"},
        }

    @pytest.mark.asyncio
    async def test_asks_for_every_vehicle_in_one_request(self):
        """One call for the whole fleet, not one per truck - the monitor
        loop runs this on a timer for every company."""
        factory, captured = _mock_session(VEHICLE_PAYLOAD)
        with patch.object(samsara_service, "get_company_credential", return_value="key"), \
             patch("aiohttp.ClientSession", factory):
            await samsara_service.get_fleet_locations(1, ["v1", "v2", "v3"])

        assert captured["params"]["vehicleIds"] == "v1,v2,v3"
        assert captured["params"]["types"] == "gps"

    @pytest.mark.asyncio
    async def test_sends_the_companys_own_key_as_a_bearer_token(self):
        factory, captured = _mock_session(VEHICLE_PAYLOAD)
        with patch.object(samsara_service, "get_company_credential", return_value="samsara_api_abc"), \
             patch("aiohttp.ClientSession", factory):
            await samsara_service.get_fleet_locations(1, ["v1"])

        assert captured["headers"]["Authorization"] == "Bearer samsara_api_abc"

    @pytest.mark.asyncio
    async def test_empty_vehicle_list_short_circuits_without_calling_out(self):
        with patch.object(samsara_service, "get_company_credential") as cred, \
             patch("aiohttp.ClientSession") as session:
            assert await samsara_service.get_fleet_locations(1, []) == {}

        cred.assert_not_called()
        session.assert_not_called()

    @pytest.mark.asyncio
    async def test_vehicle_without_a_gps_fix_is_omitted(self):
        """A parked truck with a stale/absent fix must drop out of the
        result, not appear at (0, 0) in the Gulf of Guinea."""
        payload = {"data": [
            {"id": "v1", "gps": {"latitude": 1.0, "longitude": 2.0, "time": "t"}},
            {"id": "v2"},
            {"id": "v3", "gps": None},
        ]}
        factory, _ = _mock_session(payload)
        with patch.object(samsara_service, "get_company_credential", return_value="key"), \
             patch("aiohttp.ClientSession", factory):
            result = await samsara_service.get_fleet_locations(1, ["v1", "v2", "v3"])

        assert list(result) == ["v1"]

    @pytest.mark.asyncio
    async def test_non_200_response_returns_empty_rather_than_raising(self):
        """miniapp/api.py's monitoring endpoint degrades to "no pins" on a
        Samsara outage; that depends on this not throwing."""
        factory, _ = _mock_session({}, status=503)
        with patch.object(samsara_service, "get_company_credential", return_value="key"), \
             patch("aiohttp.ClientSession", factory):
            assert await samsara_service.get_fleet_locations(1, ["v1"]) == {}

    @pytest.mark.asyncio
    async def test_missing_data_key_is_handled(self):
        factory, _ = _mock_session({})
        with patch.object(samsara_service, "get_company_credential", return_value="key"), \
             patch("aiohttp.ClientSession", factory):
            assert await samsara_service.get_fleet_locations(1, ["v1"]) == {}

    @pytest.mark.asyncio
    async def test_company_with_no_samsara_key_raises_not_implemented(self):
        """Distinct from an outage: this company never connected Samsara.
        Callers catch NotImplementedError specifically to tell them so."""
        with patch.object(samsara_service, "get_company_credential", return_value=None):
            with pytest.raises(NotImplementedError, match="No Samsara account connected"):
                await samsara_service.get_fleet_locations(1, ["v1"])

    @pytest.mark.asyncio
    async def test_test_mode_bypasses_the_real_api_entirely(self, monkeypatch):
        monkeypatch.setattr(samsara_service, "SAMSARA_TEST_MODE", True)

        async def fake(company_id, vehicle_ids):
            return {"v1": {"lat": 1.0, "lng": 2.0, "updated_at": "simulated"}}

        with patch("services.samsara_test_mode.get_fleet_locations", fake), \
             patch.object(samsara_service, "get_company_credential") as cred:
            result = await samsara_service.get_fleet_locations(1, ["v1"])

        assert result["v1"]["updated_at"] == "simulated"
        # No API key is needed while simulating.
        cred.assert_not_called()


class TestGetVehicleLocation:
    @pytest.mark.asyncio
    async def test_returns_just_that_vehicles_entry(self):
        factory, _ = _mock_session(VEHICLE_PAYLOAD)
        with patch.object(samsara_service, "get_company_credential", return_value="key"), \
             patch("aiohttp.ClientSession", factory):
            result = await samsara_service.get_vehicle_location(1, "v2")

        assert result == {"lat": 32.7767, "lng": -96.7970, "updated_at": "2026-08-29T12:01:00Z"}

    @pytest.mark.asyncio
    async def test_returns_none_when_that_vehicle_has_no_fix(self):
        factory, _ = _mock_session({"data": [{"id": "v1", "gps": None}]})
        with patch.object(samsara_service, "get_company_credential", return_value="key"), \
             patch("aiohttp.ClientSession", factory):
            assert await samsara_service.get_vehicle_location(1, "v1") is None
