"""
WebAuthn / FIDO2 (security keys, Touch ID, Windows Hello). Works with no
paid third-party service - the browser and the authenticator handle the
cryptography, this module just generates challenges and verifies the
signed responses using the `webauthn` package.

Note: this is the trickiest 2FA method to get exactly right without a real
browser + physical authenticator to test against. If registration or
verification fails in a way that looks like a library/API mismatch rather
than a wrong code, check that the installed `webauthn` package version
matches the function signatures used below (pip install webauthn).
"""
import base64

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
)
from webauthn.helpers import parse_registration_credential_json, parse_authentication_credential_json

from config import WEBAUTHN_RP_ID, WEBAUTHN_RP_NAME, WEBAUTHN_ORIGIN


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _from_b64u(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


# ------------------------------------------------------------------
# Registration (adding a new security key)
# ------------------------------------------------------------------
def build_registration_options(user_id: str, account_label: str, existing_credential_ids: list[str]) -> tuple[str, str]:
    """Returns (options_json_for_frontend, challenge_b64url_to_store)."""
    options = generate_registration_options(
        rp_id=WEBAUTHN_RP_ID,
        rp_name=WEBAUTHN_RP_NAME,
        user_id=user_id.encode(),
        user_name=account_label,
        user_display_name=account_label,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=_from_b64u(cred_id)) for cred_id in existing_credential_ids
        ],
    )
    challenge_b64 = _b64u(options.challenge)
    return options_to_json(options), challenge_b64


def verify_registration(credential_json: str, expected_challenge_b64: str) -> dict:
    """Verifies the browser's registration response. Returns a dict ready
    to store: {credential_id, public_key, sign_count} (all safe to persist)."""
    credential = parse_registration_credential_json(credential_json)
    verification = verify_registration_response(
        credential=credential,
        expected_challenge=_from_b64u(expected_challenge_b64),
        expected_origin=WEBAUTHN_ORIGIN,
        expected_rp_id=WEBAUTHN_RP_ID,
    )
    return {
        "credential_id": _b64u(verification.credential_id),
        "public_key": _b64u(verification.credential_public_key),
        "sign_count": verification.sign_count,
    }


# ------------------------------------------------------------------
# Authentication (using a security key to log in / complete 2FA)
# ------------------------------------------------------------------
def build_authentication_options(allowed_credential_ids: list[str]) -> tuple[str, str]:
    """Returns (options_json_for_frontend, challenge_b64url_to_store)."""
    options = generate_authentication_options(
        rp_id=WEBAUTHN_RP_ID,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=_from_b64u(cred_id)) for cred_id in allowed_credential_ids
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    challenge_b64 = _b64u(options.challenge)
    return options_to_json(options), challenge_b64


def verify_authentication(
    credential_json: str,
    expected_challenge_b64: str,
    stored_public_key_b64: str,
    stored_sign_count: int,
) -> int:
    """Verifies a security-key sign-in response. Returns the new sign_count
    to persist (helps detect cloned authenticators on future logins)."""
    credential = parse_authentication_credential_json(credential_json)
    verification = verify_authentication_response(
        credential=credential,
        expected_challenge=_from_b64u(expected_challenge_b64),
        expected_origin=WEBAUTHN_ORIGIN,
        expected_rp_id=WEBAUTHN_RP_ID,
        credential_public_key=_from_b64u(stored_public_key_b64),
        credential_current_sign_count=stored_sign_count,
    )
    return verification.new_sign_count
