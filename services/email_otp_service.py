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
