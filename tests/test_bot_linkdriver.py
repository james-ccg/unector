"""
Tests for bot.py's /linkdriver command: links a NEW Telegram group to a
driver record created from the dashboard's Settings > Drivers page, reusing
the same TelegramLinkToken code pattern /verify2fa uses for 2FA account
linking (see db/repository.py's consume_telegram_link_token). The two
commands share that token table, so the account_type check that keeps a
code from one flow being misused in the other is covered here too.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot


def _make_message(text=None, chat_type="supergroup", chat_id=-100123456, chat_title="Jasur's Truck"):
    message = MagicMock()
    message.chat.type = chat_type
    message.chat.id = chat_id
    message.chat.title = chat_title
    message.text = text
    message.reply = AsyncMock()
    return message


class TestLinkDriverUsage:
    @pytest.mark.asyncio
    async def test_no_code_shows_usage(self):
        message = _make_message(text="/linkdriver")
        await bot.handle_linkdriver(message)

        message.reply.assert_awaited_once()
        assert "Usage: /linkdriver" in message.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_private_chat_rejected_before_consuming_the_code(self):
        """A code should not be burned by a fat-fingered private-chat attempt
        - the user still has it to use correctly in the actual group."""
        message = _make_message(text="/linkdriver ABC123", chat_type="private")

        with patch.object(bot, "consume_telegram_link_token") as consume:
            await bot.handle_linkdriver(message)

        consume.assert_not_called()
        assert "group" in message.reply.await_args.args[0].lower()


class TestLinkDriverCodeValidation:
    @pytest.mark.asyncio
    async def test_invalid_or_expired_code_shows_friendly_message(self):
        message = _make_message(text="/linkdriver BADCODE")

        with patch.object(bot, "consume_telegram_link_token", return_value=None):
            await bot.handle_linkdriver(message)

        assert "invalid or has expired" in message.reply.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_2fa_linking_code_rejected(self):
        """A code generated for /verify2fa (account_type "owner"/"dispatcher")
        must not be usable to link a driver's group, even though both flows
        share the same TelegramLinkToken table."""
        message = _make_message(text="/linkdriver ABC123")

        with patch.object(bot, "consume_telegram_link_token", return_value={"account_type": "owner", "account_id": 1}) as consume, \
             patch.object(bot, "link_driver_group") as link:
            await bot.handle_linkdriver(message)

        consume.assert_called_once_with("ABC123")
        link.assert_not_called()
        assert "invalid or has expired" in message.reply.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_code_is_uppercased_before_lookup(self):
        message = _make_message(text="/linkdriver abc123")

        with patch.object(bot, "consume_telegram_link_token", return_value=None) as consume:
            await bot.handle_linkdriver(message)

        consume.assert_called_once_with("ABC123")


class TestLinkDriverHappyPath:
    @pytest.mark.asyncio
    async def test_successful_link_replies_with_confirmation(self):
        message = _make_message(text="/linkdriver abc123", chat_id=-1009999, chat_title="Driver Group")

        with patch.object(bot, "consume_telegram_link_token", return_value={"account_type": "driver_group", "account_id": 42}), \
             patch.object(bot, "link_driver_group", return_value="ok") as link:
            await bot.handle_linkdriver(message)

        link.assert_called_once_with(42, -1009999, "Driver Group")
        assert "linked" in message.reply.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_missing_group_title_falls_back_to_placeholder(self):
        message = _make_message(text="/linkdriver ABC123", chat_title=None)

        with patch.object(bot, "consume_telegram_link_token", return_value={"account_type": "driver_group", "account_id": 7}), \
             patch.object(bot, "link_driver_group", return_value="ok") as link:
            await bot.handle_linkdriver(message)

        link.assert_called_once_with(7, -100123456, "Unknown Group")


class TestLinkDriverConflict:
    @pytest.mark.asyncio
    async def test_group_already_linked_to_another_driver(self):
        message = _make_message(text="/linkdriver ABC123")

        with patch.object(bot, "consume_telegram_link_token", return_value={"account_type": "driver_group", "account_id": 42}), \
             patch.object(bot, "link_driver_group", return_value="already_linked_elsewhere"):
            await bot.handle_linkdriver(message)

        assert "already linked to a different driver" in message.reply.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_driver_no_longer_exists(self):
        message = _make_message(text="/linkdriver ABC123")

        with patch.object(bot, "consume_telegram_link_token", return_value={"account_type": "driver_group", "account_id": 999}), \
             patch.object(bot, "link_driver_group", return_value="not_found"):
            await bot.handle_linkdriver(message)

        assert "no longer exists" in message.reply.await_args.args[0].lower()
