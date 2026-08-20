"""
Tests for bot.py's /start and /faq commands - simple informational
commands that don't touch the database, so they're tested by calling the
handler directly with a mocked Message rather than running a full
Telegram update through the Dispatcher.
"""
from unittest.mock import AsyncMock

import pytest

from bot import handle_faq, handle_start


@pytest.mark.asyncio
async def test_start_replies_with_welcome_and_command_list():
    message = AsyncMock()
    await handle_start(message)

    message.reply.assert_awaited_once()
    text = message.reply.await_args.args[0]
    assert "Welcome to Freight Pilot" in text
    assert "/dispatch" in text
    assert "/faq" in text
    assert message.reply.await_args.kwargs.get("parse_mode") == "Markdown"


@pytest.mark.asyncio
async def test_faq_replies_with_all_six_questions():
    message = AsyncMock()
    await handle_faq(message)

    message.reply.assert_awaited_once()
    text = message.reply.await_args.args[0]
    for expected in [
        "What is Freight Pilot?",
        "How does billing work?",
        "How does Gmail integration work?",
        "How does GPS tracking work?",
        "What does the AI do?",
        "Can I add dispatchers?",
    ]:
        assert expected in text
