"""
Tests for services/google_identity_service.py - the "Continue with Google"
sign-in.

This module decides who someone is, so the tests concentrate on the checks
that make that claim trustworthy rather than on the happy path alone:

  - it must request ONLY the identity scopes. Quietly widening these to the
    Gmail ones would drag sign-in into Google's restricted-scope verification
    and hand the app inbox access it has no reason to hold;
  - it must reject an unverified address. Google will happily return an
    `email` claim for an account that never proved it owns the address, and
    trusting it would let anyone sign in as anyone by registering that
    address on a throwaway Google account;
  - it must not fall back to unsigned data when no id_token comes back.

Google's own libraries are stubbed - the point is this module's decisions,
not Google's token verification, which has its own test suite.
"""
from unittest.mock import MagicMock

import pytest

from services import google_identity_service as identity


class TestScopes:
    def test_requests_only_identity_scopes(self):
        assert identity.SCOPES == ["openid", "https://www.googleapis.com/auth/userinfo.email"]

    def test_never_requests_gmail_access(self):
        """Sign-in and the Gmail integration are deliberately separate OAuth
        grants - see the module docstring. If these ever merge, signing in
        starts demanding inbox access and needs a CASA security assessment."""
        assert not any("gmail" in scope for scope in identity.SCOPES)


class TestAuthorizationUrl:
    def test_passes_state_through_and_prompts_for_account_choice(self, monkeypatch):
        captured = {}

        class FakeFlow:
            def authorization_url(self, **kwargs):
                captured.update(kwargs)
                return "https://accounts.google.com/o/oauth2/auth?x=1", "ignored-state"

        monkeypatch.setattr(identity, "_build_flow", lambda redirect_uri: FakeFlow())

        url = identity.build_authorization_url("https://app.example.com/cb", "signed-state")

        assert url.startswith("https://accounts.google.com/")
        assert captured["state"] == "signed-state"
        # Without select_account, a browser already signed into one Google
        # account silently reuses it, which is surprising on a shared machine.
        assert captured["prompt"] == "select_account"

    def test_does_not_request_offline_access(self, monkeypatch):
        """Sign-in needs a one-shot identity assertion. Asking for offline
        access would have Google mint a refresh token this flow never uses -
        a stored long-lived credential with no purpose is just exposure."""
        captured = {}

        class FakeFlow:
            def authorization_url(self, **kwargs):
                captured.update(kwargs)
                return "https://accounts.google.com/", "s"

        monkeypatch.setattr(identity, "_build_flow", lambda redirect_uri: FakeFlow())
        identity.build_authorization_url("https://app.example.com/cb", "state")

        assert "access_type" not in captured


class TestExchangeCodeForEmail:
    def _flow_returning(self, monkeypatch, id_token):
        flow = MagicMock()
        flow.credentials.id_token = id_token
        monkeypatch.setattr(identity, "_build_flow", lambda redirect_uri: flow)
        return flow

    def _claims(self, monkeypatch, claims):
        monkeypatch.setattr(
            identity.google_id_token, "verify_oauth2_token",
            lambda raw, request, client_id: claims,
        )

    def test_returns_the_verified_address(self, monkeypatch):
        self._flow_returning(monkeypatch, "signed.jwt.here")
        self._claims(monkeypatch, {"email": "owner@example.com", "email_verified": True})

        assert identity.exchange_code_for_email("code", "https://app.example.com/cb") == "owner@example.com"

    def test_normalises_case(self, monkeypatch):
        """Stored company emails are lowercased, so an address that comes back
        capitalised has to match the same way or sign-in silently finds no
        account for a user who plainly has one."""
        self._flow_returning(monkeypatch, "signed.jwt.here")
        self._claims(monkeypatch, {"email": "  Owner@Example.COM ", "email_verified": True})

        assert identity.exchange_code_for_email("code", "https://app.example.com/cb") == "owner@example.com"

    def test_rejects_an_unverified_address(self, monkeypatch):
        """The security check that matters most here. Google returns `email`
        even when the account never proved ownership; accepting it would let
        anyone sign in as anyone by adding that address to a fresh account."""
        self._flow_returning(monkeypatch, "signed.jwt.here")
        self._claims(monkeypatch, {"email": "victim@example.com", "email_verified": False})

        assert identity.exchange_code_for_email("code", "https://app.example.com/cb") is None

    def test_returns_none_when_google_sends_no_id_token(self, monkeypatch):
        """No signed token means nothing to verify. Falling back to any
        unsigned part of the response would be trusting the caller."""
        self._flow_returning(monkeypatch, None)

        assert identity.exchange_code_for_email("code", "https://app.example.com/cb") is None

    def test_returns_none_when_the_token_carries_no_email(self, monkeypatch):
        self._flow_returning(monkeypatch, "signed.jwt.here")
        self._claims(monkeypatch, {"email_verified": True})

        assert identity.exchange_code_for_email("code", "https://app.example.com/cb") is None

    def test_verification_failure_propagates(self, monkeypatch):
        """A token that fails signature/audience verification is an error, not
        a "no account" answer - swallowing it into None would make a forged
        token indistinguishable from an unknown user."""
        self._flow_returning(monkeypatch, "tampered.jwt")

        def boom(raw, request, client_id):
            raise ValueError("Token has wrong audience")

        monkeypatch.setattr(identity.google_id_token, "verify_oauth2_token", boom)

        with pytest.raises(ValueError):
            identity.exchange_code_for_email("code", "https://app.example.com/cb")

    def test_token_is_verified_against_our_own_client_id(self, monkeypatch):
        """Checking the audience is what stops a valid Google token issued to
        some *other* application being replayed here."""
        self._flow_returning(monkeypatch, "signed.jwt.here")
        seen = {}

        def capture(raw, request, client_id):
            seen["client_id"] = client_id
            return {"email": "owner@example.com", "email_verified": True}

        monkeypatch.setattr(identity.google_id_token, "verify_oauth2_token", capture)
        monkeypatch.setattr(identity, "GOOGLE_CLIENT_ID", "our-client-id.apps.googleusercontent.com")

        identity.exchange_code_for_email("code", "https://app.example.com/cb")

        assert seen["client_id"] == "our-client-id.apps.googleusercontent.com"
