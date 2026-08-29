"""
Tests for services/webauthn_service.py - security-key registration and
sign-in.

The base64url helpers get the most attention here because everything else
rides on them: challenges, credential IDs and public keys are all stored as
base64url text and decoded again on the next request. A padding bug shows
up not as an exception but as a verification that always fails, which reads
like "your security key is wrong" to the user.

The `webauthn` library itself is mocked - it does real cryptography against
a real authenticator, which no test can stand in for.
"""
import base64
from unittest.mock import MagicMock, patch

import pytest

from services import webauthn_service


class TestBase64UrlHelpers:
    @pytest.mark.parametrize("size", range(1, 40))
    def test_round_trips_at_every_length(self, size):
        """Lengths not divisible by 3 are exactly the ones that need
        padding put back before decoding."""
        raw = bytes(range(size))
        assert webauthn_service._from_b64u(webauthn_service._b64u(raw)) == raw

    def test_encoding_is_unpadded(self):
        """WebAuthn's JSON uses unpadded base64url; trailing '=' is invalid
        there and some browsers reject it outright."""
        assert not webauthn_service._b64u(b"abc").endswith("=")
        assert "=" not in webauthn_service._b64u(bytes(range(10)))

    def test_uses_the_url_safe_alphabet(self):
        """Standard base64 would emit + and /, which break inside a URL and
        differ from what the browser sends back."""
        # 0xFB 0xFF produces '+/' under the standard alphabet.
        encoded = webauthn_service._b64u(b"\xfb\xff\xfe")
        assert "+" not in encoded and "/" not in encoded

    def test_decodes_what_a_browser_would_send(self):
        raw = b"\xfb\xff\xfe\x00\x10"
        browser_form = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        assert webauthn_service._from_b64u(browser_form) == raw

    def test_empty_bytes_round_trip(self):
        assert webauthn_service._from_b64u(webauthn_service._b64u(b"")) == b""


class TestRegistrationOptions:
    def test_returns_options_json_and_the_challenge_to_store(self):
        options = MagicMock(challenge=b"\x01\x02\x03")
        with patch.object(webauthn_service, "generate_registration_options", return_value=options), \
             patch.object(webauthn_service, "options_to_json", return_value='{"challenge":"AQID"}'):
            options_json, challenge_b64 = webauthn_service.build_registration_options(
                "42", "owner@carrier.com", []
            )

        assert options_json == '{"challenge":"AQID"}'
        # The stored challenge must decode back to exactly what was issued -
        # verification compares them byte for byte.
        assert webauthn_service._from_b64u(challenge_b64) == b"\x01\x02\x03"

    def test_already_enrolled_keys_are_excluded(self):
        """Without exclude_credentials the authenticator happily enrolls the
        same key twice, leaving a duplicate the user can't tell apart."""
        existing = [webauthn_service._b64u(b"cred-one"), webauthn_service._b64u(b"cred-two")]
        options = MagicMock(challenge=b"c")

        with patch.object(webauthn_service, "generate_registration_options", return_value=options) as gen, \
             patch.object(webauthn_service, "options_to_json", return_value="{}"):
            webauthn_service.build_registration_options("42", "owner@carrier.com", existing)

        excluded = gen.call_args.kwargs["exclude_credentials"]
        assert [descriptor.id for descriptor in excluded] == [b"cred-one", b"cred-two"]

    def test_user_id_is_passed_as_bytes(self):
        options = MagicMock(challenge=b"c")
        with patch.object(webauthn_service, "generate_registration_options", return_value=options) as gen, \
             patch.object(webauthn_service, "options_to_json", return_value="{}"):
            webauthn_service.build_registration_options("42", "owner@carrier.com", [])

        assert gen.call_args.kwargs["user_id"] == b"42"


class TestVerifyRegistration:
    def test_returns_only_values_that_are_safe_to_persist(self):
        verification = MagicMock(
            credential_id=b"new-cred", credential_public_key=b"pubkey", sign_count=0
        )
        with patch.object(webauthn_service, "parse_registration_credential_json"), \
             patch.object(webauthn_service, "verify_registration_response", return_value=verification):
            stored = webauthn_service.verify_registration("{}", webauthn_service._b64u(b"challenge"))

        assert set(stored) == {"credential_id", "public_key", "sign_count"}
        assert webauthn_service._from_b64u(stored["credential_id"]) == b"new-cred"
        assert webauthn_service._from_b64u(stored["public_key"]) == b"pubkey"
        assert stored["sign_count"] == 0

    def test_the_stored_challenge_is_decoded_before_comparison(self):
        """It goes to the DB as text and must come back as the original
        bytes, or every verification fails."""
        verification = MagicMock(credential_id=b"c", credential_public_key=b"p", sign_count=0)
        with patch.object(webauthn_service, "parse_registration_credential_json"), \
             patch.object(webauthn_service, "verify_registration_response", return_value=verification) as verify:
            webauthn_service.verify_registration("{}", webauthn_service._b64u(b"\x00\xff-expected"))

        assert verify.call_args.kwargs["expected_challenge"] == b"\x00\xff-expected"


class TestVerifyAuthentication:
    def test_returns_the_new_sign_count(self):
        """Persisting the incremented counter is what makes a cloned
        authenticator detectable on a later login."""
        with patch.object(webauthn_service, "parse_authentication_credential_json"), \
             patch.object(webauthn_service, "verify_authentication_response",
                          return_value=MagicMock(new_sign_count=7)):
            new_count = webauthn_service.verify_authentication(
                "{}", webauthn_service._b64u(b"chal"), webauthn_service._b64u(b"pubkey"), 6
            )

        assert new_count == 7

    def test_stored_key_and_counter_are_passed_through_for_checking(self):
        with patch.object(webauthn_service, "parse_authentication_credential_json"), \
             patch.object(webauthn_service, "verify_authentication_response",
                          return_value=MagicMock(new_sign_count=1)) as verify:
            webauthn_service.verify_authentication(
                "{}", webauthn_service._b64u(b"chal"), webauthn_service._b64u(b"stored-pubkey"), 5
            )

        kwargs = verify.call_args.kwargs
        assert kwargs["credential_public_key"] == b"stored-pubkey"
        assert kwargs["credential_current_sign_count"] == 5
        assert kwargs["expected_challenge"] == b"chal"

    def test_a_failed_assertion_propagates(self):
        """miniapp/api.py tries each enrolled key in turn and relies on a
        raise to move on to the next one."""
        with patch.object(webauthn_service, "parse_authentication_credential_json"), \
             patch.object(webauthn_service, "verify_authentication_response",
                          side_effect=ValueError("signature mismatch")):
            with pytest.raises(ValueError):
                webauthn_service.verify_authentication(
                    "{}", webauthn_service._b64u(b"c"), webauthn_service._b64u(b"p"), 0
                )
