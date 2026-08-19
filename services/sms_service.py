"""
Sends 2FA one-time codes by SMS. This needs a paid SMS provider account -
unlike TOTP, Telegram OTP, and recovery codes, there's no free way to send
a real text message to an arbitrary phone number.

Only Twilio is wired up here as a concrete example. To use it:
    pip install twilio
    Set SMS_PROVIDER=twilio, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER in .env.

If SMS_PROVIDER is left empty (the default), this raises NotImplementedError
so the rest of the app can handle "SMS isn't set up" gracefully instead of
crashing.
"""
from config import SMS_PROVIDER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER


def is_configured() -> bool:
    if SMS_PROVIDER == "twilio":
        return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)
    return False


def send_otp_sms(to_phone_number: str, code: str) -> None:
    if not is_configured():
        raise NotImplementedError(
            "SMS OTP isn't configured. This needs a paid SMS provider account - "
            "set SMS_PROVIDER=twilio plus TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "and TWILIO_FROM_NUMBER in .env, and `pip install twilio`. "
            "In the meantime, Authenticator app, Telegram, and email OTP work with no paid service."
        )

    if SMS_PROVIDER == "twilio":
        _send_via_twilio(to_phone_number, code)


def _send_via_twilio(to_phone_number: str, code: str) -> None:
    try:
        from twilio.rest import Client
    except ImportError as e:
        raise NotImplementedError(
            "The 'twilio' package isn't installed. Run: pip install twilio"
        ) from e

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(
        body=f"Your Freight Pilot verification code is: {code}",
        from_=TWILIO_FROM_NUMBER,
        to=to_phone_number,
    )
