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
    assert "Welcome to Unector" in text
    assert "/dispatch" in text
    assert "/faq" in text
    assert message.reply.await_args.kwargs.get("parse_mode") == "Markdown"


@pytest.mark.asyncio
async def test_faq_replies_with_every_question():
    """Which subjects the FAQ has to cover - on this surface and on the
    site's - is held in tests/test_faq_surfaces.py, which compares the two
    against each other. This one is here because it actually runs the
    handler: it catches a reply that never gets sent, which reading the
    source cannot."""
    message = AsyncMock()
    await handle_faq(message)

    # Sent in more than one message now - it outgrew Telegram's 4096-character
    # limit, which refuses a long message rather than truncating it.
    assert message.reply.await_count >= 1
    text = "".join(call.args[0] for call in message.reply.await_args_list)
    for expected in [
        "What is Unector?",
        "How does billing work?",
        "How do I set up a truck's group?",
        "Which logo ends up on the group?",
        "How does Gmail integration work?",
        "How does GPS tracking work?",
        "What does the AI do?",
        "How many dispatchers can I have?",
    ]:
        assert expected in text
