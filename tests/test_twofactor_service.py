"""
services/twofactor_service.py's verify_totp_code - specifically its replay
protection. A raw TOTP secret is normally valid for a ~90s window
(current step +/- 1 for clock drift), so without tracking the last step a
code was accepted at, a single observed/leaked code (shoulder-surfed, a
log line, a MITM'd request) could be replayed successfully for that whole
window. verify_totp_code rejects any step <= the caller-supplied
last_used_step to close that off.
"""
import pyotp

from config import encrypt_value
from services import twofactor_service


def _make_encrypted_secret() -> tuple[str, pyotp.TOTP]:
    secret = pyotp.random_base32()
    return encrypt_value(secret), pyotp.TOTP(secret)


class TestVerifyTotpCode:
    def test_correct_code_with_no_prior_step_is_accepted(self):
        encrypted_secret, totp = _make_encrypted_secret()
        step = twofactor_service.verify_totp_code(encrypted_secret, totp.now())
        assert step is not None

    def test_wrong_code_is_rejected(self):
        encrypted_secret, totp = _make_encrypted_secret()
        # A code that (almost certainly) doesn't match any of the three
        # accepted steps (current, +/-1).
        wrong = "000000" if totp.now() != "000000" else "111111"
        assert twofactor_service.verify_totp_code(encrypted_secret, wrong) is None

    def test_replaying_the_same_code_is_rejected(self):
        encrypted_secret, totp = _make_encrypted_secret()
        code = totp.now()

        first_step = twofactor_service.verify_totp_code(encrypted_secret, code)
        assert first_step is not None

        # Same code, now passed back as "already used" - must be rejected
        # even though it's still within its normal +/-1 step validity window.
        replayed_step = twofactor_service.verify_totp_code(encrypted_secret, code, last_used_step=first_step)
        assert replayed_step is None

    def test_a_new_code_after_a_used_step_is_still_accepted(self):
        encrypted_secret, totp = _make_encrypted_secret()
        code = totp.now()
        first_step = twofactor_service.verify_totp_code(encrypted_secret, code)
        assert first_step is not None

        # An older/equal step must never verify again, regardless of code.
        assert twofactor_service.verify_totp_code(encrypted_secret, code, last_used_step=first_step + 1) is None
