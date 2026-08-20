"""
Tests for the customizable per-scenario location alert rules: a company can
configure its own distance thresholds + messages for "near pickup" /
"near delivery" (LocationAlertRule), and a company with none configured
keeps getting the bot's original single hardcoded alert - see
bot.py's _fire_scenario_alerts/_render_alert_message/_check_all_loads_once.
"""
from unittest.mock import AsyncMock, patch

import pytest

import bot
from db.repository import MonitoredLoad


def _make_load(**overrides) -> MonitoredLoad:
    defaults = dict(
        id=42,
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


def _rule(id, distance_miles, message_template=None):
    return {"id": id, "scenario": "pu_near", "distance_miles": distance_miles,
            "message_template": message_template, "enabled": True}


# ------------------------------------------------------------------
# _render_alert_message
# ------------------------------------------------------------------
def test_render_default_message_fills_placeholders():
    text = bot._render_alert_message(None, "pu_near", 12.4, "11111")
    assert "12 miles from pickup" in text
    assert "#11111" in text


def test_render_custom_template_fills_placeholders():
    text = bot._render_alert_message("{miles}mi out from load #{load_id}!", "del_near", 4.6, "22222")
    assert text == "5mi out from load #22222!"


def test_render_malformed_template_falls_back_to_default():
    text = bot._render_alert_message("Bad template {oops}", "pu_near", 10.0, "33333")
    assert "10 miles from pickup" in text


# ------------------------------------------------------------------
# _fire_scenario_alerts - default (no custom rules) fallback path
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_default_fallback_fires_once_and_marks_notified():
    load = _make_load(notified_pu_near=False)

    with patch.object(bot, "SAMSARA_NEARBY_MILES", 5.0), \
         patch.object(bot.bot, "send_message", new_callable=AsyncMock) as send, \
         patch.object(bot, "mark_notified") as mark_notified:
        await bot._fire_scenario_alerts(load, "pu_near", 3.0, [])

    send.assert_awaited_once()
    assert send.await_args.args[0] == 555
    mark_notified.assert_called_once_with(42, "pu")


@pytest.mark.asyncio
async def test_default_fallback_skips_when_already_notified():
    load = _make_load(notified_pu_near=True)

    with patch.object(bot, "SAMSARA_NEARBY_MILES", 5.0), \
         patch.object(bot.bot, "send_message", new_callable=AsyncMock) as send, \
         patch.object(bot, "mark_notified") as mark_notified:
        await bot._fire_scenario_alerts(load, "pu_near", 3.0, [])

    send.assert_not_awaited()
    mark_notified.assert_not_called()


@pytest.mark.asyncio
async def test_default_fallback_skips_when_too_far():
    load = _make_load(notified_pu_near=False)

    with patch.object(bot, "SAMSARA_NEARBY_MILES", 5.0), \
         patch.object(bot.bot, "send_message", new_callable=AsyncMock) as send:
        await bot._fire_scenario_alerts(load, "pu_near", 8.0, [])

    send.assert_not_awaited()


# ------------------------------------------------------------------
# _fire_scenario_alerts - custom rules path
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_custom_rules_only_fires_thresholds_within_range():
    load = _make_load(alerted_rule_ids=[])
    rules = [_rule(1, 50.0), _rule(2, 5.0)]  # furthest-out first, matching get_enabled_alert_rules' ordering

    with patch.object(bot.bot, "send_message", new_callable=AsyncMock) as send, \
         patch.object(bot, "mark_alert_rule_fired") as mark_fired:
        await bot._fire_scenario_alerts(load, "pu_near", 8.0, rules)

    # Only the 50mi rule qualifies at 8 miles out - the 5mi one hasn't been reached yet.
    send.assert_awaited_once()
    mark_fired.assert_called_once_with(42, 1)
    assert load.alerted_rule_ids == [1]


@pytest.mark.asyncio
async def test_custom_rule_does_not_refire_once_marked():
    load = _make_load(alerted_rule_ids=[1])
    rules = [_rule(1, 50.0), _rule(2, 5.0)]

    with patch.object(bot.bot, "send_message", new_callable=AsyncMock) as send, \
         patch.object(bot, "mark_alert_rule_fired") as mark_fired:
        await bot._fire_scenario_alerts(load, "pu_near", 3.0, rules)

    # Rule 1 already fired earlier; only rule 2 (5mi) should fire now that we're at 3 miles.
    send.assert_awaited_once()
    mark_fired.assert_called_once_with(42, 2)
    assert load.alerted_rule_ids == [1, 2]


@pytest.mark.asyncio
async def test_custom_rules_send_the_configured_message():
    load = _make_load()
    rules = [_rule(9, 25.0, message_template="Heads up - {miles}mi from pickup on #{load_id}")]

    with patch.object(bot.bot, "send_message", new_callable=AsyncMock) as send, \
         patch.object(bot, "mark_alert_rule_fired"):
        await bot._fire_scenario_alerts(load, "pu_near", 20.0, rules)

    assert send.await_args.args[1] == "Heads up - 20mi from pickup on #11111"


# ------------------------------------------------------------------
# _check_all_loads_once - Samsara calls are batched per company
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_check_all_loads_batches_samsara_per_company_not_per_load():
    load_a1 = _make_load(id=1, company_id=1, samsara_vehicle_id="veh-a1", telegram_group_id=101)
    load_a2 = _make_load(id=2, company_id=1, samsara_vehicle_id="veh-a2", telegram_group_id=102)
    load_b1 = _make_load(id=3, company_id=2, samsara_vehicle_id="veh-b1", telegram_group_id=201)

    locations = {
        "veh-a1": {"lat": 40.0, "lng": -75.0},
        "veh-a2": {"lat": 40.0, "lng": -75.0},
        "veh-b1": {"lat": 40.0, "lng": -75.0},
    }

    with patch.object(bot, "get_active_loads_for_monitoring", return_value=[load_a1, load_a2, load_b1]), \
         patch.object(bot, "get_enabled_alert_rules", return_value=[]), \
         patch.object(bot.samsara_service, "get_fleet_locations", new_callable=AsyncMock) as get_fleet, \
         patch.object(bot, "_fire_scenario_alerts", new_callable=AsyncMock) as fire_alerts:
        get_fleet.return_value = locations
        await bot._check_all_loads_once()

    # One Samsara call per company (2 companies), not one per load (3 loads).
    assert get_fleet.await_count == 2
    called_company_ids = {call.args[0] for call in get_fleet.await_args_list}
    assert called_company_ids == {1, 2}
    assert fire_alerts.await_count == 3


@pytest.mark.asyncio
async def test_check_all_loads_skips_company_without_samsara_connected():
    load = _make_load()

    with patch.object(bot, "get_active_loads_for_monitoring", return_value=[load]), \
         patch.object(bot.samsara_service, "get_fleet_locations", side_effect=NotImplementedError("no key")), \
         patch.object(bot, "_fire_scenario_alerts", new_callable=AsyncMock) as fire_alerts:
        await bot._check_all_loads_once()

    fire_alerts.assert_not_awaited()
