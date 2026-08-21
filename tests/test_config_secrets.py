"""
config.py refuses to boot in production with weak/missing secrets, rather
than starting successfully and only failing later (a forgeable JWT, or a
RuntimeError on first credential encryption). This is a module-import-time
check, so it has to be exercised in a subprocess - importing config.py
directly in this process would only run it once, before any test gets a
chance to vary the environment.
"""
import os
import pathlib
import subprocess
import sys

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent


def _run_import_config(env_overrides: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=_PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


class TestProductionSecretCheck:
    def test_refuses_to_start_with_dev_default_jwt_secret(self):
        result = _run_import_config({
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "dev-only-change-me-before-going-live",
            "FERNET_MASTER_KEY": "kX8u2z8P3sVXvnQwJk4xJmYQ2wq2t9s5C1c8H9nq2vE=",
        })
        assert result.returncode != 0
        assert "insecure secrets" in result.stderr

    def test_refuses_to_start_with_missing_fernet_key(self):
        result = _run_import_config({
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "a" * 64,
            "FERNET_MASTER_KEY": "",
        })
        assert result.returncode != 0
        assert "FERNET_MASTER_KEY" in result.stderr

    def test_starts_normally_with_proper_production_secrets(self):
        from cryptography.fernet import Fernet

        result = _run_import_config({
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "a" * 64,
            "FERNET_MASTER_KEY": Fernet.generate_key().decode(),
        })
        assert result.returncode == 0, result.stderr

    def test_dev_default_is_fine_outside_production(self):
        result = _run_import_config({
            "ENVIRONMENT": "development",
            "JWT_SECRET_KEY": "dev-only-change-me-before-going-live",
        })
        assert result.returncode == 0, result.stderr

    def test_refuses_to_start_with_stripe_key_but_no_webhook_secret(self):
        """A STRIPE_SECRET_KEY with no matching STRIPE_WEBHOOK_SECRET means
        every subscription lifecycle webhook (upgrades, cancellations,
        failed payments) would silently fail signature verification -
        checkout itself doesn't need the webhook, so this would look fine
        until a company's subscription state quietly stops updating."""
        from cryptography.fernet import Fernet

        result = _run_import_config({
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "a" * 64,
            "FERNET_MASTER_KEY": Fernet.generate_key().decode(),
            "STRIPE_SECRET_KEY": "sk_live_fake_for_test",
            "STRIPE_WEBHOOK_SECRET": "",
        })
        assert result.returncode != 0
        assert "STRIPE_WEBHOOK_SECRET" in result.stderr

    def test_starts_normally_with_stripe_billing_fully_configured(self):
        from cryptography.fernet import Fernet

        result = _run_import_config({
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "a" * 64,
            "FERNET_MASTER_KEY": Fernet.generate_key().decode(),
            "STRIPE_SECRET_KEY": "sk_live_fake_for_test",
            "STRIPE_WEBHOOK_SECRET": "whsec_fake_for_test",
        })
        assert result.returncode == 0, result.stderr

    def test_refuses_to_start_with_samsara_test_mode_enabled(self):
        """SAMSARA_TEST_MODE fabricates GPS data - left on in production, it
        would fire real proximity alerts to real driver Telegram groups
        using fake coordinates, with nothing distinguishing them from
        genuine ones."""
        from cryptography.fernet import Fernet

        result = _run_import_config({
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "a" * 64,
            "FERNET_MASTER_KEY": Fernet.generate_key().decode(),
            "SAMSARA_TEST_MODE": "true",
        })
        assert result.returncode != 0
        assert "SAMSARA_TEST_MODE" in result.stderr
