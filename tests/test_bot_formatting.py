"""
Tests for bot.py's HTML message formatting. _format_bol_response and
_format_loadpics_response build Telegram HTML-parse-mode messages out of
values Gemini extracted from a driver-submitted photo (i.e. untrusted OCR
output) - every dynamic value must be HTML-escaped before interpolation,
or a photographed "<" or "&" could break Telegram's parser or inject fake
formatting into the message.
"""
from bot import _format_bol_response, _format_loadpics_response


class TestBolResponseEscaping:
    def test_html_special_chars_in_weight_are_escaped(self):
        result = {
            "weight": {"bol": "<script>bad</script>", "rc": "45,000 & up", "status": "ok"},
            "delivery_address": {"bol": "123 Main St", "rc": "123 Main St", "status": "match", "emoji": "✅"},
            "temperature": {"rc": "34F", "bol": "34F", "status": "match"},
            "seal": {"summary": "<b>fake bold</b> injected"},
        }
        html_output = _format_bol_response(result)

        assert "<script>" not in html_output
        assert "&lt;script&gt;" in html_output
        assert "45,000 &amp; up" in html_output
        assert "<b>fake bold</b> injected" not in html_output
        assert "&lt;b&gt;fake bold&lt;/b&gt; injected" in html_output

    def test_plain_values_render_normally(self):
        result = {
            "weight": {"bol": "44,000", "rc": "45,000", "status": "okay"},
            "delivery_address": {"bol": "123 Main St", "rc": "123 Main St", "status": "match", "emoji": "✅"},
            "temperature": {"rc": "34F", "bol": "34F", "status": "match"},
            "seal": {"summary": "Seal numbers match"},
        }
        html_output = _format_bol_response(result)
        assert "44,000" in html_output
        assert "Seal numbers match" in html_output
        assert "<b>Weight:</b>" in html_output  # our own static tags still render


class TestLoadpicsResponseEscaping:
    def test_html_special_chars_in_seal_are_escaped(self):
        result = {
            "task1_securement": {"status": "excellent"},
            "task2_seal": {"bol": "<img src=x onerror=alert(1)>", "photos": "ABC123", "status": "match"},
            "task3_temperature": {"rc": "34F", "bol": "34F", "photos": "34F", "status": "match"},
            "task4_documentation": {"rc": "2 pages", "bol": "2 pages", "status": "match"},
            "issues": [],
        }
        html_output = _format_loadpics_response(result)
        assert "<img" not in html_output
        assert "&lt;img src=x onerror=alert(1)&gt;" in html_output
