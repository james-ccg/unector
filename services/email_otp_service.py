"""
Sends 2FA one-time codes by email via plain SMTP. This is separate from
services/gmail_service.py, which is a per-company OAuth connection used for
Rate Confirmation processing - this module is platform-level (login
security), so it uses one fixed SMTP account configured by whoever runs
the server, not each company's own inbox.

A Gmail "app password" (myaccount.google.com/apppasswords) works fine as
SMTP_USERNAME/SMTP_PASSWORD for development. Any standard SMTP provider
(SendGrid, Postmark, your own mail server, etc.) works too.
"""
import smtplib
from email.mime.text import MIMEText

from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, FRONTEND_URL,
)


def is_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD)


def send_otp_email(to_address: str, code: str) -> None:
    if not is_configured():
        raise NotImplementedError(
            "Email OTP isn't configured yet. Set SMTP_HOST, SMTP_USERNAME, and "
            "SMTP_PASSWORD in .env (a Gmail app password works fine for this)."
        )

    body = (
        f"Your Freight Pilot verification code is: {code}\n\n"
        "This code expires in 10 minutes. If you didn't request this, you can "
        "safely ignore this email."
    )
    message = MIMEText(body)
    message["Subject"] = f"{code} is your Freight Pilot verification code"
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = to_address

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, [to_address], message.as_string())


def send_registration_verification_email(to_address: str, code: str, verify_url: str) -> None:
    """Confirms the visitor actually controls the Gmail inbox they just
    connected during registration - sent right after the OAuth callback,
    before any Company row exists. Gives both a code and a link so either
    works, whichever's more convenient."""
    if not is_configured():
        raise NotImplementedError(
            "Email isn't configured yet. Set SMTP_HOST, SMTP_USERNAME, and "
            "SMTP_PASSWORD in .env (a Gmail app password works fine for this)."
        )

    body = (
        "Thanks for signing up for Freight Pilot! Confirm this is your inbox to finish "
        "creating your account.\n\n"
        f"Click here to confirm: {verify_url}\n\n"
        f"Or enter this code on the registration page: {code}\n\n"
        "This expires in 1 hour. If you didn't start signing up for Freight Pilot, you can "
        "safely ignore this email."
    )
    message = MIMEText(body)
    message["Subject"] = f"{code} - Confirm your email for Freight Pilot"
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = to_address

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, [to_address], message.as_string())


def send_password_reset_email(to_address: str, reset_url: str) -> None:
    """Sends an owner a one-time link to set a new password. Same platform
    SMTP account as send_otp_email above - this isn't a per-company Gmail
    integration, so it works even for a company that hasn't connected one."""
    if not is_configured():
        raise NotImplementedError(
            "Email isn't configured yet. Set SMTP_HOST, SMTP_USERNAME, and "
            "SMTP_PASSWORD in .env (a Gmail app password works fine for this)."
        )

    body = (
        "Someone (hopefully you) requested a password reset for your Freight Pilot account.\n\n"
        f"Set a new password here: {reset_url}\n\n"
        "This link expires in 1 hour and can only be used once. If you didn't request this, "
        "you can safely ignore this email - your password won't change unless you click the link above."
    )
    message = MIMEText(body)
    message["Subject"] = "Reset your Freight Pilot password"
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = to_address

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, [to_address], message.as_string())


def send_trial_ending_email(
    to_address: str,
    *,
    company_name: str,
    ends_on: str,
    charge: str | None,
    has_card: bool | None,
) -> None:
    """Tells an owner their trial is nearly up, and what happens next.

    The point of this message is the part nobody enjoys writing: on a given
    day, money either moves or the account stops. Guidance on trial-expiry
    email is consistent that the date, the amount and the way out all belong
    in it, and the auto-renewal statutes ask for the same - so all three are
    here, above anything else.

    `has_card` is what we know about a card being on file: True, False, or
    None when Stripe could not be asked. None gets wording that is true
    either way rather than a guess, because warning about a charge that will
    not happen is its own kind of wrong.

    `charge` is like "$20 a month", or None for a plan with no price, in
    which case the amount is left out rather than invented.
    """
    if not is_configured():
        raise NotImplementedError(
            "Email isn't configured yet. Set SMTP_HOST, SMTP_USERNAME, and "
            "SMTP_PASSWORD in .env (a Gmail app password works fine for this)."
        )

    amount = charge or "the price of your plan"
    settings_url = f"{FRONTEND_URL}/settings"

    if has_card is True:
        what_happens = (
            f"On {ends_on}, {amount} will be charged automatically to the card on "
            "file, and again every period after that until you cancel.\n\n"
            "If you'd rather not continue, cancel before that date and you won't be "
            "charged at all."
        )
    elif has_card is False:
        what_happens = (
            f"There's no card on file, so nothing will be charged. On {ends_on} the "
            "plan simply stops and your account pauses.\n\n"
            "To keep it running, add a card in Settings before that date. Once one is "
            f"on file, {amount} is charged when the trial ends and every period after, "
            "until you cancel."
        )
    else:
        what_happens = (
            f"What happens on {ends_on} depends on whether a card is on file.\n\n"
            f"If there is one, {amount} is charged automatically that day and every "
            "period after, until you cancel. If there isn't, nothing is charged and "
            "the account pauses instead."
        )

    body = (
        f"Hello{' ' + company_name if company_name else ''},\n\n"
        f"Your Freight Pilot trial ends on {ends_on}.\n\n"
        f"{what_happens}\n\n"
        f"Manage or cancel any time here: {settings_url}\n\n"
        "One thing worth knowing: while a plan or trial is running, the last card on "
        "file can't be removed - the next charge would fail and the account would "
        "lapse without warning. Add a second card to replace it, or cancel the plan "
        "and then remove it.\n\n"
        "Freight Pilot"
    )

    message = MIMEText(body)
    message["Subject"] = f"Your Freight Pilot trial ends on {ends_on}"
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = to_address

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, [to_address], message.as_string())
