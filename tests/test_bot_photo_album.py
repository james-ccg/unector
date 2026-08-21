"""
Tests for bot.py's photo-album debounce - specifically the straggler case:
a photo for an album that arrives after the rest of that album's debounce
already fired and got processed. Without _recently_flushed_groups, that
photo would silently start a brand-new one-photo group under the same
media_group_id (which almost never carries the caption, since Telegram
puts it on the first photo), and get dropped with no trace once its own
debounce finds no command. See handle_photo_message/_flush_photo_group/
_expire_recently_flushed_group in bot.py.
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot


def _make_photo_message(media_group_id="group-1"):
    message = MagicMock()
    message.media_group_id = media_group_id
    message.photo = [MagicMock(file_id="file-1")]
    message.chat.type = "supergroup"
    message.chat.id = -100123
    message.chat.title = "Test Group"
    message.reply = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_straggler_photo_after_group_already_flushed_gets_warned_not_dropped():
    group_id = "straggler-test-group"
    bot._recently_flushed_groups[group_id] = time.monotonic()  # simulates "just flushed"
    message = _make_photo_message(media_group_id=group_id)

    try:
        with patch.object(bot, "_process_photo_group", new_callable=AsyncMock) as process:
            await bot.handle_photo_message(message)

        process.assert_not_awaited()
        message.reply.assert_awaited_once()
        assert "already processed" in message.reply.await_args.args[0].lower()
        # The straggler must not have started a new pending group either.
        assert group_id not in bot._pending_photo_groups
    finally:
        bot._recently_flushed_groups.pop(group_id, None)
        bot._pending_photo_groups.pop(group_id, None)


@pytest.mark.asyncio
async def test_straggler_warning_expires_after_the_grace_window():
    """Once _expire_recently_flushed_group's delay has passed, a photo for
    that same group_id is a normal (if odd) case - it starts a fresh
    pending group rather than being treated as a stale straggler forever."""
    group_id = "expired-test-group"
    bot._recently_flushed_groups[group_id] = time.monotonic() - (bot.RECENTLY_FLUSHED_GRACE_SECONDS + 1)
    message = _make_photo_message(media_group_id=group_id)

    try:
        await bot.handle_photo_message(message)

        message.reply.assert_not_awaited()
        assert group_id in bot._pending_photo_groups
        bot._pending_photo_groups[group_id]["timer"].cancel()
    finally:
        bot._recently_flushed_groups.pop(group_id, None)
        bot._pending_photo_groups.pop(group_id, None)
