"""
Tests for pinning the load card in a driver's group.

The card carries the addresses, the appointment times and the reference
numbers, and by the afternoon it is a long way up a busy group. Pinning it
puts it one tap away, and exactly one load stays pinned so the driver never
has to work out which of several pins is today's job.

The rule these tests exist to hold is that none of it may cost a dispatch.
The load is saved and posted before any of this runs, so a group where the
bot was never made an admin still gets its load.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError

import bot


def _posted_card(message_id=555, chat_id=-100123456):
    """The Message that message.answer() hands back after posting a card."""
    posted = MagicMock()
    posted.message_id = message_id
    posted.chat.id = chat_id
    posted.pin = AsyncMock()
    return posted


class TestPinningTheCard:
    @pytest.mark.asyncio
    async def test_the_new_card_is_pinned(self):
        posted = _posted_card()
        with patch.object(bot, "take_over_pin", return_value=[]), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.unpin_chat_message = AsyncMock()
            assert await bot._pin_load_card(1, 2, "L-1", posted) is True

        posted.pin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pinning_does_not_ping_the_group_a_second_time(self):
        """The card itself just notified everyone. Saying it was pinned adds
        nothing except another buzz in the driver's pocket."""
        posted = _posted_card()
        with patch.object(bot, "take_over_pin", return_value=[]), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.unpin_chat_message = AsyncMock()
            await bot._pin_load_card(1, 2, "L-1", posted)

        assert posted.pin.await_args.kwargs["disable_notification"] is True

    @pytest.mark.asyncio
    async def test_the_previous_card_is_unpinned(self):
        posted = _posted_card(message_id=900)
        with patch.object(bot, "take_over_pin", return_value=[404, 405]), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.unpin_chat_message = AsyncMock()
            await bot._pin_load_card(1, 2, "L-2", posted)

        unpinned = [c.args[1] for c in fake_bot.unpin_chat_message.await_args_list]
        assert unpinned == [404, 405]

    @pytest.mark.asyncio
    async def test_the_new_pin_goes_up_before_the_old_one_comes_down(self):
        """Ordered this way round so the group is never left with no pinned
        load, however the network behaves in between."""
        order = []
        posted = _posted_card()
        posted.pin = AsyncMock(side_effect=lambda **kw: order.append("pin"))
        with patch.object(bot, "take_over_pin", return_value=[404]), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.unpin_chat_message = AsyncMock(
                side_effect=lambda *a, **k: order.append("unpin")
            )
            await bot._pin_load_card(1, 2, "L-2", posted)

        assert order == ["pin", "unpin"]


class TestNothingCostsTheDispatch:
    @pytest.mark.asyncio
    async def test_a_bot_without_the_right_to_pin_is_not_an_error(self):
        """The ordinary case in a group nobody made the bot an admin in."""
        posted = _posted_card()
        posted.pin = AsyncMock(
            side_effect=TelegramAPIError(method=MagicMock(), message="not enough rights")
        )
        with patch.object(bot, "take_over_pin", return_value=[]), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.unpin_chat_message = AsyncMock()
            assert await bot._pin_load_card(1, 2, "L-1", posted) is False

    @pytest.mark.asyncio
    async def test_a_previous_pin_that_will_not_come_down_still_leaves_the_new_one_up(self):
        """A driver who unpinned it themselves, or a message old enough that
        Telegram will not touch it. The new card is already pinned by then."""
        posted = _posted_card()
        with patch.object(bot, "take_over_pin", return_value=[404]), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.unpin_chat_message = AsyncMock(
                side_effect=TelegramAPIError(method=MagicMock(), message="message to unpin not found")
            )
            assert await bot._pin_load_card(1, 2, "L-2", posted) is True

        posted.pin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_database_that_will_not_record_the_pin_pins_nothing(self):
        """If the id cannot be stored, the next dispatch has no way to take
        this pin down - so leave the group as it is rather than start a
        stack of pins nothing remembers."""
        posted = _posted_card()
        with patch.object(bot, "take_over_pin", side_effect=RuntimeError("db is gone")), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.unpin_chat_message = AsyncMock()
            assert await bot._pin_load_card(1, 2, "L-1", posted) is False

        posted.pin.assert_not_awaited()
