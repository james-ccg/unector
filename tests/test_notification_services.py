"""
Tests for the three 2FA delivery channels (email, SMS, Telegram) plus the
email routing layer.

The behaviour that matters most here is the unconfigured path: every one of
these depends on credentials the operator may simply not have set, and the
app is built around them raising NotImplementedError so a missing provider
degrades to "that method isn't available" instead of a 500. The message
bodies are asserted too, since a code that never makes it into the text is
a silent lockout.

Every send is mocked at the transport (smtplib / aiogram / twilio); nothing
here opens a socket.
"""
from unittest.mock import MagicMock, patch

import pytest

from services import email_otp_service, email_service, sms_service, telegram_otp_service


# ------------------------------------------------------------------
# Email OTP (platform SMTP)
# ------------------------------------------------------------------
def _configure_smtp(monkeypatch):
    monkeypatch.setattr(email_otp_service, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_otp_service, "SMTP_PORT", 587)
    monkeypatch.setattr(email_otp_service, "SMTP_USERNAME", "bot@example.com")
    monkeypatch.setattr(email_otp_service, "SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(email_otp_service, "SMTP_FROM_EMAIL", "bot@example.com")


def _sent_message(smtp_mock) -> str:
    """The raw RFC-822 text handed to sendmail()."""
    return smtp_mock.return_value.__enter__.return_value.sendmail.call_args[0][2]


class TestEmailOtpConfiguration:
    def test_is_configured_requires_host_user_and_password(self, monkeypatch):
        _configure_smtp(monkeypatch)
        assert email_otp_service.is_configured() is True

    @pytest.mark.parametrize("missing", ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"])
    def test_is_configured_is_false_when_any_piece_is_missing(self, monkeypatch, missing):
        _configure_smtp(monkeypatch)
        monkeypatch.setattr(email_otp_service, missing, "")
        assert email_otp_service.is_configured() is False

    @pytest.mark.parametrize("send", [
        lambda: email_otp_service.send_otp_email("user@example.com", "123456"),
        lambda: email_otp_service.send_registration_verification_email(
            "user@example.com", "123456", "https://example.com/verify"),
        lambda: email_otp_service.send_password_reset_email(
            "user@example.com", "https://example.com/reset"),
    ])
    def test_every_send_raises_not_implemented_when_unconfigured(self, monkeypatch, send):
        monkeypatch.setattr(email_otp_service, "SMTP_HOST", "")
        with pytest.raises(NotImplementedError, match="SMTP_HOST"):
            send()


class TestEmailOtpMessages:
    def test_otp_email_carries_the_code_in_body_and_subject(self, monkeypatch):
        _configure_smtp(monkeypatch)
        with patch("smtplib.SMTP") as smtp:
            email_otp_service.send_otp_email("user@example.com", "654321")

        message = _sent_message(smtp)
        assert "654321" in message
        assert "Subject: 654321 is your Freight Pilot verification code" in message

    def test_otp_email_goes_to_the_requested_address(self, monkeypatch):
        _configure_smtp(monkeypatch)
        with patch("smtplib.SMTP") as smtp:
            email_otp_service.send_otp_email("driver@carrier.com", "111111")

        to_addresses = smtp.return_value.__enter__.return_value.sendmail.call_args[0][1]
        assert to_addresses == ["driver@carrier.com"]

    def test_connection_is_upgraded_to_tls_and_authenticated(self, monkeypatch):
        """Credentials must never cross the wire before starttls()."""
        _configure_smtp(monkeypatch)
        with patch("smtplib.SMTP") as smtp:
            email_otp_service.send_otp_email("user@example.com", "222222")

        server = smtp.return_value.__enter__.return_value
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("bot@example.com", "app-password")

    def test_registration_email_offers_both_the_code_and_the_link(self, monkeypatch):
        """Registration deliberately gives two ways to confirm - dropping
        either one strands anyone whose client mangles the other."""
        _configure_smtp(monkeypatch)
        with patch("smtplib.SMTP") as smtp:
            email_otp_service.send_registration_verification_email(
                "new@example.com", "987654", "https://freightpilot.app/verify?t=abc"
            )

        message = _sent_message(smtp)
        assert "987654" in message
        assert "https://freightpilot.app/verify?t=abc" in message

    def test_password_reset_email_carries_the_link(self, monkeypatch):
        _configure_smtp(monkeypatch)
        with patch("smtplib.SMTP") as smtp:
            email_otp_service.send_password_reset_email(
                "owner@carrier.com", "https://freightpilot.app/reset-password?token=xyz"
            )

        message = _sent_message(smtp)
        assert "https://freightpilot.app/reset-password?token=xyz" in message
        assert "Subject: Reset your Freight Pilot password" in message

    def test_password_reset_email_contains_no_code(self, monkeypatch):
        """This flow is link-only - a stray code would imply an entry box
        that doesn't exist."""
        _configure_smtp(monkeypatch)
        with patch("smtplib.SMTP") as smtp:
            email_otp_service.send_password_reset_email("owner@x.com", "https://x.com/r?token=t")

        assert "verification code" not in _sent_message(smtp)


# ------------------------------------------------------------------
# SMS OTP (optional paid provider)
# ------------------------------------------------------------------
class TestSmsOtp:
    def test_not_configured_by_default(self, monkeypatch):
        """SMS is the one channel with no free option, so an operator who
        set nothing must get a clear "not set up", never a crash."""
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "")
        assert sms_service.is_configured() is False

    def test_twilio_needs_all_three_settings(self, monkeypatch):
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "twilio")
        monkeypatch.setattr(sms_service, "TWILIO_ACCOUNT_SID", "AC123")
        monkeypatch.setattr(sms_service, "TWILIO_AUTH_TOKEN", "token")
        monkeypatch.setattr(sms_service, "TWILIO_FROM_NUMBER", "")
        assert sms_service.is_configured() is False

        monkeypatch.setattr(sms_service, "TWILIO_FROM_NUMBER", "+15550001111")
        assert sms_service.is_configured() is True

    def test_an_unknown_provider_is_not_treated_as_configured(self, monkeypatch):
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "some-other-gateway")
        assert sms_service.is_configured() is False

    def test_send_raises_not_implemented_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "")
        with pytest.raises(NotImplementedError, match="SMS OTP isn't configured"):
            sms_service.send_otp_sms("+15551234567", "123456")

    def test_the_error_points_at_the_channels_that_do_work(self, monkeypatch):
        """Whoever hits this is locked out of SMS; the message is the only
        place that tells them a free alternative exists."""
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "")
        with pytest.raises(NotImplementedError) as exc:
            sms_service.send_otp_sms("+15551234567", "123456")

        text = str(exc.value)
        assert "Authenticator" in text and "Telegram" in text and "email" in text

    def test_twilio_send_passes_the_code_and_from_number(self, monkeypatch):
        monkeypatch.setattr(sms_service, "SMS_PROVIDER", "twilio")
        monkeypatch.setattr(sms_service, "TWILIO_ACCOUNT_SID", "AC123")
        monkeypatch.setattr(sms_service, "TWILIO_AUTH_TOKEN", "token")
        monkeypatch.setattr(sms_service, "TWILIO_FROM_NUMBER", "+15550001111")

        client_cls = MagicMock()
        twilio_rest = MagicMock(Client=client_cls)
        with patch.dict("sys.modules", {"twilio": MagicMock(), "twilio.rest": twilio_rest}):
            sms_service.send_otp_sms("+15559876543", "424242")

        kwargs = client_cls.return_value.messages.create.call_args.kwargs
        assert "424242" in kwargs["body"]
        assert kwargs["from_"] == "+15550001111"
        assert kwargs["to"] == "+15559876543"


