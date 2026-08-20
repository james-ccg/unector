"""
Tests for bot.py's /detention command: a manual trigger (not GPS/time-based
- see bot.py's comment above handle_detention for why) that emails the
broker a detention/layover request using the terms already extracted from
the RC, and guards against sending it twice for the same load.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot


def _make_driver(company_id=1, dispatcher_username=None):
    driver = MagicMock()
    driver.id = 10
    driver.company_id = company_id
    driver.dispatcher_username = dispatcher_username
    return driver


def _make_load(raw_extracted_json=None, detention_requested_at=None, company_id=1):
    load = MagicMock()
    load.id = 42
    load.company_id = company_id
    load.load_id = "11111"
    load.raw_extracted_json = raw_extracted_json
    load.detention_requested_at = detention_requested_at
    return load


def _make_message():
    message = MagicMock()
    message.chat.type = "private"  # skips the update_group_title DB call
    message.chat.id = 555
    message.reply = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_no_driver_linked_shows_friendly_message():
    message = _make_message()

    with patch.object(bot, "get_driver_by_group", return_value=None):
        await bot.handle_detention(message)

    message.reply.assert_awaited_once()
    assert "isn't linked" in message.reply.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_no_active_load_tells_user_to_dispatch_first():
    message = _make_message()
    driver = _make_driver()

    with patch.object(bot, "get_driver_by_group", return_value=driver), \
         patch.object(bot, "get_load_by_group", return_value=None):
        await bot.handle_detention(message)

    assert "/dispatch" in message.reply.await_args.args[0]


@pytest.mark.asyncio
async def test_already_requested_is_not_sent_twice():
    message = _make_message()
    driver = _make_driver()
    when = datetime(2026, 1, 15, 10, 30)
    load = _make_load(raw_extracted_json={"detention_terms": "2 hrs free"}, detention_requested_at=when)

    with patch.object(bot, "get_driver_by_group", return_value=driver), \
         patch.object(bot, "get_load_by_group", return_value=load), \
         patch.object(bot.email_service, "send_email") as send_email:
        await bot.handle_detention(message)

    send_email.assert_not_called()
    assert "already" in message.reply.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_no_detention_terms_on_rc_shows_friendly_message():
    message = _make_message()
    driver = _make_driver()
    load = _make_load(raw_extracted_json={"broker_contact_email": "broker@example.com"})

    with patch.object(bot, "get_driver_by_group", return_value=driver), \
         patch.object(bot, "get_load_by_group", return_value=load), \
         patch.object(bot.email_service, "send_email") as send_email:
        await bot.handle_detention(message)

    send_email.assert_not_called()
    assert "no detention" in message.reply.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_no_broker_email_shows_friendly_message():
    message = _make_message()
    driver = _make_driver()
    load = _make_load(raw_extracted_json={"detention_terms": "2 hrs free, $50/hr after"})

    with patch.object(bot, "get_driver_by_group", return_value=driver), \
         patch.object(bot, "get_load_by_group", return_value=load), \
         patch.object(bot.email_service, "send_email") as send_email:
        await bot.handle_detention(message)

    send_email.assert_not_called()
    assert "manually" in message.reply.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_happy_path_sends_email_marks_load_and_tags_dispatcher():
    message = _make_message()
    driver = _make_driver(dispatcher_username="janedispatch")
    load = _make_load(raw_extracted_json={
        "detention_terms": "2 hrs free, $50/hr after",
        "broker_contact_email": "broker@example.com",
    })

    with patch.object(bot, "get_driver_by_group", return_value=driver), \
         patch.object(bot, "get_load_by_group", return_value=load), \
         patch.object(bot.email_service, "send_email") as send_email, \
         patch.object(bot, "mark_detention_requested") as mark_requested:
        await bot.handle_detention(message)

    send_email.assert_called_once()
    assert send_email.call_args.kwargs["to_address"] == "broker@example.com"
    assert "2 hrs free, $50/hr after" in send_email.call_args.kwargs["body"]
    assert send_email.call_args.kwargs["company_id"] == 1

    mark_requested.assert_called_once_with(42)

    reply_text = message.reply.await_args.args[0]
    assert "broker@example.com" in reply_text
    assert "@janedispatch" in reply_text


@pytest.mark.asyncio
async def test_email_not_connected_shows_setup_message_and_does_not_mark_sent():
    message = _make_message()
    driver = _make_driver()
    load = _make_load(raw_extracted_json={
        "detention_terms": "2 hrs free",
        "broker_contact_email": "broker@example.com",
    })

    with patch.object(bot, "get_driver_by_group", return_value=driver), \
         patch.object(bot, "get_load_by_group", return_value=load), \
         patch.object(bot.email_service, "send_email", side_effect=NotImplementedError("Gmail not connected")), \
         patch.object(bot, "mark_detention_requested") as mark_requested:
        await bot.handle_detention(message)

    mark_requested.assert_not_called()
    assert "isn't connected" in message.reply.await_args.args[0].lower()
