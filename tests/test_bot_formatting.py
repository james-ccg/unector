"""
Tests for bot.py's HTML message formatting. _format_bol_response and
_format_loadpics_response build Telegram HTML-parse-mode messages out of
values Gemini extracted from a driver-submitted photo (i.e. untrusted OCR
output) - every dynamic value must be HTML-escaped before interpolation,
or a photographed "<" or "&" could break Telegram's parser or inject fake
formatting into the message.
"""
from bot import _format_bol_response, _format_loadpics_response, format_load_template


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


class TestFormatLoadTemplateStops:
    """format_load_template renders one PU/DEL block per stop - the primary
    pu_address/del_address plus any additional_pu_stops/additional_del_stops
    Gemini found on a multi-stop RC."""

    def _base_data(self, **overrides):
        data = {
            "broker_name": "ACME Logistics",
            "pu_address": "123 Origin St\nOriginville, OH 43000",
            "pu_date": "8/3/2026",
            "pu_time": "17:15",
            "del_address": "456 Dest Ave\nDestcity, NJ 07000",
            "del_date": "8/4/2026",
            "del_time": "10:30",
        }
        data.update(overrides)
        return data

    def test_single_stop_load_shows_one_pu_and_one_del(self):
        text = format_load_template("11111", self._base_data())
        assert text.count("PU:") == 1
        assert text.count("DEL:") == 1
        assert "🟢 PU:1" in text
        assert "🔴 DEL:1" in text

    def test_multi_stop_pu_renders_each_stop_numbered_in_order(self):
        data = self._base_data(additional_pu_stops=[
            {"address": "789 Second Stop Rd\nCity2, OH 43001", "date": "8/3/2026", "time": "19:00", "reference": "PU2-REF"},
            {"address": "111 Third Stop Rd\nCity3, OH 43002", "date": "8/3/2026", "time": "21:00"},
        ])
        text = format_load_template("22222", data)

        assert text.count("PU:") == 3
        assert "🟢 PU:1" in text
        assert "🟢 PU:2" in text
        assert "🟢 PU:3" in text
        # Order preserved: stop 2 appears before stop 3 in the rendered text.
        assert text.index("Second Stop Rd") < text.index("Third Stop Rd")
        assert "PU2-REF" in text

    def test_multi_stop_del_renders_each_stop_numbered(self):
        data = self._base_data(additional_del_stops=[
            {"address": "222 Second Drop Ave\nCity2, NJ 07001", "date": "8/4/2026", "time": "14:00"},
        ])
        text = format_load_template("33333", data)

        assert text.count("DEL:") == 2
        assert "🔴 DEL:1" in text
        assert "🔴 DEL:2" in text
        assert "Second Drop Ave" in text

    def test_additional_stop_addresses_are_html_escaped(self):
        data = self._base_data(additional_pu_stops=[
            {"address": "<script>bad</script>\nCity2, OH 43001", "date": "8/3/2026", "time": "19:00"},
        ])
        text = format_load_template("44444", data)
        assert "<script>" not in text
        assert "&lt;script&gt;" in text
