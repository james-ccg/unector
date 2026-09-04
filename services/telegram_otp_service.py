"""
Sends 2FA one-time codes via the Telegram bot itself - no paid service
needed at all, since we already have a working bot. Requires the account
to have linked their Telegram account first (see the /verify2fa command in
bot.py and the telegram-link endpoints in miniapp/api.py).
"""
from aiogram import Bot

from config import TELEGRAM_BOT_TOKEN


async def send_otp_telegram(telegram_user_id: int, code: str) -> None:
    """Sends a one-time code as a direct message from the bot.

    Note: Telegram only allows a bot to message a user who has started a
    conversation with it first (which the /verify2fa flow requires anyway)."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(
            telegram_user_id,
            f"🔐 Your Unector verification code is: <code>{code}</code>\n\n"
            "This code expires in 10 minutes. If you didn't request this, you can ignore it.",
            parse_mode="HTML",
        )
    finally:
        await bot.session.close()
