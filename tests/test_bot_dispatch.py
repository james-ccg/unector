"""
Tests for bot.py's /dispatch command (renamed from /loadid, with a new
behavior added alongside the rename): a load number after /dispatch
searches email like before; with no number, an attached or replied-to PDF
builds the RC template directly instead.

Dependencies (DB repository functions, gemini_service, email_service,
geo_utils) are patched on the bot module directly - these tests exercise
the branching logic in handle_dispatch_text/handle_dispatch_document, not
the real Gmail/Gemini/DB integrations (those are covered elsewhere).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot


def _make_driver(company_id=1):
    driver = MagicMock()
    driver.id = 10
    driver.company_id = company_id
    driver.dispatcher_username = None
    driver.telegram_username = None
    return driver


def _make_company(company_id=1):
    company = MagicMock()
    company.id = company_id
    return company


def _make_message(text=None, caption=None, document=None, reply_to_document=None):
    message = MagicMock()
    message.chat.type = "private"  # skips the update_group_title DB call
    message.chat.id = 555
    message.message_id = 999
    message.text = text
    message.caption = caption
    message.document = document
    if reply_to_document is not None:
        message.reply_to_message = MagicMock()
        message.reply_to_message.document = reply_to_document
    else:
        message.reply_to_message = None
    message.reply = AsyncMock()
    message.answer = AsyncMock()
    return message


def _make_document(mime_type="application/pdf", file_size=1024):
    doc = MagicMock()
    doc.mime_type = mime_type
    doc.file_size = file_size
    doc.file_id = "fake-file-id"
    return doc


class TestCommandArg:
    def test_extracts_number_after_command(self):
        assert bot._command_arg("/dispatch 11111", "dispatch") == "11111"

    def test_empty_when_bare_command(self):
        assert bot._command_arg("/dispatch", "dispatch") == ""

    def test_empty_when_only_whitespace_follows(self):
        assert bot._command_arg("/dispatch   ", "dispatch") == ""

    def test_works_with_botname_suffix(self):
        assert bot._command_arg("/dispatch@FreightPilot_bot 22222", "dispatch") == "22222"


class TestDispatchTextWithNumber:
    @pytest.mark.asyncio
    async def test_number_triggers_email_search(self):
        message = _make_message(text="/dispatch 11111")
        driver, company = _make_driver(), _make_company()

        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot, "get_company", return_value=company), \
             patch.object(bot.email_service, "find_rc_pdf_by_load_id", return_value=None) as find_rc:
            await bot.handle_dispatch_text(message)

        find_rc.assert_called_once_with(company.id, "11111")

    @pytest.mark.asyncio
    async def test_number_ignores_a_replied_document(self):
        """Per spec: a load number always means "search email", even if a
        PDF was also attached/replied to - the number takes priority."""
        message = _make_message(text="/dispatch 11111", reply_to_document=_make_document())
        driver, company = _make_driver(), _make_company()

        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot, "get_company", return_value=company), \
             patch.object(bot.email_service, "find_rc_pdf_by_load_id", return_value=None) as find_rc, \
             patch.object(bot.gemini_service, "extract_rc_data") as extract:
            await bot.handle_dispatch_text(message)

        find_rc.assert_called_once()
        extract.assert_not_called()


class TestDispatchTextNoNumber:
    @pytest.mark.asyncio
    async def test_no_number_no_reply_shows_usage(self):
        message = _make_message(text="/dispatch")
        driver, company = _make_driver(), _make_company()

        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot, "get_company", return_value=company):
            await bot.handle_dispatch_text(message)

        message.reply.assert_awaited_once()
        assert "Usage: /dispatch" in message.reply.await_args.args[0]

    @pytest.mark.asyncio
    async def test_no_number_with_replied_pdf_builds_from_it(self):
        replied_doc = _make_document()
        message = _make_message(text="/dispatch", reply_to_document=replied_doc)
        driver, company = _make_driver(), _make_company()

        fake_file = MagicMock()
        fake_file.file_path = "fake/path.pdf"
        fake_download = MagicMock()
        fake_download.read.return_value = b"%PDF-fake-bytes"

        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot, "get_company", return_value=company), \
             patch.object(bot, "save_load") as save_load, \
             patch.object(bot.bot, "get_file", AsyncMock(return_value=fake_file)), \
             patch.object(bot.bot, "download_file", AsyncMock(return_value=fake_download)), \
             patch.object(bot.gemini_service, "extract_rc_data", return_value={"load_id": "77777"}), \
             patch.object(bot.geo_utils, "geocode_address", AsyncMock(return_value=None)):
            await bot.handle_dispatch_text(message)

        save_load.assert_called_once()
        assert save_load.call_args.args[2] == "77777"  # extracted load_id, not a placeholder

    @pytest.mark.asyncio
    async def test_no_load_id_extracted_falls_back_to_placeholder(self):
        replied_doc = _make_document()
        message = _make_message(text="/dispatch", reply_to_document=replied_doc)
        driver, company = _make_driver(), _make_company()

        fake_file = MagicMock()
        fake_file.file_path = "fake/path.pdf"
        fake_download = MagicMock()
        fake_download.read.return_value = b"%PDF-fake-bytes"

        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot, "get_company", return_value=company), \
             patch.object(bot, "save_load") as save_load, \
             patch.object(bot.bot, "get_file", AsyncMock(return_value=fake_file)), \
             patch.object(bot.bot, "download_file", AsyncMock(return_value=fake_download)), \
             patch.object(bot.gemini_service, "extract_rc_data", return_value={"load_id": None}), \
             patch.object(bot.geo_utils, "geocode_address", AsyncMock(return_value=None)):
            await bot.handle_dispatch_text(message)

        save_load.assert_called_once()
        assert save_load.call_args.args[2] == f"PDF-{message.message_id}"


class TestDispatchDocumentCaption:
    @pytest.mark.asyncio
    async def test_number_in_caption_still_searches_email(self):
        doc = _make_document()
        message = _make_message(caption="/dispatch 33333", document=doc)
        driver, company = _make_driver(), _make_company()

        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot, "get_company", return_value=company), \
             patch.object(bot.email_service, "find_rc_pdf_by_load_id", return_value=None) as find_rc, \
             patch.object(bot.gemini_service, "extract_rc_data") as extract:
            await bot.handle_dispatch_document(message)

        find_rc.assert_called_once_with(company.id, "33333")
        extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_number_uses_the_attached_pdf(self):
        doc = _make_document()
        message = _make_message(caption="/dispatch", document=doc)
        driver, company = _make_driver(), _make_company()

        fake_file = MagicMock()
        fake_file.file_path = "fake/path.pdf"
        fake_download = MagicMock()
        fake_download.read.return_value = b"%PDF-fake-bytes"

        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot, "get_company", return_value=company), \
             patch.object(bot, "save_load") as save_load, \
             patch.object(bot.bot, "get_file", AsyncMock(return_value=fake_file)), \
             patch.object(bot.bot, "download_file", AsyncMock(return_value=fake_download)), \
             patch.object(bot.gemini_service, "extract_rc_data", return_value={"load_id": "88888"}), \
             patch.object(bot.geo_utils, "geocode_address", AsyncMock(return_value=None)):
            await bot.handle_dispatch_document(message)

        save_load.assert_called_once()
        assert save_load.call_args.args[2] == "88888"

    @pytest.mark.asyncio
    async def test_rejects_unsupported_file_type(self):
        doc = _make_document(mime_type="application/zip")
        message = _make_message(caption="/dispatch", document=doc)
        driver, company = _make_driver(), _make_company()

        with patch.object(bot, "get_driver_by_group", return_value=driver), \
             patch.object(bot, "get_company", return_value=company), \
             patch.object(bot.gemini_service, "extract_rc_data") as extract:
            await bot.handle_dispatch_document(message)

        extract.assert_not_called()
        message.reply.assert_awaited_once()
        assert "supported" in message.reply.await_args.args[0].lower()
