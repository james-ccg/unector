"""
What happens when the bot check cannot run.

Turnstile validates the hostname a widget is embedded on against the site
key's allowed list, so the same build that works on one address refuses on
another - a tunnel, a staging domain, anything not registered. When it
refuses, no token is produced, and the form is left disabled with nothing on
screen explaining why.

The old message for that case said "Couldn't confirm you're not a bot. Try
again." Both halves were wrong: nothing had been confirmed or denied about
the visitor, and trying again cannot change a setting in somebody's
Cloudflare dashboard.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = (ROOT / "miniapp" / "api.py").read_text(encoding="utf-8")
COMPONENT = (
    ROOT / "frontend" / "src" / "components" / "Turnstile.tsx"
).read_text(encoding="utf-8")
LIB = (ROOT / "frontend" / "src" / "lib" / "turnstile.ts").read_text(encoding="utf-8")
PAGES = ["LoginPage", "RegisterPage", "ForgotPasswordPage"]


def _verify_turnstile_source() -> str:
    start = API.index("def verify_turnstile(")
    end = API.index("\n@app.", start)
    return API[start:end]


class TestTheServerSaysWhichFailure:
    def test_a_missing_token_is_not_described_as_a_failed_check(self):
        """The two cases have different causes and different fixes, and the
        message used to be the same for both."""
        source = _verify_turnstile_source()
        missing, rejected = source.split("result.get(\"success\")")
        assert "didn't run" in missing
        assert "Couldn't confirm you're not a bot" not in missing

    def test_the_reason_cloudflare_gave_is_logged(self):
        """error-codes names our own configuration as often as anything the
        visitor did, so it is logged rather than shown - but losing it
        entirely leaves nothing to diagnose from."""
        assert 'result.get("error-codes")' in _verify_turnstile_source()


class TestTheWidgetReportsItsFailure:
    def test_a_load_failure_is_handled_rather_than_thrown_away(self):
        """It was a .then() with no .catch(), so the message written for this
        case reached the console as an unhandled rejection and nobody else."""
        assert ".catch(" in COMPONENT
        assert "onUnavailableRef.current?.(detail)" in COMPONENT

    def test_a_failed_script_load_is_not_cached_forever(self):
        """A rejected promise stays rejected. Caching it made the first
        failure permanent for the life of the tab, including after the
        connection came back."""
        assert "scriptPromise = null" in COMPONENT

    def test_the_error_callback_tells_the_page(self):
        assert "'error-callback'" in COMPONENT
        assert "describeTurnstileError" in COMPONENT

    @pytest.mark.parametrize("page", PAGES)
    def test_every_gated_form_shows_the_reason(self, page):
        """All three block submission without a token, so all three need to
        say why when there will never be one."""
        text = (ROOT / "frontend" / "src" / "pages" / f"{page}.tsx").read_text(encoding="utf-8")
        assert "onUnavailable={setTurnstileError}" in text, page
        assert "turnstileUnavailableMessage(turnstileError)" in text, page

    @pytest.mark.parametrize("page", PAGES)
    def test_a_retry_clears_the_previous_reason(self, page):
        """Otherwise a stale explanation sits under a widget that has since
        recovered."""
        text = (ROOT / "frontend" / "src" / "pages" / f"{page}.tsx").read_text(encoding="utf-8")
        assert "setTurnstileError(null)" in text, page


class TestTheWording:
    def test_the_domain_case_is_named(self):
        """110200 is the one that costs the most time unaided: the widget
        draws a generic "cannot connect" box, and the real problem is a
        hostname missing from the site key's list."""
        assert "'110200'" in LIB
        assert "not on the allowed list" in LIB

    def test_an_unknown_code_still_says_something_specific(self):
        """Better a number somebody can search for than "an error occurred"."""
        assert "reported error ${code}" in LIB

    def test_the_message_does_not_tell_people_to_try_again(self):
        """The form is already disabled. Suggesting a retry is suggesting the
        one action that cannot work."""
        message = LIB[LIB.index("export function turnstileUnavailableMessage"):]
        # The sentence is split across two source lines, so a phrase can
        # straddle the seam between the quoted halves. Joining them back up
        # is what makes searching for a sentence mean anything - the same
        # trick tests/test_trial_disclosure.py needs, and the same reason a
        # split string once hid "Pin messages" from a search for it.
        joined = " ".join(message.split()).replace('` + "', "").replace('" +', "")
        assert "trying again won't help" in joined
        assert not re.search(r"\bTry again\b", joined)
