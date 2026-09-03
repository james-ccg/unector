"""
Tests for the Telegram half of reading a truck group's description: the
offer that follows /linkdriver, the /readbio re-read, and the Confirm /
Not now buttons.

The same proposal is confirmable from the dashboard, so the case that
matters most here is the second press - whoever gets there second must be
told it is already done, not shown a failure.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot


def _make_message(text=None, chat_type="supergroup", chat_id=-100123456):
    message = MagicMock()
    message.chat.type = chat_type
    message.chat.id = chat_id
    message.chat.title = "ODM 3001"
    message.text = text
    message.reply = AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
    return message


def _make_callback(data):
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message.html_text = "From this group's description:"
    callback.message.edit_text = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    return callback


PROPOSAL = {
    "id": 7,
    "fields": {"truck_number": "3001", "driver_name": "Fareedullah"},
    "unclear": [],
    "conflicts": [],
}


class TestOfferAfterLinking:
    @pytest.mark.asyncio
    async def test_a_bio_worth_reading_is_offered_with_buttons(self):
        with patch.object(bot.group_profile, "read_and_propose", AsyncMock(return_value=PROPOSAL)), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.send_message = AsyncMock()
            await bot.offer_group_profile(-100123456, driver_id=1, company_id=1)

        text, kwargs = fake_bot.send_message.await_args.args[1], fake_bot.send_message.await_args.kwargs
        assert "3001" in text
        buttons = kwargs["reply_markup"].inline_keyboard[0]
        assert [b.callback_data for b in buttons] == ["gp:apply:7", "gp:skip:7"]

    @pytest.mark.asyncio
    async def test_an_empty_bio_says_nothing_at_all(self):
        """A group somebody just made has no description. That is ordinary,
        not something to interrupt them about."""
        with patch.object(bot.group_profile, "read_and_propose", AsyncMock(return_value=None)), \
             patch.object(bot, "bot") as fake_bot:
            fake_bot.send_message = AsyncMock()
            await bot.offer_group_profile(-100123456, driver_id=1, company_id=1)

        fake_bot.send_message.assert_not_awaited()


class TestReadBio:
    @pytest.mark.asyncio
    async def test_private_chat_is_turned_away(self):
        message = _make_message(text="/readbio", chat_type="private")
        with patch.object(bot, "get_driver_by_group") as lookup:
            await bot.handle_readbio(message)
        lookup.assert_not_called()
        assert "group" in message.reply.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_an_unlinked_group_is_told_how_to_link(self):
        message = _make_message(text="/readbio")
        with patch.object(bot, "get_driver_by_group", return_value=None):
            await bot.handle_readbio(message)
        assert "/linkdriver" in message.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_a_bio_with_nothing_in_it_says_what_to_do_next(self):
        message = _make_message(text="/readbio")
        driver = MagicMock(id=1, company_id=1)
        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot.group_profile, "read_and_propose", AsyncMock(return_value=None)):
            await bot.handle_readbio(message)

        notice = message.reply.await_args_list[0]
        said = message.reply.return_value.edit_text.await_args.args[0]
        assert "Reading" in notice.args[0]
        assert "/readbio again" in said


class TestButtons:
    @pytest.mark.asyncio
    async def test_confirm_saves_it(self):
        callback = _make_callback("gp:apply:7")
        with patch.object(bot, "apply_group_profile_proposal", return_value=(True, "ok")) as apply:
            await bot.handle_group_profile_button(callback)

        apply.assert_called_once_with(7, "telegram")
        assert "Saved" in callback.message.edit_text.await_args.args[0]

    @pytest.mark.asyncio
    async def test_not_now_dismisses_it(self):
        callback = _make_callback("gp:skip:7")
        with patch.object(bot, "dismiss_group_profile_proposal", return_value=(True, "ok")) as skip:
            await bot.handle_group_profile_button(callback)

        skip.assert_called_once_with(7, "telegram")

    @pytest.mark.asyncio
    async def test_a_proposal_the_dashboard_already_handled_is_not_an_error(self):
        callback = _make_callback("gp:apply:7")
        with patch.object(
            bot, "apply_group_profile_proposal", return_value=(False, "already_resolved")
        ):
            await bot.handle_group_profile_button(callback)

        said = callback.answer.await_args.args[0]
        assert "already" in said.lower()
        callback.message.edit_reply_markup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_failure_names_the_reason(self):
        callback = _make_callback("gp:apply:7")
        with patch.object(bot, "apply_group_profile_proposal", return_value=(False, "not_found")):
            await bot.handle_group_profile_button(callback)

        assert "not_found" in callback.answer.await_args.args[0]

    @pytest.mark.asyncio
    async def test_a_malformed_button_writes_nothing(self):
        callback = _make_callback("gp:apply:not-a-number")
        with patch.object(bot, "apply_group_profile_proposal") as apply:
            await bot.handle_group_profile_button(callback)

        apply.assert_not_called()
        callback.answer.assert_awaited_once()
