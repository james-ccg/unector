"""
Tests for the four notification channels - email OTP, SMS OTP, Telegram OTP,
and the email routing layer.

None of these can be tested against the real thing: sending would mean a live
SMTP login, a billed Twilio message, or a Telegram API call. What's worth
covering is the logic around the send, which is where the bugs actually are:

  - the "not configured" guards, which the whole app relies on to degrade
    gracefully instead of crashing when an optional channel isn't set up;
  - that the code being delivered actually reaches the message body, and that
    the message is addressed to the right recipient;
  - that connections get closed even when the send fails, since a leaked SMTP
    or aiogram session is the kind of fault that only shows up under load.

The transports themselves (smtplib, twilio, aiogram) are stubbed - they're
third-party code with their own test suites, and exercising them here would
test the network, not this project.
"""
from unittest.mock import MagicMock

import pytest

from services import email_otp_service, email_service, sms_service, telegram_otp_service


# ------------------------------------------------------------------
# Email OTP (platform SMTP - login security, not a company's own inbox)
# ------------------------------------------------------------------
class TestEmailOtpService:
    def _configure(self, monkeypatch):
        for name, value in [
            ("SMTP_HOST", "smtp.example.com"),
            ("SMTP_PORT", 587),
            ("SMTP_USERNAME", "bot@example.com"),
            ("SMTP_PASSWORD", "app-password"),
            ("SMTP_FROM_EMAIL", "bot@example.com"),
        ]:
            monkeypatch.setattr(email_otp_service, name, value)

    def _capture_smtp(self, monkeypatch):
        """Stands in for smtplib.SMTP, recording what would have been sent."""
        server = MagicMock()
        # The module uses `with smtplib.SMTP(...) as server`, so the context
        # manager has to hand back the same mock the assertions look at.
        server.__enter__.return_value = server
        monkeypatch.setattr(email_otp_service.smtplib, "SMTP", MagicMock(return_value=server))
        return server

    @pytest.mark.parametrize("missing", ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"])
    def test_is_not_configured_when_any_credential_is_missing(self, monkeypatch, missing):
        self._configure(monkeypatch)
        monkeypatch.setattr(email_otp_service, missing, "")
        assert email_otp_service.is_configured() is False

    def test_is_configured_with_all_credentials(self, monkeypatch):
        self._configure(monkeypatch)
        assert email_otp_service.is_configured() is True

    def test_sending_unconfigured_raises_not_implemented(self, monkeypatch):
        monkeypatch.setattr(email_otp_service, "SMTP_HOST", "")
        with pytest.raises(NotImplementedError):
            email_otp_service.send_otp_email("owner@example.com", "123456")

    def test_otp_email_carries_the_code_and_the_recipient(self, monkeypatch):
        self._configure(monkeypatch)
        server = self._capture_smtp(monkeypatch)

        email_otp_service.send_otp_email("owner@example.com", "654321")

        server.starttls.assert_called_once()
        server.login.assert_called_once_with("bot@example.com", "app-password")
        from_addr, recipients, raw = server.sendmail.call_args[0]
        assert recipients == ["owner@example.com"]
        assert from_addr == "bot@example.com"
        # The code has to be in the body, not only the subject - some clients
        # truncate long subjects, and it's the body people copy from.
        assert "654321" in raw

    def test_registration_email_carries_both_the_code_and_the_link(self, monkeypatch):
        self._configure(monkeypatch)
        server = self._capture_smtp(monkeypatch)

        email_otp_service.send_registration_verification_email(
            "new@example.com", "112233", "https://app.example.com/verify?token=abc"
        )

        _from, recipients, raw = server.sendmail.call_args[0]
        assert recipients == ["new@example.com"]
        assert "112233" in raw
        # Registration offers two ways to verify; dropping either one strands
        # whichever the visitor tries to use.
        assert "verify?token=abc" in raw.replace("=\n", "")

    def test_password_reset_email_carries_the_reset_link(self, monkeypatch):
        self._configure(monkeypatch)
        server = self._capture_smtp(monkeypatch)

        email_otp_service.send_password_reset_email(
            "owner@example.com", "https://app.example.com/reset-password?token=xyz"
        )

        _from, recipients, raw = server.sendmail.call_args[0]
        assert recipients == ["owner@example.com"]
        assert "reset-password?token=xyz" in raw.replace("=\n", "")

    def test_smtp_connection_is_closed_even_when_sending_fails(self, monkeypatch):
        """`with smtplib.SMTP(...)` must still tear the connection down on a
        failed send - otherwise a flaky mail host leaks a socket per attempt."""
        self._configure(monkeypatch)
        server = self._capture_smtp(monkeypatch)
        server.sendmail.side_effect = OSError("mail server refused")

        with pytest.raises(OSError):
            email_otp_service.send_otp_email("owner@example.com", "999999")

        server.__exit__.assert_called_once()


# ------------------------------------------------------------------
# SMS OTP (the only channel that needs a paid account)
# ------------------------------------------------------------------
class TestSmsService:
    def test_not_configured_without_a_provider(self, monkeypatch):
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "")
        assert sms_service.is_configured() is False

    def test_not_configured_when_twilio_credentials_are_incomplete(self, monkeypatch):
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "twilio")
        monkeypatch.setattr(sms_service, "TWILIO_ACCOUNT_SID", "AC123")
        monkeypatch.setattr(sms_service, "TWILIO_AUTH_TOKEN", "")
        monkeypatch.setattr(sms_service, "TWILIO_FROM_NUMBER", "+15550100")
        assert sms_service.is_configured() is False

    def test_configured_with_full_twilio_credentials(self, monkeypatch):
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "twilio")
        monkeypatch.setattr(sms_service, "TWILIO_ACCOUNT_SID", "AC123")
        monkeypatch.setattr(sms_service, "TWILIO_AUTH_TOKEN", "secret")
        monkeypatch.setattr(sms_service, "TWILIO_FROM_NUMBER", "+15550100")
        assert sms_service.is_configured() is True

    def test_unknown_provider_is_treated_as_unconfigured(self, monkeypatch):
        """A typo in SMS_PROVIDER must fail closed. Falling through to "send"
        with no provider wired up would raise something unrelated deep in the
        2FA flow instead of the actionable "SMS isn't set up" message."""
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "nexmo")
        assert sms_service.is_configured() is False
        with pytest.raises(NotImplementedError):
            sms_service.send_otp_sms("+15550111", "123456")

    def test_unconfigured_send_explains_the_free_alternatives(self, monkeypatch):
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "")
        with pytest.raises(NotImplementedError) as excinfo:
            sms_service.send_otp_sms("+15550111", "123456")
        # The whole point of this message is that the owner has three other
        # working options and shouldn't go buy an SMS plan to get 2FA.
        message = str(excinfo.value).lower()
        assert "telegram" in message and "email" in message


