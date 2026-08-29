"""
Tests for services/gemini_service.py - the AI extraction the whole dispatch
flow depends on.

The model call itself is mocked; what's tested is everything around it: the
retry-on-overload loop (a 503 that isn't retried surfaces to the driver as a
failed /dispatch), how a response is parsed back into JSON, and that the
documents handed in actually reach the request.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import ServerError

from services import gemini_service


def _response(text: str) -> MagicMock:
    return MagicMock(text=text)


def _server_error() -> ServerError:
    """A 503 from Gemini, as raised by the SDK when the model is overloaded."""
    return ServerError(503, {"error": {"message": "The model is overloaded."}})


class TestParseJsonResponse:
    def test_parses_a_clean_json_response(self):
        payload = {"load_id": "12345", "rate_amount": 2500}
        assert gemini_service._parse_json_response(_response(json.dumps(payload))) == payload

    def test_strips_markdown_code_fences(self):
        """response_mime_type=json should prevent fences, but the model has
        been known to add them anyway and that used to break extraction."""
        fenced = '```json\n{"load_id": "12345"}\n```'
        assert gemini_service._parse_json_response(_response(fenced)) == {"load_id": "12345"}

    def test_strips_a_bare_fence_without_a_language_tag(self):
        assert gemini_service._parse_json_response(_response('```\n{"a": 1}\n```')) == {"a": 1}

    def test_tolerates_surrounding_whitespace(self):
        assert gemini_service._parse_json_response(_response('  \n {"a": 1} \n ')) == {"a": 1}

    def test_unparseable_output_raises_a_clear_value_error(self):
        """bot.py catches this and tells the driver to try again, rather
        than dumping a JSONDecodeError into the Telegram group."""
        with pytest.raises(ValueError, match="Could not parse Gemini's response as JSON"):
            gemini_service._parse_json_response(_response("Sorry, I can't read this document."))

    def test_the_error_includes_the_offending_output(self):
        """Without the actual text there's nothing to debug from."""
        with pytest.raises(ValueError, match="not json at all"):
            gemini_service._parse_json_response(_response("not json at all"))

    def test_a_none_response_text_is_handled(self):
        with pytest.raises(ValueError):
            gemini_service._parse_json_response(MagicMock(text=None))

    def test_preserves_nested_structures(self):
        """RC extraction returns arrays of extra stops that must survive."""
        payload = {"additional_pu_stops": [{"address": "A", "date": "1/1/2026", "reference": None}]}
        assert gemini_service._parse_json_response(_response(json.dumps(payload))) == payload


class TestGenerateWithRetry:
    def test_returns_immediately_when_the_first_call_succeeds(self):
        client = MagicMock()
        client.models.generate_content.return_value = _response("{}")
        with patch.object(gemini_service, "client", client), \
             patch("time.sleep") as sleep:
            result = gemini_service._generate_with_retry(model="m", contents=[])

        assert result.text == "{}"
        assert client.models.generate_content.call_count == 1
        sleep.assert_not_called()

    def test_retries_after_an_overload_and_then_succeeds(self):
        """Most 503s clear within seconds - retrying beats making the driver
        re-run /dispatch."""
        client = MagicMock()
        client.models.generate_content.side_effect = [_server_error(), _response('{"ok": true}')]
        with patch.object(gemini_service, "client", client), \
             patch("time.sleep") as sleep:
            result = gemini_service._generate_with_retry(model="m", contents=[])

        assert result.text == '{"ok": true}'
        assert client.models.generate_content.call_count == 2
        sleep.assert_called_once_with(gemini_service.RETRY_BACKOFF_SECONDS)

    def test_gives_up_after_the_configured_number_of_attempts(self):
        client = MagicMock()
        client.models.generate_content.side_effect = _server_error()
        with patch.object(gemini_service, "client", client), \
             patch("time.sleep"):
            with pytest.raises(ServerError):
                gemini_service._generate_with_retry(model="m", contents=[])

        assert client.models.generate_content.call_count == gemini_service.MAX_RETRIES

    def test_backoff_doubles_between_attempts(self):
        """A fixed short delay would hammer an already-overloaded model."""
        client = MagicMock()
        client.models.generate_content.side_effect = _server_error()
        with patch.object(gemini_service, "client", client), \
             patch("time.sleep") as sleep:
            with pytest.raises(ServerError):
                gemini_service._generate_with_retry(model="m", contents=[])

        base = gemini_service.RETRY_BACKOFF_SECONDS
        assert [call.args[0] for call in sleep.call_args_list] == [base, base * 2]

    def test_a_non_server_error_is_not_retried(self):
        """A bad API key or malformed request will fail identically every
        time - retrying just delays the error."""
        client = MagicMock()
        client.models.generate_content.side_effect = ValueError("invalid argument")
        with patch.object(gemini_service, "client", client), \
             patch("time.sleep") as sleep:
            with pytest.raises(ValueError):
                gemini_service._generate_with_retry(model="m", contents=[])

        assert client.models.generate_content.call_count == 1
        sleep.assert_not_called()


class TestPartsFromFiles:
    def test_builds_one_part_per_file(self):
        files = [(b"\x89PNG-load", "image/png"), (b"%PDF-bol", "application/pdf")]
        parts = gemini_service._parts_from_files(files)
        assert len(parts) == 2

    def test_an_empty_list_produces_no_parts(self):
        assert gemini_service._parts_from_files([]) == []


class TestExtractionEntryPoints:
    """The three public calls - each must send the documents AND ask for
    JSON back, since _parse_json_response depends on that config."""

    def test_extract_rc_data_sends_the_pdf_and_asks_for_json(self):
        with patch.object(gemini_service, "_generate_with_retry",
                          return_value=_response('{"load_id": "999"}')) as gen:
            assert gemini_service.extract_rc_data(b"%PDF-1.4") == {"load_id": "999"}

        kwargs = gen.call_args.kwargs
        assert kwargs["config"] is gemini_service.JSON_CONFIG
        assert kwargs["model"] == gemini_service.MODEL
        # The PDF plus the prompt.
        assert len(kwargs["contents"]) == 2

    def test_check_load_picture_includes_every_photo(self):
        files = [(b"a", "image/jpeg"), (b"b", "image/jpeg"), (b"c", "image/jpeg")]
        with patch.object(gemini_service, "_generate_with_retry",
                          return_value=_response('{"loading_ok": true}')) as gen:
            gemini_service.check_load_picture({"weight": "40,000"}, files)

        # Three photos plus the prompt.
        assert len(gen.call_args.kwargs["contents"]) == 4

    def test_compare_bol_with_rc_embeds_the_rc_data_in_the_prompt(self):
        """The comparison is only meaningful if the RC values actually reach
        the model."""
        with patch.object(gemini_service, "_generate_with_retry",
                          return_value=_response('{"match": true}')) as gen:
            gemini_service.compare_bol_with_rc(
                {"weight": "45,000", "del_address": "Kroger DC"}, [(b"img", "image/jpeg")]
            )

        prompt = gen.call_args.kwargs["contents"][-1]
        assert "45,000" in prompt
        assert "Kroger DC" in prompt

    def test_non_ascii_rc_data_survives_into_the_prompt(self):
        """ensure_ascii=False is deliberate - escaping would make addresses
        unreadable to the model."""
        with patch.object(gemini_service, "_generate_with_retry",
                          return_value=_response("{}")) as gen:
            gemini_service.compare_bol_with_rc({"broker_name": "Grüne Logistik"}, [])

        assert "Grüne Logistik" in gen.call_args.kwargs["contents"][-1]
