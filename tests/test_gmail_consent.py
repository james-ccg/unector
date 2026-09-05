"""
Connecting the right mailbox, with all of the permissions.

Two things go wrong on Google's consent screen, and neither announced
itself.

The first is the account. A login hint is passed so a reconnect reopens the
mailbox already on file - which is right, and is what stops somebody with
two addresses silently connecting the wrong inbox. But while that account is
signed in Google walks straight past the chooser, so an owner whose rate
confirmations arrive somewhere else had no way to say so at all.

The second is the permissions. Google lists each one with its own checkbox,
so approving the app and approving everything it asked for are different
events. A half-granted connection used to be saved and shown as working, and
the missing half surfaced when a driver sent a POD and the broker never got
it.
"""
import urllib.parse as urlparse

import pytest

from services import gmail_service


def _query(url: str) -> dict:
    return urlparse.parse_qs(urlparse.urlparse(url).query)


class TestWhichAccountGoogleOffers:
    def test_a_reconnect_reopens_the_mailbox_on_file(self):
        """The hint is the whole reason a reconnect does not become a chance
        to connect the wrong inbox."""
        q = _query(gmail_service.build_authorization_url(
            "http://localhost:8000/cb", "state", login_hint="office@example.com",
        ))
        assert q["login_hint"] == ["office@example.com"]
        assert q["prompt"] == ["consent"]

    def test_switching_account_drops_the_hint_and_asks(self):
        q = _query(gmail_service.build_authorization_url(
            "http://localhost:8000/cb", "state", login_hint=None, force_picker=True,
        ))
        assert "login_hint" not in q
        assert q["prompt"] == ["consent select_account"]

    def test_consent_is_forced_either_way(self):
        """Google only issues a refresh token when consent is re-granted, so
        dropping it would leave a reconnect with an access token that expires
        in an hour and no way to renew it."""
        for kwargs in ({"login_hint": "a@example.com"}, {"force_picker": True}):
            q = _query(gmail_service.build_authorization_url(
                "http://localhost:8000/cb", "state", **kwargs,
            ))
            assert q["prompt"][0].startswith("consent")

    def test_offline_access_is_asked_for(self):
        q = _query(gmail_service.build_authorization_url("http://localhost:8000/cb", "state"))
        assert q["access_type"] == ["offline"]


class TestPartiallyGrantedPermissions:
    class _Credentials:
        def __init__(self, granted):
            self.refresh_token = "refresh-token"
            self.granted_scopes = granted

    class _Flow:
        def __init__(self, granted):
            self.credentials = TestPartiallyGrantedPermissions._Credentials(granted)

        def fetch_token(self, code=None):
            return None

    def _exchange(self, monkeypatch, granted):
        monkeypatch.setattr(
            gmail_service, "_build_web_flow", lambda uri: self._Flow(granted)
        )
        return gmail_service.exchange_code("code", "http://localhost:8000/cb")

    def test_everything_granted_reports_nothing_missing(self, monkeypatch):
        token, missing = self._exchange(monkeypatch, list(gmail_service.SCOPES))
        assert token == "refresh-token"
        assert missing == []

    def test_a_missing_scope_is_named(self, monkeypatch):
        """Reading without sending is the likely half: the send permission is
        the scarier-sounding one on the consent screen."""
        readonly = "https://www.googleapis.com/auth/gmail.readonly"
        _token, missing = self._exchange(monkeypatch, [readonly])
        assert missing == ["https://www.googleapis.com/auth/gmail.send"]

    def test_nothing_granted_reports_both(self, monkeypatch):
        _token, missing = self._exchange(monkeypatch, [])
        assert set(missing) == set(gmail_service.SCOPES)

    def test_an_older_library_without_the_attribute_does_not_cry_wolf(self, monkeypatch):
        """granted_scopes is not on every google-auth version. Absent has to
        mean "cannot tell", not "nothing was granted" - the second would
        refuse every connection on those versions."""
        class Bare:
            refresh_token = "refresh-token"

        class BareFlow:
            credentials = Bare()

            def fetch_token(self, code=None):
                return None

        monkeypatch.setattr(gmail_service, "_build_web_flow", lambda uri: BareFlow())
        token, missing = gmail_service.exchange_code("code", "http://localhost:8000/cb")
        assert token == "refresh-token"
        assert missing == []


class TestTheEndpoint:
    def test_the_partial_grant_has_a_sentence_of_its_own(self):
        """Four failures used to share one message. This one has to say which
        boxes were left unticked and why both matter."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        api = (root / "miniapp" / "api.py").read_text(encoding="utf-8")
        errors = (root / "frontend" / "src" / "lib" / "gmailError.ts").read_text(encoding="utf-8")

        assert "gmail=error_partial_scopes" in api
        assert "error_partial_scopes:" in errors

    @pytest.mark.parametrize("needle", ["switch_account", "force_picker"])
    def test_the_escape_hatch_is_reachable_from_the_api(self, needle):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        assert needle in (root / "miniapp" / "api.py").read_text(encoding="utf-8")