# ------------------------------------------------------------------
# Telegram OTP (free - reuses the bot we already run)
# ------------------------------------------------------------------
class TestTelegramOtpService:
    @pytest.mark.asyncio
    async def test_sends_the_code_to_the_linked_account(self, monkeypatch):
        bot = MagicMock()
        sent = {}

        async def fake_send_message(user_id, text, **kwargs):
            sent["user_id"] = user_id
            sent["text"] = text
            sent["kwargs"] = kwargs

        async def fake_close():
            sent["closed"] = True

        bot.send_message = fake_send_message
        bot.session.close = fake_close
        monkeypatch.setattr(telegram_otp_service, "Bot", MagicMock(return_value=bot))

        await telegram_otp_service.send_otp_telegram(987654321, "246810")

        assert sent["user_id"] == 987654321
        assert "246810" in sent["text"]
        # Sent as HTML because the code is wrapped in <code> - without the
        # parse mode the user sees the literal tags.
        assert sent["kwargs"]["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_session_is_closed_even_when_the_send_fails(self, monkeypatch):
        """aiogram opens an aiohttp session per Bot instance. This module
        builds a fresh one per code, so a send that raises without closing
        leaks a connector every failed 2FA attempt."""
        bot = MagicMock()
        closed = {"value": False}

        async def fake_send_message(*_args, **_kwargs):
            raise RuntimeError("chat not found")

        async def fake_close():
            closed["value"] = True

        bot.send_message = fake_send_message
        bot.session.close = fake_close
        monkeypatch.setattr(telegram_otp_service, "Bot", MagicMock(return_value=bot))

        with pytest.raises(RuntimeError):
            await telegram_otp_service.send_otp_telegram(1, "000000")

        assert closed["value"] is True


# ------------------------------------------------------------------
# email_service - the thin routing layer over the per-company inbox
# ------------------------------------------------------------------
class TestEmailServiceRouting:
    """This module exists so bot.py never imports gmail_service directly,
    leaving room to add another provider later. The only behaviour it has is
    forwarding, so that's what's checked - including that arguments survive
    the hop, which is the one thing a pass-through can get wrong."""

    def test_find_rc_pdf_forwards_to_gmail(self, monkeypatch):
        called = {}

        def fake_find(company_id, load_id):
            called["args"] = (company_id, load_id)
            return b"%PDF-"

        monkeypatch.setattr(email_service.gmail_service, "find_rc_pdf_by_load_id", fake_find)

        result = email_service.find_rc_pdf_by_load_id(7, "12345")
        assert called["args"] == (7, "12345")
        assert result == b"%PDF-"

    def test_send_email_forwards_every_argument(self, monkeypatch):
        called = {}

        def fake_send(company_id, to_address, subject, body, attachments=None):
            called["args"] = (company_id, to_address, subject, body, attachments)

        monkeypatch.setattr(email_service.gmail_service, "send_email", fake_send)

        email_service.send_email(3, "broker@example.com", "POD", "Attached.", [("pod.pdf", b"x")])

        assert called["args"] == (
            3, "broker@example.com", "POD", "Attached.", [("pod.pdf", b"x")],
        )

    def test_send_email_defaults_attachments_to_none(self, monkeypatch):
        """Most sends have no attachment; the default has to survive the hop
        or gmail_service receives a positional None it didn't expect."""
        called = {}

        def fake_send(company_id, to_address, subject, body, attachments=None):
            called["attachments"] = attachments

        monkeypatch.setattr(email_service.gmail_service, "send_email", fake_send)

        email_service.send_email(1, "b@example.com", "Subject", "Body")
        assert called["attachments"] is None
