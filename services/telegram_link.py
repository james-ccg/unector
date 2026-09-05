"""
Connecting a person's Telegram account to their Unector login.

Telegram will not let a bot message somebody who has never opened a chat
with it - sendMessage answers 403 "bot can't initiate conversation with a
user" - and there is no API, permission or setting that changes that. It is
Telegram's rule, protecting their users from bots, and consent given on our
site cannot override it.

What that leaves is making the one required step as small as possible. A
deep link does exactly that: tapping it opens the bot with a payload
attached, and pressing Start both begins the conversation Telegram insists
on and links the account, in one action. The alternative it replaces was
"generate a code, open Telegram, find the bot, type /verify2fa ABC123",
which is why so few connections ever got made - and an unconnected account
fails silently, since a notification with nowhere to go is just a log line.

The token is the same one /verify2fa consumes, so both routes end at
consume_telegram_link_token and there is only one thing to expire.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

import requests

from config import TELEGRAM_BOT_TOKEN
from db.repository import create_telegram_link_token

logger = logging.getLogger(__name__)

TELEGRAM_TIMEOUT_SECONDS = 10

# Long enough to walk to a phone and short enough that a link left in a
# browser tab overnight cannot connect somebody else's Telegram account.
LINK_TOKEN_MINUTES = 30

# Looked up from the bot itself rather than configured, so it cannot drift
# from the token in .env - a username in a config file that names a bot the
# token no longer belongs to produces a link that opens the wrong bot.
_username_cache: str | None = None


def bot_username(refresh: bool = False) -> str | None:
    """The bot's @name, from getMe, cached for the life of the process."""
    global _username_cache
    if _username_cache and not refresh:
        return _username_cache
    if not TELEGRAM_BOT_TOKEN:
        return None

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe",
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
        if not response.ok:
            logger.warning("Couldn't read the bot's username: HTTP %s", response.status_code)
            return None
        _username_cache = (response.json().get("result") or {}).get("username")
    except Exception as e:  # noqa: BLE001 - reported, not swallowed silently
        logger.warning("Couldn't read the bot's username: %s: %s", type(e).__name__, e)
        return None

    return _username_cache


def issue_link(account_type: str, account_id: int) -> dict:
    """A one-tap link that connects this account to the bot.

    Returns the deep link and the code behind it. The code is included
    because the link cannot be tapped on a desktop with no Telegram
    installed, and typing /connect <code> in the app there is the way
    through - the same token, the other door.
    """
    code = secrets.token_hex(3).upper()
    create_telegram_link_token(
        account_type,
        account_id,
        code,
        datetime.now(timezone.utc) + timedelta(minutes=LINK_TOKEN_MINUTES),
    )

    username = bot_username()
    return {
        "code": code,
        # None when the bot is unreachable or unconfigured. The caller shows
        # the code and the command instead of a link to nowhere.
        "url": f"https://t.me/{username}?start={code}" if username else None,
        "expires_in_minutes": LINK_TOKEN_MINUTES,
    }
