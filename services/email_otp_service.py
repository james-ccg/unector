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

from config import SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL


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
