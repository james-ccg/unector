"""
A blank line in .env has to mean the same as a missing one.

os.getenv's own default only applies when a key is absent entirely. A key
that is present but empty - `GMAIL_OAUTH_REDIRECT_URI=` on its own line,
which is how .env.example ships several of them - returns "", and the
fallback written beside it never runs.

This has now cost the project twice. Every app email went out with an empty
From header once. Then an OAuth request went to Google with an empty
redirect_uri, and Google answered "Missing required parameter: redirect_uri"
- an error that reads like a bug in the request builder and is a blank line
in a config file.

So the rule is enforced here rather than remembered: anything with a default
reads it through config.env(), and a blank value gets that default.
"""
import pathlib
import re

import pytest

from config import env

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestTheHelper:
    def test_a_missing_key_gets_the_default(self, monkeypatch):
        monkeypatch.delenv("UNECTOR_TEST_SETTING", raising=False)
        assert env("UNECTOR_TEST_SETTING", "fallback") == "fallback"

    def test_a_blank_key_gets_the_default_too(self, monkeypatch):
        """The whole point. os.getenv returns "" here and would not."""
        monkeypatch.setenv("UNECTOR_TEST_SETTING", "")
        assert env("UNECTOR_TEST_SETTING", "fallback") == "fallback"

    def test_whitespace_counts_as_blank(self, monkeypatch):
        """`KEY=   ` is a typo, not a setting."""
        monkeypatch.setenv("UNECTOR_TEST_SETTING", "   ")
        assert env("UNECTOR_TEST_SETTING", "fallback") == "fallback"

    def test_a_real_value_wins(self, monkeypatch):
        monkeypatch.setenv("UNECTOR_TEST_SETTING", "chosen")
        assert env("UNECTOR_TEST_SETTING", "fallback") == "chosen"

    def test_a_real_value_is_trimmed(self, monkeypatch):
        """A trailing space after a URL in .env is invisible and breaks an
        exact-match comparison at the other end."""
        monkeypatch.setenv("UNECTOR_TEST_SETTING", "  https://example.com  ")
        assert env("UNECTOR_TEST_SETTING", "fallback") == "https://example.com"

    def test_no_default_means_empty_string(self, monkeypatch):
        monkeypatch.delenv("UNECTOR_TEST_SETTING", raising=False)
        assert env("UNECTOR_TEST_SETTING") == ""


class TestNothingStillUsesTheUnsafeForm:
    """A *non-empty* default passed to os.getenv is the shape that fails,
    because that is the case where something is lost. Caught by reading the
    source, since the failure only appears when somebody happens to leave
    that particular key blank.

    `os.getenv("X", "")` stays allowed and is not matched below: it says
    "empty when unset", which is what the optional settings want, and there
    is no fallback for a blank value to defeat.
    """

    FILES = ["config.py", "miniapp/api.py"]

    @pytest.mark.parametrize("filename", FILES)
    def test_no_getenv_carries_a_default_it_cannot_deliver(self, filename):
        text = (ROOT / filename).read_text(encoding="utf-8")
        # Skip the helper's own docstring, which names the pattern to explain it.
        text = text.replace("os.getenv's own default", "")
        offenders = re.findall(r'os\.getenv\("([A-Z_]+)",\s*"[^"]+"\)', text)
        assert not offenders, f"{filename}: {sorted(set(offenders))} - use env() instead"


class TestTheRedirectUrisResolve:
    """The three OAuth callbacks, which is where this last went wrong.
    Google rejects an empty redirect_uri outright, and all three are shipped
    blank in at least one environment."""

    @pytest.mark.parametrize("name,tail", [
        ("GMAIL_REDIRECT_URI", "/api/settings/gmail/callback"),
        ("GOOGLE_LOGIN_REDIRECT_URI", "/api/auth/google/callback"),
        ("REGISTER_GMAIL_REDIRECT_URI", "/api/auth/register/gmail/callback"),
    ])
    def test_it_is_never_empty(self, name, tail):
        import miniapp.api as api

        value = getattr(api, name)
        assert value, f"{name} is empty - Google answers 'Missing required parameter'"
        assert value.endswith(tail), value
        assert value.startswith("http"), value
