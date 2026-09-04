"""Sends a notification to everyone at a company who wants it.

One entry point, `notify`. Callers say what happened; this decides who
hears about it and where, which keeps the decision in one place instead of
spread across every feature that has news.

Three rules hold here.

A notification must never break the thing that caused it. A load was
dispatched whether or not the email went out, so every channel is tried
independently and every failure is logged and swallowed. The alternative -
an SMTP timeout rolling back a dispatch - is far worse than a missed
message.

The site channel always fires. It costs nothing, interrupts nobody, and is
the only channel with no way to fail silently: an email address can be
missing or wrong and a Telegram DM needs the person to have started a chat
with the bot first. The bell is where anything the other two dropped can
still be found.

Mandatory events ignore preferences entirely. A failed payment or a change
to how an account is secured has a real consequence, and a notice nobody
asked for is the point of it.
"""
from __future__ import annotations

import asyncio
import logging

import requests

from config import TELEGRAM_BOT_TOKEN
from db import repository
from services import notification_events as events

logger = logging.getLogger(__name__)

# Telegram is reached over plain HTTP rather than through aiogram, because
# this runs in the API process as often as in the bot's, and those do not
# share a Bot instance or an event loop.
TELEGRAM_TIMEOUT_SECONDS = 10


def wants(
    account_type: str,
    account_id: int,
    event: events.Event,
    channel: str,
    saved: dict | None = None,
) -> bool:
    """Whether this account should get this event on this channel.

    A missing row means untouched rather than off, so it falls through to
    the event's own default. Writing a full grid of switches when an account
    is created would freeze today's defaults for everyone who never opens
    the page."""
    if not event.allows(channel):
        return False
    if event.mandatory or channel == "site":
        return True

    if saved is None:
        saved = repository.notification_preferences(account_type, account_id)
    chosen = saved.get((event.key, channel))
    return event.default_for(channel) if chosen is None else chosen


def _deliver_telegram(telegram_user_id: int, title: str, body: str | None) -> None:
    text = f"<b>{title}</b>"
    if body:
        text += f"\n\n{body}"

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": telegram_user_id, "text": text, "parse_mode": "HTML"},
        timeout=TELEGRAM_TIMEOUT_SECONDS,
    )
    if not response.ok:
        # 403 here is the ordinary case, not a bug: Telegram refuses to let a
        # bot message someone who has never started a chat with it.
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")


def notify(
    company_id: int,
    event_key: str,
    *,
    title: str,
    body: str | None = None,
    link: str | None = None,
    account_types: tuple[str, ...] = ("owner", "dispatcher"),
) -> dict:
    """Tells the company about something. Returns what actually went where.

    `account_types` narrows the audience - some news is the owner's alone,
    billing being the obvious case."""
    event = events.get(event_key)
    if not event:
        raise ValueError(f"No such notification event: {event_key}")

    sent = {"site": 0, "telegram": 0, "email": 0}
    skipped: list[str] = []

    for person in repository.office_recipients(company_id):
        if person["account_type"] not in account_types:
            continue

        account_type = person["account_type"]
        account_id = person["account_id"]
        saved = repository.notification_preferences(account_type, account_id)

        # The site record first, so there is something to find however the
        # rest of this goes.
        try:
            repository.create_notification(
                company_id, account_type, account_id,
                event=event_key, title=title, body=body, link=link,
            )
            sent["site"] += 1
        except Exception as e:  # noqa: BLE001 - reported, not swallowed silently
            logger.exception("Couldn't record a notification for %s %s: %s",
                             account_type, account_id, e)

        if wants(account_type, account_id, event, "telegram", saved):
            target = person["telegram_user_id"]
            if not target:
                skipped.append(f"{account_type}:{account_id} telegram (not linked)")
            else:
                try:
                    _deliver_telegram(target, title, body)
                    sent["telegram"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("Telegram notification to %s failed: %s: %s",
                                   target, type(e).__name__, e)

        if wants(account_type, account_id, event, "email", saved):
            address = person["email"]
            if not address:
                skipped.append(f"{account_type}:{account_id} email (no address)")
            else:
                try:
                    from services import email_otp_service

                    email_otp_service.send_notification_email(address, title, body, link)
                    sent["email"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("Email notification to %s failed: %s: %s",
                                   address, type(e).__name__, e)

    if skipped:
        logger.info("Notification %s skipped channels: %s", event_key, "; ".join(skipped))
    return {"event": event_key, "sent": sent, "skipped": skipped}


async def notify_async(company_id: int, event_key: str, **kwargs) -> dict:
    """`notify` from async code.

    Everything it does is blocking - SMTP, an HTTP call, the database - so
    it goes to a thread rather than stalling the bot's event loop while a
    mail server thinks about it."""
    return await asyncio.to_thread(notify, company_id, event_key, **kwargs)