# ------------------------------------------------------------------
# Telegram OTP (uses the bot we already run)
# ------------------------------------------------------------------
class TestTelegramOtp:
    @pytest.mark.asyncio
    async def test_sends_the_code_to_the_linked_account(self):
        bot = MagicMock()
        bot.send_message = MagicMock(return_value=_async_none())
        bot.session.close = MagicMock(return_value=_async_none())

        with patch.object(telegram_otp_service, "Bot", return_value=bot):
            await telegram_otp_service.send_otp_telegram(555000111, "313131")

        args, kwargs = bot.send_message.call_args
        assert args[0] == 555000111
        assert "313131" in args[1]
        assert kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_the_session_is_closed_even_when_sending_fails(self):
        """aiogram holds an aiohttp session; leaking one per failed OTP
        attempt would slowly exhaust connections on the running bot."""
        bot = MagicMock()
        bot.send_message = MagicMock(side_effect=RuntimeError("chat not found"))
        bot.session.close = MagicMock(return_value=_async_none())

        with patch.object(telegram_otp_service, "Bot", return_value=bot):
            with pytest.raises(RuntimeError):
                await telegram_otp_service.send_otp_telegram(555000111, "313131")

        bot.session.close.assert_called_once()


def _async_none():
    async def _coro():
        return None
    return _coro()


# ------------------------------------------------------------------
# Email routing layer
# ------------------------------------------------------------------
class TestEmailServiceRouting:
    """email_service is a thin indirection over gmail_service so bot.py
    doesn't bind to one provider. These assert it actually forwards, since
    a broken passthrough here silently breaks RC lookup and POD delivery."""

    def test_find_rc_pdf_forwards_every_argument(self):
        with patch.object(email_service.gmail_service, "find_rc_pdf_by_load_id") as inner:
            inner.return_value = b"%PDF"
            assert email_service.find_rc_pdf_by_load_id(7, "12345") == b"%PDF"

        inner.assert_called_once_with(7, "12345")

    def test_send_email_forwards_every_argument(self):
        attachments = [{"filename": "pod.pdf", "data": b"x", "mime_type": "application/pdf"}]
        with patch.object(email_service.gmail_service, "send_email") as inner:
            email_service.send_email(7, "broker@example.com", "POD", "body", attachments)

        inner.assert_called_once_with(7, "broker@example.com", "POD", "body", attachments)

    def test_send_email_defaults_attachments_to_none(self):
        with patch.object(email_service.gmail_service, "send_email") as inner:
            email_service.send_email(7, "broker@example.com", "Subject", "body")

        assert inner.call_args[0][4] is None
