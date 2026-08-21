"""
Tests for bot.py's /verify2fa command - links a Telegram account to an
owner/dispatcher login for 2FA delivery. Since /linkdriver was added
sharing the same TelegramLinkToken table (a different account_type,
"driver_group", for linking a driver's group instead), these tests lock in
that a code from one flow can never be consumed by the other - see
tests/test_bot_linkdriver.py for the mirror-image coverage.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot


def _make_message(text=None):
    message = MagicMock()
    message.text = text
    message.from_user.id = 555666777
    message.reply = AsyncMock()
    return message


class TestVerify2faUsage:
    @pytest.mark.asyncio
    async def test_no_code_shows_usage(self):
        message = _make_message(text="/verify2fa")
        await bot.handle_verify2fa(message)

        assert "Usage: /verify2fa" in message.reply.await_args.args[0]


class TestVerify2faCodeValidation:
    @pytest.mark.asyncio
    async def test_invalid_or_expired_code_shows_friendly_message(self):
        message = _make_message(text="/verify2fa BADCODE")

        with patch.object(bot, "consume_telegram_link_token", return_value=None), \
             patch.object(bot, "set_telegram_otp") as set_otp:
            await bot.handle_verify2fa(message)

        set_otp.assert_not_called()
        assert "invalid or has expired" in message.reply.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_driver_link_code_rejected(self):
        """A code generated for /linkdriver (account_type "driver_group")
        must not be usable to enroll Telegram 2FA for an owner/dispatcher,
        even though both flows share the same TelegramLinkToken table."""
        message = _make_message(text="/verify2fa ABC123")

        with patch.object(bot, "consume_telegram_link_token", return_value={"account_type": "driver_group", "account_id": 42}) as consume, \
             patch.object(bot, "set_telegram_otp") as set_otp:
            await bot.handle_verify2fa(message)

        consume.assert_called_once_with("ABC123")
        set_otp.assert_not_called()
        assert "invalid or has expired" in message.reply.await_args.args[0].lower()


class TestVerify2faHappyPath:
    @pytest.mark.asyncio
    async def test_owner_code_links_telegram(self):
        message = _make_message(text="/verify2fa abc123")

        with patch.object(bot, "consume_telegram_link_token", return_value={"account_type": "owner", "account_id": 7}), \
             patch.object(bot, "set_telegram_otp") as set_otp:
            await bot.handle_verify2fa(message)

        set_otp.assert_called_once_with("owner", 7, 555666777, enabled=True)
        assert "linked" in message.reply.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_dispatcher_code_links_telegram(self):
        message = _make_message(text="/verify2fa abc123")

        with patch.object(bot, "consume_telegram_link_token", return_value={"account_type": "dispatcher", "account_id": 9}), \
             patch.object(bot, "set_telegram_otp") as set_otp:
            await bot.handle_verify2fa(message)

        set_otp.assert_called_once_with("dispatcher", 9, 555666777, enabled=True)
