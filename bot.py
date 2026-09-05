"""
Unector Bot - main entry point.

Getting started:
    pip install -r requirements.txt
    python config.py                     # generates FERNET_MASTER_KEY (run once)
    # fill in .env (see below)
    python bot.py

Commands:
    /start         - welcome message and command list (works anywhere)
    /faq           - frequently asked questions (works anywhere)
    /commands      - full command list (works anywhere)
    /dashboard     - sends a button that opens the Mini App (owner/dispatcher login)
    /link          - direct link to the Mini App, for opening in any browser
    /verify2fa <code> - links this Telegram account for 2FA codes (code from Settings > Security)
    /linkdriver <code> - links a NEW Telegram group to a driver (code from Settings > Drivers).
                     Must be sent inside the group being linked.
    /myid          - debug helper, prints the current chat/group ID

The rest only work inside a driver+dispatch group, once it's linked to a driver:
    /dispatch <id> - finds RC from email, formats it, and posts to the group. With no id but
                     a PDF attached, replied to, or forwarded alongside it, builds the template
                     directly from that PDF instead of searching email.
    /loadpics      - (photo caption) AI reviews the load photo(s). Send 1-10 photos together
                     as one album (load, seal, reefer display, BOL, etc.) with /loadpics as the
                     caption on any one of them - the bot waits for the whole album and reviews
                     every photo together.
    /bol           - (photo/document caption) compares the BOL against the RC. Also supports
                     multiple photos sent together as one album, same as /loadpics.
    /pod           - (photo/document caption) forwards the POD straight to the broker by email.
                     Not checked by AI - just sent as-is. Supports multiple photos/pages too.
    /detention     - sends a detention/layover request to the broker, citing the terms already
                     extracted from the RC, and notifies the dispatcher. Send this when the
                     driver is actually being held - it isn't triggered automatically.
    /setvehicle    - links this group's driver to a Samsara vehicle ID, for GPS location alerts
"""
import asyncio
import html
import logging
import re
import time

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BotCommand, CallbackQuery,
)

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_PROXY_URL,
    SAMSARA_NEARBY_MILES,
    SAMSARA_POLL_INTERVAL_SECONDS,
    MINIAPP_URL,
    PLAN_PRICES,
)
from db.database import init_db
from db.repository import (
    get_driver_by_group,
    get_company,
    save_load,
    get_load_by_group,
    update_load_status,
    set_driver_vehicle,
    get_active_loads_for_monitoring,
    mark_notified,
    mark_detention_requested,
    mark_alert_rule_fired,
    get_enabled_alert_rules,
    consume_telegram_link_token,
    set_telegram_otp,
    link_driver_group,
    get_pending_proposal_for_group,
    apply_group_profile_proposal,
    dismiss_group_profile_proposal,
    proposal_driver_id,
    companies_due_trial_reminder,
    mark_trial_reminder_sent,
    create_notification,
    take_over_pin,
)
from services import (
    gemini_service, email_service, samsara_service, geo_utils, group_profile,
    notification_service,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _command_filter(cmd: str):
    """aiogram's built-in Command filter only checks message.text, never
    message.caption - so it never matches commands sent as a photo/document
    caption (e.g. a photo captioned "/loadpics"). This custom filter checks
    both, which is what /loadpics, /bol, and /pod need."""
    pattern = re.compile(rf"(?i)^/{re.escape(cmd)}(@\w+)?(\s|$)")

    def _check(message: Message) -> bool:
        content = message.text or message.caption or ""
        return bool(pattern.match(content))

    return _check


# If TELEGRAM_PROXY_URL is set in .env, aiogram connects through that proxy.
# Useful in regions where a direct connection to api.telegram.org is
# unstable or blocked.
session = AiohttpSession(proxy=TELEGRAM_PROXY_URL) if TELEGRAM_PROXY_URL else None

bot = Bot(token=TELEGRAM_BOT_TOKEN, session=session)
dp = Dispatcher()


@dp.error()
async def global_error_handler(event):
    """Log any unexpected error instead of letting it crash the whole bot."""
    logger.exception("Unexpected error: %s", event.exception)
    return True


async def update_group_title(group_id: int, title: str):
    """Updates the stored group title for a driver when the group name changes."""
    from db.database import get_session
    from db import models
    with get_session() as session:
        driver = session.query(models.Driver).filter(
            models.Driver.telegram_group_id == group_id
        ).first()
        if driver and driver.telegram_group_title != title:
            driver.telegram_group_title = title
            session.commit()
            logger.info(f"Updated group title for driver {driver.driver_bot_id}: {title}")


@dp.message(Command("start"))
async def handle_start(message: Message):
    """Welcome message + command list - the first thing most users see."""
    await message.reply(
        "👋 **Welcome to Unector!**\n\n"
        "I help trucking companies automate dispatch: I pull rate confirmations from email, "
        "extract load details with AI, check your BOL/POD photos, and track GPS proximity to "
        "pickup/delivery.\n\n"
        "**Commands**\n"
        "/dispatch <id> - find and post a load's rate confirmation\n"
        "/loadpics - (photo caption) AI reviews your load photos\n"
        "/bol - (photo/document caption) compares the BOL against the RC\n"
        "/pod - (photo/document caption) forwards the POD to the broker\n"
        "/detention - request detention/layover pay from the broker\n"
        "/setvehicle <id> - link this group to a Samsara vehicle for GPS alerts\n"
        "/dashboard - open the owner/dispatcher web dashboard\n"
        "/faq - frequently asked questions\n"
        "/commands - full command list\n\n"
        "The load commands only work inside your driver+dispatch group - if you're not sure "
        "where that is, ask your dispatcher.",
        parse_mode="Markdown",
    )


# Telegram refuses a message over 4096 characters outright - it does not
# truncate - so a growing FAQ does not get shorter, it stops arriving. The
# text lives here as one constant and is split at question boundaries on the
# way out, which keeps the writing in one readable place and keeps the limit
# from being something anybody has to remember while editing it.
TELEGRAM_MESSAGE_LIMIT = 4096

# Where the rest of the answers are. An empty MINIAPP_URL is an ordinary
# local-dev state, and printing "https:///pages/faq" would be worse than
# naming the page and letting /dashboard get them there.
FAQ_MORE_LINK = (
    f"{MINIAPP_URL.rstrip('/')}/pages/faq"
    if MINIAPP_URL
    else "the FAQ page on the dashboard (/dashboard opens it)"
)

# Kept to the questions somebody asks *from inside Telegram*: what this is,
# how to wire up a truck's group, and what it costs. Everything else is on
# the site, and the last line says so.
#
# The billing answer is long on purpose and is not a candidate for trimming.
# A free trial that turns into a charge is a negative-option offer: ROSCA
# wants the material terms - that it renews by itself, when, how much, and
# how to stop - given clearly before billing details are taken, and plenty
# of owners only ever see the bot. tests/test_trial_disclosure.py pins the
# phrases.
FAQ_TEXT = (
    "**Frequently Asked Questions**\n\n"
    "**What is Unector?**\n"
    "Dispatch management for trucking companies, run through Telegram. It reads "
    "rate confirmations out of your inbox, posts each load to the driver's group, "
    "checks BOL and POD photos, watches GPS for arrivals, and keeps a dashboard "
    "for the office.\n\n"
    "**How do I set up a truck's group?**\n"
    "Add the bot to the group, then send the linking code from Settings > Drivers "
    "inside that group. While you are there make the bot an admin with "
    "*Change group info* and *Pin messages*. "
    "With those two it keeps the group's name, description and picture matching "
    "the confirmed record, and pins the load everyone keeps scrolling back to. "
    "Without them nothing breaks; those writes are just skipped.\n\n"
    "**How does billing work?**\n"
    "Free to look around. Pro is $20/mo (or $200/yr) for up to 5 active drivers. "
    "Max 5x is $100/mo for up to 25 drivers, and Max 20x is $200/mo for up to 100. "
    "Every paid plan starts with a 7-day free trial. Starting one asks for a "
    "payment method - card, PayPal or a wallet - but nothing is charged while the "
    "trial runs. The plan then renews by itself: the price is charged on the day "
    "the trial ends and every period after, until it is cancelled from Settings. "
    "Until that first payment goes through the last payment method cannot be "
    "removed, since it is the only way to take it. Afterwards it can be removed "
    "whenever you like, and doing so ends the plan when the paid period runs "
    "out.\n\n"
    "**Who pays?**\n"
    "One plan per company, not one per person - whoever pays for it puts everybody "
    "on that plan at once. Settings > Billing shows who bought it and what has "
    "been charged, and the owner and every dispatcher are told when it changes.\n\n"
    "**Everything else**\n"
    "The group description the bot reads, the company logo, notifications, Gmail, "
    "GPS, what the AI does and how many dispatchers a plan allows are all "
    f"answered at {FAQ_MORE_LINK}\n\n"
    "For the full command list, use /commands. /dashboard opens the web "
    "dashboard, and /link gives the direct URL."
)


def split_for_telegram(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Breaks a long reply into messages Telegram will accept.

    Splits between questions - the blank line before a bold heading - so a
    question and its answer are never torn across two messages. A single
    section longer than the limit is a real possibility as this grows, so it
    falls back to splitting on paragraphs and then, failing that, on the
    limit itself: an ugly break beats no message at all.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    separator = "\n\n"
    for section in text.split(separator):
        candidate = f"{current}{separator}{section}" if current else section
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(section) > limit:
            chunks.append(section[:limit])
            section = section[limit:]
        current = section
    if current:
        chunks.append(current)
    return chunks


@dp.message(Command("faq"))
async def handle_faq(message: Message):
    """Frequently asked questions - mirrors the web dashboard's FAQ page."""
    for chunk in split_for_telegram(FAQ_TEXT):
        await message.reply(chunk, parse_mode="Markdown")


@dp.message(Command("commands"))
async def handle_commands(message: Message):
    """Full command reference - everything /start only summarizes."""
    await message.reply(
        "**Full Command List**\n\n"
        "**Anywhere**\n"
        "/start - welcome message and command summary\n"
        "/faq - frequently asked questions\n"
        "/commands - this list\n"
        "/dashboard - open the owner/dispatcher web dashboard\n"
        "/link - direct dashboard link, for opening in any browser\n"
        "/verify2fa <code> - links this chat for 2FA codes (code from Settings → Security)\n"
        "/linkdriver <code> - links a new Telegram group to a driver (code from Settings → Drivers) - "
        "send it inside the group being linked\n"
        "/myid - prints the current chat/group ID\n\n"
        "**Inside a driver+dispatch group only**\n"
        "/dispatch <id> - finds the rate confirmation email and posts it to the group. "
        "With no id but a PDF attached, replied to, or sent alongside it, builds the load "
        "directly from that PDF instead\n"
        "/loadpics - (photo caption) AI reviews load photos - send up to 10 as one album\n"
        "/bol - (photo/document caption) compares the BOL against the RC\n"
        "/pod - (photo/document caption) forwards the POD straight to the broker\n"
        "/detention - sends a detention/layover request to the broker, citing the RC's "
        "terms, and notifies the dispatcher - send it when the driver is actually held\n"
        "/setvehicle <id> - links this group's driver to a Samsara vehicle for GPS alerts\n"
        "/readbio - re-reads this group's description after you edit it, and offers "
        "the truck and driver details it finds for confirmation\n\n"
        "**What the bot needs in a group**\n"
        "Make it an admin with *Change group info* and *Pin messages*. With those it "
        "keeps the group's name, description and picture matching the confirmed record, "
        "and pins the current load card. Without them everything else still works - the "
        "writes are skipped, not retried.",
        parse_mode="Markdown",
    )


@dp.message(Command("myid"))
async def handle_myid(message: Message):
    """Temporary debug command - prints the chat/group ID (needed for seed.py)."""
    # Update group title if this is a group
    if message.chat.type in ["group", "supergroup"]:
        await update_group_title(message.chat.id, message.chat.title or "Unknown Group")
    
    await message.reply(f"🆔 This chat/group ID: `{message.chat.id}`", parse_mode="Markdown")


@dp.message(Command("link"))
async def handle_link(message: Message):
    """Returns the direct link to the Mini App that can be opened on any device."""
    if not MINIAPP_URL:
        await message.reply(
            "⚙️ The Mini App isn't set up yet. MINIAPP_URL is empty in .env."
        )
        return
    
    await message.reply(
        f"🔗 **Unector Dashboard Link**\n\n"
        f"{MINIAPP_URL}\n\n"
        f"📱 **How to use:**\n"
        f"• Copy the link above\n"
        f"• Open it in any browser (Chrome, Safari, Firefox)\n"
        f"• Works on any device that can run a browser\n\n"
        f"💡 **You can:**\n"
        f"• Share it with your team\n"
        f"• Bookmark it for quick access\n"
        f"• Open it from anywhere, anytime\n\n"
        f"🔐 Login required: Owner (MC#) or Dispatcher credentials",
        parse_mode="Markdown"
    )


@dp.message(Command("verify2fa"))
async def handle_verify2fa(message: Message):
    """Links this Telegram account to a Unector login, so it can be
    used to receive 2FA codes. Usage: /verify2fa <code shown on the
    Settings > Security page>"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "Usage: /verify2fa <code>\n\n"
            "Get a code from Settings → Security → Telegram in the Unector dashboard."
        )
        return

    code = args[1].strip().upper()
    result = consume_telegram_link_token(code)
    # account_type also covers "driver_group" codes from /linkdriver below -
    # the two commands share this token table, so a code meant for one must
    # never be usable in the other.
    if not result or result["account_type"] not in ("owner", "dispatcher"):
        await message.reply("❌ That code is invalid or has expired. Generate a new one from Settings → Security.")
        return

    set_telegram_otp(result["account_type"], result["account_id"], message.from_user.id, enabled=True)
    await message.reply(
        "✅ Telegram linked! You can now receive verification codes here, and enable "
        "Telegram as a two-factor method in Settings → Security."
    )


@dp.message(Command("linkdriver"))
async def handle_linkdriver(message: Message):
    """Links THIS Telegram group to a driver record, using a one-time code
    from the dashboard's Settings > Drivers page - the group-linking half of
    self-service driver setup (the owner creates the driver there, then adds
    the bot to the driver's group and sends this). Mirrors /verify2fa's use
    of the same TelegramLinkToken table, with a distinct account_type
    ("driver_group") so a code from one flow can't be misused in the other.
    Usage: /linkdriver <code>"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "Usage: /linkdriver <code>\n\n"
            "Get a code from the dashboard's Settings → Drivers page, after adding the driver there."
        )
        return

    if message.chat.type not in ("group", "supergroup"):
        await message.reply("⚠️ Run this command inside the driver's own Telegram group, not in a private chat.")
        return

    code = args[1].strip().upper()
    result = consume_telegram_link_token(code)
    if not result or result["account_type"] != "driver_group":
        await message.reply(
            "❌ That code is invalid or has expired. Generate a new one from the dashboard's Settings → Drivers page."
        )
        return

    status = link_driver_group(result["account_id"], message.chat.id, message.chat.title or "Unknown Group")
    if status == "already_linked_elsewhere":
        await message.reply("⚠️ This Telegram group is already linked to a different driver.")
        return
    if status == "not_found":
        await message.reply("⚠️ That driver no longer exists - please generate a new code from Settings → Drivers.")
        return

    await message.reply(
        "✅ This group is now linked! /dispatch, /loadpics, /bol, /pod, /detention, and /setvehicle all work here now."
    )

    # Most carriers already keep the truck and driver details in this group's
    # description. Offer to save what it says rather than making someone type
    # it all again on the dashboard.
    driver = get_driver_by_group(message.chat.id)
    if driver:
        await notification_service.notify_async(
            driver.company_id,
            "fleet.group_linked",
            title=f"{message.chat.title or 'A group'} is linked",
            body=f"It is now the dispatch group for driver {driver.driver_bot_id}.",
            link="/settings#drivers",
        )
        await offer_group_profile(message.chat.id, driver.id, driver.company_id)


# ------------------------------------------------------------------
# Truck and driver details from the group's description
#
# Carriers keep one group per truck and write the unit number, the trailer
# and the driver's details into its bio. The bot reads that, shows what it
# found, and saves it only once someone says yes - here or on the dashboard,
# whichever comes first.
# ------------------------------------------------------------------

async def _announce_group_changes(company_id: int, driver_id: int, changed: dict) -> None:
    """Tells the office what the bot just rewrote in a driver's group.

    Silent when nothing was written. A group where the bot is not an admin
    refuses all three, and an empty "the bot changed nothing" is worse than
    no message: it trains people to skip the ones that do say something.
    """
    described = group_profile.describe_changes(changed.get("written") or ())
    if not described:
        return
    await notification_service.notify_async(
        company_id, "fleet.group_updated",
        title=f"The bot updated a driver's group ({described})",
        body="Written from the details somebody confirmed.",
        link="/settings",
    )


async def offer_group_profile(chat_id: int, driver_id: int, company_id: int) -> None:
    """Reads the group's bio and asks the group to confirm what it says.

    Silent when there is nothing to read: an empty description, or a bio
    that carries no truck or driver details, is the ordinary case for a
    group somebody just created, and is not worth a message."""
    # A carrier who has never uploaded a logo usually has one sitting on the
    # group already. Taking it now, while we are here, saves them going to
    # find the file - and it only ever fills a gap, never overwrites a mark
    # somebody chose on the dashboard.
    await asyncio.to_thread(group_profile.adopt_group_logo, company_id, chat_id)

    proposal = await group_profile.read_and_propose(
        bot, company_id=company_id, driver_id=driver_id, chat_id=chat_id
    )
    if not proposal:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Confirm", callback_data=f"gp:apply:{proposal['id']}"),
            InlineKeyboardButton(text="✖️ Not now", callback_data=f"gp:skip:{proposal['id']}"),
        ]]
    )
    await bot.send_message(
        chat_id, group_profile.describe(proposal), parse_mode="HTML", reply_markup=keyboard
    )

    # The group has been asked; the office may not be watching it, so tell
    # them too. Either side confirming resolves the same proposal.
    await notification_service.notify_async(
        company_id,
        "fleet.profile_pending",
        title="A group description needs checking",
        body=group_profile.summarise(proposal),
        link="/settings#drivers",
    )


@dp.message(Command("readbio"))
async def handle_readbio(message: Message):
    """Re-reads this group's description, for after it has been edited."""
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("⚠️ Run this inside the truck's own Telegram group, not in a private chat.")
        return

    driver = get_driver_by_group(message.chat.id)
    if not driver:
        await message.reply(
            "⚠️ This group isn't linked to a driver yet. Link it first with /linkdriver <code>, "
            "using a code from the dashboard's Settings → Drivers page."
        )
        return

    notice = await message.reply("📖 Reading this group's description...")
    proposal = await group_profile.read_and_propose(
        bot, company_id=driver.company_id, driver_id=driver.id, chat_id=message.chat.id
    )
    if not proposal:
        await notice.edit_text(
            "This group's description doesn't carry any truck or driver details I can read. "
            "Add them there and run /readbio again, or enter them on the dashboard's Drivers page."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Confirm", callback_data=f"gp:apply:{proposal['id']}"),
            InlineKeyboardButton(text="✖️ Not now", callback_data=f"gp:skip:{proposal['id']}"),
        ]]
    )
    await notice.edit_text(
        group_profile.describe(proposal), parse_mode="HTML", reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("gp:"))
async def handle_group_profile_button(callback: CallbackQuery):
    """Confirm or dismiss, pressed in the group.

    The same proposal is also confirmable from the dashboard, so "already
    resolved" is a normal outcome here rather than a failure - it means the
    office got there first, and the buttons on this message are stale."""
    try:
        _, action, raw_id = (callback.data or "").split(":", 2)
        proposal_id = int(raw_id)
    except ValueError:
        await callback.answer("That button is no longer valid.", show_alert=True)
        return

    if action == "apply":
        owner = proposal_driver_id(proposal_id)
        ok, reason = apply_group_profile_proposal(proposal_id, "telegram")
        if ok and owner:
            # Rewrites this group's own name, description and picture from
            # what was just confirmed, so what everyone sees matches the
            # record - then tells the office what changed, since they were
            # not the ones standing in the group when it happened.
            changed = await asyncio.to_thread(group_profile.publish_all, *owner)
            await _announce_group_changes(owner[0], owner[1], changed)
        done_text = "✅ Saved to the dashboard."
    elif action == "skip":
        ok, reason = dismiss_group_profile_proposal(proposal_id, "telegram")
        done_text = "Left as it is. Run /readbio when you want to try again."
    else:
        await callback.answer("That button is no longer valid.", show_alert=True)
        return

    if ok:
        await callback.answer(done_text.split(".")[0].lstrip("✅ "))
        await callback.message.edit_text(
            f"{callback.message.html_text}\n\n<i>{done_text}</i>", parse_mode="HTML"
        )
        return

    if reason == "already_resolved":
        await callback.answer("This was already handled - from the dashboard, or here.")
        await callback.message.edit_reply_markup(reply_markup=None)
        return
    if reason == "driver_gone":
        await callback.answer("That driver has been deleted from the dashboard.", show_alert=True)
        return
    await callback.answer(f"Couldn't save it ({reason}).", show_alert=True)


@dp.message(Command("dashboard"))
async def handle_dashboard(message: Message):
    """Sends a button that opens the Mini App (owner/dispatcher login + driver management)."""
    # Update group title if changed
    if message.chat.type in ["group", "supergroup"]:
        await update_group_title(message.chat.id, message.chat.title or "Unknown Group")
    
    if not MINIAPP_URL:
        await message.reply(
            "⚙️ The Mini App isn't set up yet. MINIAPP_URL is empty in .env. "
            "Please see the README's Mini App section for setup instructions."
        )
        return

    # Web App buttons only work in private chats with the bot
    if message.chat.type != "private":
        await message.reply(
            f"📊 **Unector Dashboard**\n\n"
            f"To access the dashboard from any device:\n\n"
            f"**Option 1 (Telegram):**\n"
            f"Open a private chat with me and send /dashboard\n\n"
            f"**Option 2 (Direct link):**\n"
            f"Open this link in any browser:\n"
            f"{MINIAPP_URL}\n\n"
            f"Works on any device that can run a browser.",
            parse_mode="Markdown"
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Open Unector Dashboard", web_app=WebAppInfo(url=MINIAPP_URL))],
            [InlineKeyboardButton(text="🔗 Direct Link", url=MINIAPP_URL)]
        ]
    )
    await message.reply(
        "**📊 Unector Dashboard**\n\n"
        "Choose how to open:\n"
        "• **Web App button** - opens inside Telegram\n"
        "• **Direct Link** - opens in your browser\n\n"
        f"Direct URL: `{MINIAPP_URL}`\n\n"
        "💡 You can share this link with your team or open it on any device!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


@dp.message(Command("setvehicle"))
async def handle_setvehicle(message: Message):
    """Links this group's driver to a Samsara vehicle ID, so the location
    monitor can track them. Usage: /setvehicle <samsara vehicle id>"""
    # Update group title if changed
    if message.chat.type in ["group", "supergroup"]:
        await update_group_title(message.chat.id, message.chat.title or "Unknown Group")
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: /setvehicle <Samsara vehicle ID>")
        return

    try:
        driver = get_driver_by_group(message.chat.id)
    except NotImplementedError:
        await message.reply("⚙️ This feature isn't available for this group yet.")
        return

    if not driver:
        await message.reply("⚠️ This group isn't linked to a driver account yet. Please contact your dispatcher.")
        return

    vehicle_id = args[1].strip()

    # A typo'd vehicle ID would otherwise save silently and then just never
    # match anything in every future location-monitor poll - permanently
    # and silently disabling GPS alerts for this driver, with nothing ever
    # telling the owner why. Only a real "Samsara doesn't recognize this
    # ID" result blocks/warns; if Samsara isn't connected yet or the check
    # itself fails, save anyway rather than blocking on a check that
    # couldn't run - same policy as Settings' Samsara-connect validation.
    location = None
    try:
        location = await samsara_service.get_vehicle_location(driver.company_id, vehicle_id)
        validated = True
    except NotImplementedError:
        validated = False
    except Exception:
        logger.exception("Failed to validate Samsara vehicle %s for company %s", vehicle_id, driver.company_id)
        validated = False

    set_driver_vehicle(driver.id, vehicle_id)

    if validated and location is None:
        await message.reply(
            f"⚠️ Linked, but Samsara doesn't recognize vehicle ID `{vehicle_id}` (no GPS data found for it) - "
            "double-check the ID. GPS proximity alerts won't fire until it matches a real vehicle.",
            parse_mode="Markdown",
        )
    else:
        await message.reply(f"✅ This driver is now linked to Samsara vehicle `{vehicle_id}`.", parse_mode="Markdown")


# ------------------------------------------------------------------
# /dispatch 11111                     - finds the RC by load number in email
# /dispatch (PDF attached or replied) - builds the RC template straight from that PDF
#
# The two paths share almost everything after "get the RC PDF bytes" - only
# how those bytes are obtained differs (email search vs. a Telegram
# document), so _post_load_template does the common extract/geocode/save/
# post work and each path just gets it the bytes.
# ------------------------------------------------------------------
def _command_arg(content: str, cmd: str) -> str:
    """Returns whatever follows "/cmd" or "/cmd@botname" in a command's
    text/caption, trimmed. Empty string if nothing follows."""
    match = re.match(rf"(?i)^/{re.escape(cmd)}(@\w+)?\s*(.*)$", content, re.DOTALL)
    return match.group(2).strip() if match else ""


async def _get_driver_and_company(message: Message) -> tuple | None:
    """Shared prelude for /dispatch: resolves the group's driver + company,
    replying with the appropriate error and returning None if that's not
    possible. Also refreshes the stored group title, same as other commands."""
    if message.chat.type in ["group", "supergroup"]:
        await update_group_title(message.chat.id, message.chat.title or "Unknown Group")

    try:
        driver = get_driver_by_group(message.chat.id)
    except NotImplementedError:
        await message.reply(
            "⚙️ This feature isn't available for this group yet. "
            "It'll be ready soon."
        )
        return None

    if not driver:
        await message.reply("⚠️ This group isn't linked to a driver account yet. Please contact your dispatcher.")
        return None

    return driver, get_company(driver.company_id)


async def _pin_load_card(company_id: int, driver_id: int, load_id: str, posted: Message) -> bool:
    """Pins the load card just posted, and takes down the one it replaces.

    The card is the message a driver comes back to all week - the addresses,
    the appointment times, the reference numbers - and in a busy group it is
    twenty messages up by the afternoon. Pinning puts it one tap away.

    Exactly one load stays pinned, because a stack of finished jobs is worse
    than no pin at all: the driver has to work out which of them is today's.

    Nothing here is allowed to fail the dispatch. Pinning needs the bot to be
    an admin with "Pin messages", which is a Telegram setup question rather
    than something the code can fix, and the load has already been saved and
    posted by the time this runs. So a refusal is logged and swallowed, and
    the driver still has their load.
    """
    try:
        superseded = take_over_pin(company_id, driver_id, load_id, posted.message_id)
    except Exception:
        logger.exception("Couldn't record the pinned card for load %s", load_id)
        return False

    try:
        # Silent: the card itself already notified the group a moment ago,
        # and a second ping saying the same message was pinned is noise.
        await posted.pin(disable_notification=True)
    except TelegramAPIError as e:
        logger.warning(
            "Couldn't pin the card for load %s in group %s: %s: %s",
            load_id, posted.chat.id, type(e).__name__, e,
        )
        return False

    for message_id in superseded:
        try:
            await bot.unpin_chat_message(posted.chat.id, message_id)
        except TelegramAPIError as e:
            # Ordinary once a group is a few months old: the driver unpinned
            # it themselves, or the message aged out. Not worth a warning.
            logger.info(
                "Couldn't unpin the previous card (%s) in group %s: %s: %s",
                message_id, posted.chat.id, type(e).__name__, e,
            )

    return True


async def _post_load_template(message: Message, driver, company, load_id: str, data: dict):
    """Geocodes, saves the load, and posts the formatted template to the
    group - the tail end both the email-search and direct-PDF paths share.
    Takes already-Gemini-extracted `data` (rather than raw PDF bytes and
    extracting here) so a direct-PDF /dispatch with no load number - which
    needs to peek at the extracted load_id before it can even call this -
    doesn't end up paying for two Gemini calls on the same document."""
    try:
        # Geocode the pickup/delivery addresses now, so the location monitor
        # has coordinates to compare against later - no need to re-geocode
        # every time we poll Samsara. The two lookups are independent, so
        # run them concurrently instead of waiting on one then the other.
        pu_coords, del_coords = await asyncio.gather(
            geo_utils.geocode_address(data.get("pu_address")),
            geo_utils.geocode_address(data.get("del_address")),
        )
        if pu_coords:
            data["pu_lat"], data["pu_lng"] = pu_coords
        if del_coords:
            data["del_lat"], data["del_lng"] = del_coords

        save_load(company.id, driver.id, load_id, data)
        await notification_service.notify_async(
            company.id, "load.dispatched",
            title=f"Load {load_id} sent to {driver.driver_bot_id}",
            body=(data.get("broker_name") or "").strip() or None,
            link="/dashboard",
        )
    except Exception:
        logger.exception("Failed to save RC data for load %s", load_id)
        await message.reply(
            f"⚠️ Found the RC, but something went wrong while processing it "
            f"(load {load_id}). Please try again, or contact your dispatcher."
        )
        return

    text = format_load_template(load_id, data)
    dispatcher_tag = f"@{driver.dispatcher_username}" if driver.dispatcher_username else ""
    driver_tag = f"@{driver.telegram_username}" if driver.telegram_username else ""

    posted = await message.answer(f"{text}\n\n{driver_tag} {dispatcher_tag}", parse_mode="HTML")
    await _pin_load_card(company.id, driver.id, load_id, posted)


async def _extract_rc_data_or_reply(message: Message, pdf_bytes: bytes, context: str) -> dict | None:
    """Runs Gemini extraction (off the event loop, since the SDK call is
    synchronous) and replies with a friendly error instead of raising if it
    fails. Returns None on failure - callers should just return afterward."""
    try:
        return await asyncio.to_thread(gemini_service.extract_rc_data, pdf_bytes)
    except Exception:
        logger.exception("Failed to extract RC data (%s)", context)
        await message.reply(f"⚠️ Something went wrong while reading {context}. Please try again.")
        return None


async def _dispatch_by_load_number(message: Message, driver, company, load_id: str):
    """/dispatch <number> - searches the connected inbox for the RC."""
    await message.reply(f"🔍 Checking email for load {load_id}...")

    try:
        pdf_bytes = await asyncio.to_thread(email_service.find_rc_pdf_by_load_id, company.id, load_id)
    except NotImplementedError:
        await message.reply("⚙️ Email isn't connected for this company yet - ask your dispatcher to connect Gmail from the dashboard's Settings page.")
        return

    if pdf_bytes is None:
        await message.reply(f"❌ No RC email found for load {load_id}.")
        return

    data = await _extract_rc_data_or_reply(message, pdf_bytes, "that RC email")
    if data is None:
        return

    await _post_load_template(message, driver, company, load_id, data)


async def _dispatch_from_pdf(message: Message, driver, company, document):
    """Bare /dispatch (no load number) with a PDF attached or replied to -
    builds the template directly from that PDF instead of searching email.
    The load number itself comes from Gemini's own extraction (RCs list
    their own load/order number), with a placeholder fallback if it can't
    find one, so this never just dead-ends."""
    if not await _validate_document(document, message):
        return

    await message.reply("🔍 Reading the attached PDF...")
    pdf_bytes, _mime_type = await _download_document(document)

    data = await _extract_rc_data_or_reply(message, pdf_bytes, "that PDF")
    if data is None:
        return

    load_id = data.get("load_id") or f"PDF-{message.message_id}"
    if not data.get("load_id"):
        await message.reply(
            "⚠️ Couldn't find a load number on this PDF - using a placeholder ID "
            f"({load_id}). Re-run with /dispatch <load number> if you know it."
        )

    await _post_load_template(message, driver, company, load_id, data)


@dp.message(F.document, _command_filter("dispatch"))
async def handle_dispatch_document(message: Message):
    """/dispatch sent as a document caption. A load number in the caption
    always means "search email" (the attached PDF is ignored in that case);
    with no number, the attached PDF itself becomes the RC."""
    resolved = await _get_driver_and_company(message)
    if not resolved:
        return
    driver, company = resolved

    load_id = _command_arg(message.caption or "", "dispatch")
    if load_id:
        await _dispatch_by_load_number(message, driver, company, load_id)
    else:
        await _dispatch_from_pdf(message, driver, company, message.document)


@dp.message(_command_filter("dispatch"))
async def handle_dispatch_text(message: Message):
    """Plain-text /dispatch: with a load number, search email (this is the
    original /loadid behavior, just renamed). With no number, check
    whether this is a reply to a message with a PDF attached and build the
    template from that instead; otherwise show usage."""
    resolved = await _get_driver_and_company(message)
    if not resolved:
        return
    driver, company = resolved

    load_id = _command_arg(message.text or "", "dispatch")
    if load_id:
        await _dispatch_by_load_number(message, driver, company, load_id)
        return

    replied_document = message.reply_to_message.document if message.reply_to_message else None
    if replied_document:
        await _dispatch_from_pdf(message, driver, company, replied_document)
        return

    await message.reply(
        "Usage: /dispatch <load number> (e.g. /dispatch 11111)\n\n"
        "Or attach a PDF (or reply to one) with /dispatch and no number to build "
        "the load straight from that PDF instead of searching email."
    )


# These four lines are the carrier's own standing policy - they must appear
# in every load message exactly as written, regardless of what the RC says.
MANDATORY_NOTES = [
    "MUST ACCEPT THE LOAD AS DISPATCHED - THE BROKER MAY CHARGE FOR REFUSING IT",
    "LATE FEE: $500",
    "USE STRAPS AND LOADBARS TO SECURE THE LOAD",
    "MUST SCALE AFTER PU IF OVER 35,000 LBS - $100 CHARGE IF NOT SCALED",
]


def _normalize_time(value: str) -> str:
    """Safety net: inserts a colon into any bare 3-4 digit time (e.g. '1600' -> '16:00')
    while leaving 'By '/' Apt' wording and already-colon-formatted times untouched.
    This backs up the extraction prompt, in case the model returns a raw military time."""
    if not value:
        return value

    def add_colon(m: re.Match) -> str:
        digits = m.group(0)
        if len(digits) == 3:
            digits = "0" + digits
        return f"{digits[:2]}:{digits[2:]}"

    return re.sub(r"(?<!\d)\d{3,4}(?!\d)", add_colon, value)


def _format_stop_block(emoji: str, label: str, number: int, stop: dict) -> list[str]:
    """One PU or DEL stop's block: numbered header, address, date/time, and
    (if present) a reference number - shared by a load's primary pickup/
    delivery and any extra stops from additional_pu_stops/additional_del_stops,
    so a multi-stop RC renders PU :1, PU :2, DEL :1, DEL :2, etc. the same way."""
    e = html.escape
    lines = [f"<b>{emoji} {label}:{number}</b>"]
    lines.append(f"<pre><code class='language-PERFORMANCE'>{e(stop.get('address') or '—')}</code></pre>")
    lines.append("")
    date_time_bold = f"📅 Date: {e(stop.get('date') or '—')}\n🕔 Time:"
    lines.append(f"<b>{date_time_bold}</b> {e(_normalize_time(stop.get('time')) or '—')}")
    if stop.get("reference"):
        lines.append(f"Ref#: {e(stop['reference'])}")
    lines.append("")
    return lines


def format_load_template(load_id: str, data: dict) -> str:
    """Turns the JSON extracted from the RC into the dispatch group's message template.
    Uses Telegram HTML formatting - bold for section headers and value-carrying labels,
    blockquote for address/detail boxes, italic for the AI-generated summary. Every
    dynamic value is HTML-escaped, which is safer against special characters than
    Markdown mode.

    A load's PRIMARY pickup/delivery (pu_address/del_address, from the RC's main
    fields) is what the GPS location monitor tracks for proximity alerts - see
    LocationAlertRule. Any additional stops (additional_pu_stops/additional_del_stops,
    for multi-stop RCs) are shown to the driver here but aren't geocoded or tracked;
    full multi-stop GPS tracking would need the monitor rebuilt around a stop list
    instead of a single pu/del pair, which is a bigger change than just rendering them.

    Note: Telegram only supports one visual style of blockquote - it can't be colored
    differently per section, so the PU address, the weight/commodity box, and the DEL
    address all render with the same left-bar/tinted-background look."""
    e = html.escape  # short alias, used a lot below

    broker = e(data.get("broker_name") or "—")
    carrier = e(data.get("carrier_name") or "")

    # --- Header: broker + carrier + LOAD# label are bold, the load number itself is plain ---
    header_bold = f"📌 Broker: {broker}"
    if carrier:
        header_bold += f"\n{carrier}"
    header_bold += "\nLOAD#:"
    lines = [f"<b>{header_bold}</b> {e(load_id)}"]
    lines.append("")

    # --- PU section(s) ---
    lines.extend(_format_stop_block("🟢", "PU", 1, {
        "address": data.get("pu_address"), "date": data.get("pu_date"), "time": data.get("pu_time"),
    }))
    for i, stop in enumerate(data.get("additional_pu_stops") or [], start=2):
        lines.extend(_format_stop_block("🟢", "PU", i, stop))

    # --- Weight / Commodity / PU# box (always the primary pickup's reference) ---
    box_lines = []
    if data.get("weight"):
        box_lines.append(f"<b>⚖️ Weight: {e(data['weight'])}</b>")
    box_lines.append(f"<b>📤 Commodity:</b> {e(data.get('commodity') or '—')}")
    if data.get("reefer_temp"):
        box_lines.append(f"TEMP#: {e(data['reefer_temp'])}")
    if data.get("pu_reference"):
        box_lines.append(f"PU#: {e(data['pu_reference'])}")
    box_content = "\n".join(box_lines)
    lines.append(f"<blockquote>{box_content}</blockquote>")
    lines.append("")
    lines.append("")

    # --- DEL section(s) ---
    lines.extend(_format_stop_block("🔴", "DEL", 1, {
        "address": data.get("del_address"), "date": data.get("del_date"), "time": data.get("del_time"),
    }))
    for i, stop in enumerate(data.get("additional_del_stops") or [], start=2):
        lines.extend(_format_stop_block("🔴", "DEL", i, stop))

    # --- Mandatory standing-policy notes: always the same, always bold ---
    mandatory_block = "\n\n".join(MANDATORY_NOTES)
    lines.append(f"<b>{mandatory_block}</b>")

    # --- AI-summarized, load-specific notes from the RC - italic, visually distinct ---
    summary = (data.get("special_notes_summary") or "").strip()
    if summary:
        lines.append("")
        lines.append(f"<blockquote><i>{e(summary)}</i></blockquote>")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Photo album handling for /loadpics, /bol, /pod.
#
# Telegram sends each photo in an album as a SEPARATE message, all sharing
# the same media_group_id, and only ONE of them carries the caption text
# (e.g. "/loadpics"). This handler catches every photo (with or without a
# caption), buffers them by media_group_id, waits briefly for the rest of
# the album to arrive, then - once the album looks complete - figures out
# which command was used and processes every photo in the album together.
#
# A standalone photo (not part of an album) has no media_group_id, and is
# processed immediately as a "group of one".
# ------------------------------------------------------------------
_pending_photo_groups: dict[str, dict] = {}
GROUP_DEBOUNCE_SECONDS = 1.5

# If a photo for an album arrives more than GROUP_DEBOUNCE_SECONDS after its
# predecessor (a slow upload on a big album), the debounce fires and the
# album gets processed before the straggler shows up. Without this, that
# late photo would silently start a brand-new one-photo group under the
# same media_group_id - which almost never carries the caption (Telegram
# puts it on the first photo), so it'd just be dropped with no trace once
# ITS debounce fires and finds no command. This tracks recently-completed
# groups for a short grace window so a straggler gets a clear reply instead.
_recently_flushed_groups: dict[str, float] = {}
RECENTLY_FLUSHED_GRACE_SECONDS = 10.0


@dp.message(F.photo)
async def handle_photo_message(message: Message):
    group_id = message.media_group_id

    if not group_id:
        # Not part of an album - handle it right away as a single-photo group.
        await _process_photo_group([message])
        return

    if group_id not in _pending_photo_groups:
        flushed_at = _recently_flushed_groups.get(group_id)
        if flushed_at is not None and time.monotonic() - flushed_at < RECENTLY_FLUSHED_GRACE_SECONDS:
            await message.reply(
                "⚠️ This photo arrived after the rest of its album was already processed. "
                "Please resend the whole album together."
            )
            return

    entry = _pending_photo_groups.setdefault(group_id, {"messages": [], "timer": None})
    entry["messages"].append(message)

    # Every new photo in the album resets the debounce timer, so we only
    # process once no new photos have arrived for a short while.
    if entry["timer"] is not None:
        entry["timer"].cancel()
    entry["timer"] = asyncio.create_task(_flush_photo_group(group_id))


async def _flush_photo_group(group_id: str):
    await asyncio.sleep(GROUP_DEBOUNCE_SECONDS)
    entry = _pending_photo_groups.pop(group_id, None)
    if not entry:
        return
    _recently_flushed_groups[group_id] = time.monotonic()
    asyncio.create_task(_expire_recently_flushed_group(group_id))
    await _process_photo_group(entry["messages"])


async def _expire_recently_flushed_group(group_id: str):
    """Keeps _recently_flushed_groups from growing forever - each entry is
    only needed for the grace window a straggler photo could plausibly
    still show up in."""
    await asyncio.sleep(RECENTLY_FLUSHED_GRACE_SECONDS)
    _recently_flushed_groups.pop(group_id, None)


async def _process_photo_group(messages: list[Message]):
    """Figures out which command (if any) was used as the caption on this
    batch of photos, downloads every photo, and routes to the matching handler."""
    # Update group title if changed
    first_msg = messages[0]
    if first_msg.chat.type in ["group", "supergroup"]:
        await update_group_title(first_msg.chat.id, first_msg.chat.title or "Unknown Group")
    
    command = None
    trigger_message = messages[0]

    for m in messages:
        content = m.text or m.caption or ""
        for cmd in ("loadpics", "bol", "pod"):
            if re.match(rf"(?i)^/{cmd}(@\w+)?(\s|$)", content):
                command, trigger_message = cmd, m
                break
        if command:
            break

    if command is None:
        return  # just photos with no relevant command - nothing to do

    chat_id = trigger_message.chat.id
    files: list[tuple[bytes, str]] = []
    
    try:
        for m in messages:
            photo = m.photo[-1]
            file = await bot.get_file(photo.file_id)
            data = (await bot.download_file(file.file_path)).read()
            files.append((data, "image/jpeg"))
    except Exception:
        logger.exception("Failed to download photos from album")
        # Try to send error message to chat directly instead of replying to potentially deleted message
        try:
            await bot.send_message(chat_id, "⚠️ Failed to download photos. Please try again.")
        except Exception:
            logger.exception("Could not send error message to chat %s", chat_id)
        return

    if command == "loadpics":
        await _run_loadpics(chat_id, trigger_message, files)
    elif command == "bol":
        await _run_bol(chat_id, trigger_message, files)
    elif command == "pod":
        await _run_pod(chat_id, trigger_message, files)


def _format_loadpics_response(result: dict) -> str:
    """Formats the /loadpics AI response into the specified blockquote format.

    Every value pulled from `result` originates from Gemini's OCR reading of
    a driver-submitted photo - if the photographed text itself contains
    HTML-special characters (`<`, `&`, ...), an unescaped interpolation
    would either break Telegram's HTML parser or let it inject fake
    formatting into the message, so every dynamic value is escaped via g()."""
    e = html.escape

    def g(d: dict, key: str, default: str) -> str:
        return e(str(d.get(key) or default))

    lines = []

    # Task 1 - Load securement
    task1 = result.get("task1_securement", {})
    status1 = g(task1, "status", "Not checked")
    emoji1 = "✅" if "excellent" in status1.lower() or "good" in status1.lower() else "⚠️"
    lines.append(f"<b>Task 1 - Load securement:</b>")
    lines.append(f"<blockquote><b>Status</b> - {status1} {emoji1}</blockquote>")
    lines.append("")

    # Task 2 - Seal number
    task2 = result.get("task2_seal", {})
    bol_seal = g(task2, "bol", "not visible")
    photos_seal = g(task2, "photos", "not visible")
    status2 = g(task2, "status", "Not checked")
    emoji2 = "✅" if "match" in status2.lower() else "⚠️"
    lines.append(f"<b>Task 2 - Seal number:</b>")
    blockquote_lines = [
        f"<b>BOL</b> - {bol_seal}",
        f"<b>Photos</b> - {photos_seal}",
        f"<b>Status</b> - {status2} {emoji2}"
    ]
    lines.append(f"<blockquote>{'&#10;'.join(blockquote_lines)}</blockquote>")
    lines.append("")

    # Task 3 - Temperature
    task3 = result.get("task3_temperature", {})
    rc_temp = g(task3, "rc", "didn't show")
    bol_temp = g(task3, "bol", "didn't show")
    photos_temp = g(task3, "photos", "didn't show")
    status3 = g(task3, "status", "Not checked")
    emoji3 = "✅" if "match" in status3.lower() else "⚠️"
    lines.append(f"<b>Task 3 - Temperature:</b>")
    blockquote_lines = [
        f"<b>RC</b> - {rc_temp}",
        f"<b>BOL</b> - {bol_temp}",
        f"<b>Photos</b> - {photos_temp}",
        f"<b>Status</b> - {status3} {emoji3}"
    ]
    lines.append(f"<blockquote>{'&#10;'.join(blockquote_lines)}</blockquote>")
    lines.append("")

    # Task 4 - Documentation
    task4 = result.get("task4_documentation", {})
    rc_pages = g(task4, "rc", "not specified")
    bol_pages = g(task4, "bol", "not visible")
    status4 = g(task4, "status", "Not checked")
    emoji4 = "✅" if "okay" in status4.lower() or "match" in status4.lower() else "⚠️"
    lines.append(f"<b>Task 4 - Documentation:</b>")
    blockquote_lines = [
        f"<b>RC</b> - {rc_pages}",
        f"<b>BOL</b> - {bol_pages}",
        f"<b>Status</b> - {status4} {emoji4}"
    ]
    lines.append(f"<blockquote>{'&#10;'.join(blockquote_lines)}</blockquote>")
    lines.append("")

    # Final verdict
    if result.get("issues") and len(result["issues"]) > 0:
        lines.append("<b>Please review before proceeding.</b>")
    else:
        lines.append("<b>Everything looks good!</b>")

    return "\n".join(lines)


async def _run_loadpics(chat_id: int, trigger_message: Message, files: list[tuple[bytes, str]]):
    label = "photo" if len(files) == 1 else f"{len(files)} photos"
    try:
        await bot.send_message(chat_id, f"🔍 Reviewing the {label}...")
    except Exception:
        logger.exception("Failed to send review message to chat %s", chat_id)

    try:
        load = get_load_by_group(chat_id)
    except NotImplementedError:
        load = None
    rc_json = load.raw_extracted_json if load else {}

    try:
        result = await asyncio.to_thread(gemini_service.check_load_picture, rc_json, files)
    except Exception:
        logger.exception("Failed to review load photo(s) for chat %s", chat_id)
        await bot.send_message(chat_id, "⚠️ Something went wrong while reviewing the photos. Please try again.")
        return

    if result.get("loading_ok") and load:
        update_load_status(load.id, "loaded")
        await notification_service.notify_async(
            load.company_id, "load.status_changed",
            title=f"Load {load.load_id} is loaded",
            body="Marked from the driver's group.",
            link="/dashboard",
        )

    formatted_message = _format_loadpics_response(result)
    await bot.send_message(chat_id, formatted_message, parse_mode="HTML")


def _format_bol_response(result: dict) -> str:
    """Formats the /bol AI response into the specified blockquote format.
    See _format_loadpics_response's docstring - same escaping rationale,
    since this is also built from Gemini's OCR reading of a driver photo."""
    def g(d: dict, key: str, default: str) -> str:
        return html.escape(str(d.get(key) or default))

    lines = []

    # Weight section
    weight = result.get("weight", {})
    bol_weight = g(weight, "bol", "not visible")
    rc_weight = g(weight, "rc", "not visible")
    weight_status = g(weight, "status", "Not checked")
    lines.append(f"<b>Weight:</b>")
    blockquote_lines = [
        f"<b>BOL</b> - {bol_weight}",
        f"<b>RC</b> - {rc_weight}",
        f"<b>Status</b> - {weight_status}"
    ]
    lines.append(f"<blockquote>{'&#10;'.join(blockquote_lines)}</blockquote>")
    lines.append("")

    # Delivery address section
    del_addr = result.get("delivery_address", {})
    bol_addr = g(del_addr, "bol", "not visible")
    rc_addr = g(del_addr, "rc", "not visible")
    addr_status = g(del_addr, "status", "Not checked")
    addr_emoji = g(del_addr, "emoji", "")
    lines.append(f"<b>Delivery address:</b>")
    blockquote_lines = [
        f"<b>BOL</b> - <i>{bol_addr}</i>",
        f"<b>RC</b> - <i>{rc_addr}</i>",
        f"<b>Status</b> - {addr_status} {addr_emoji}"
    ]
    lines.append(f"<blockquote>{'&#10;'.join(blockquote_lines)}</blockquote>")
    lines.append("")

    # Temperature section
    temp = result.get("temperature", {})
    rc_temp = g(temp, "rc", "didn't show")
    bol_temp = g(temp, "bol", "didn't show")
    temp_status = g(temp, "status", "Not checked")
    lines.append(f"<b>Temperature:</b>")
    blockquote_lines = [
        f"<b>RC</b> - {rc_temp}",
        f"<b>BOL</b> - {bol_temp}",
        f"<b>Status</b> - {temp_status}"
    ]
    lines.append(f"<blockquote>{'&#10;'.join(blockquote_lines)}</blockquote>")
    lines.append("")

    # Seal match status section
    seal = result.get("seal", {})
    seal_summary = g(seal, "summary", "Not checked")
    lines.append(f"<b>Seal match status:</b>")
    lines.append(f"<blockquote>{seal_summary}</blockquote>")
    lines.append("")

    # Final verdict
    if result.get("mismatches") and len(result["mismatches"]) > 0:
        lines.append("<b>Please review before proceeding.</b>")
    else:
        lines.append("<b>Everything looks good!</b>")

    return "\n".join(lines)


async def _run_bol(chat_id: int, trigger_message: Message, files: list[tuple[bytes, str]]):
    try:
        load = get_load_by_group(chat_id)
    except NotImplementedError:
        await bot.send_message(chat_id, "⚙️ This feature isn't available for this group yet.")
        return

    if not load or not load.raw_extracted_json:
        await bot.send_message(chat_id, "⚠️ Please pull in the RC first using /dispatch.")
        return

    label = "document" if len(files) == 1 else f"{len(files)} documents"
    await bot.send_message(chat_id, f"🔍 Comparing the {label} against the rate confirmation...")

    try:
        result = await asyncio.to_thread(gemini_service.compare_bol_with_rc, load.raw_extracted_json, files)
    except Exception:
        logger.exception("Failed to compare BOL for load %s", load.load_id)
        await bot.send_message(chat_id, "⚠️ Something went wrong while comparing the BOL. Please try again.")
        return

    formatted_message = _format_bol_response(result)
    await bot.send_message(chat_id, formatted_message, parse_mode="HTML")

    if result.get("match"):
        update_load_status(load.id, "bol_ok")
        # Auto email update to the broker (works once email_service is connected)
        try:
            await asyncio.to_thread(
                email_service.send_email,
                company_id=load.company_id,
                to_address=load.raw_extracted_json.get("broker_contact_email", ""),
                subject=f"Load #{load.load_id} — Loaded confirmation",
                body="Driver has been loaded and BOL matches the rate confirmation.",
            )
        except NotImplementedError:
            logger.info("Email integration not connected yet — update not sent.")


async def _run_pod(chat_id: int, trigger_message: Message, files: list[tuple[bytes, str]]):
    try:
        load = get_load_by_group(chat_id)
    except NotImplementedError:
        await bot.send_message(chat_id, "⚙️ This feature isn't available for this group yet.")
        return

    if not load or not load.raw_extracted_json:
        await bot.send_message(chat_id, "⚠️ Please pull in the RC first using /dispatch.")
        return

    broker_email = load.raw_extracted_json.get("broker_contact_email")
    if not broker_email:
        await bot.send_message(
            chat_id,
            "⚠️ No broker contact email found for this load - please send the POD manually."
        )
        return

    await bot.send_message(chat_id, f"📤 Sending POD to {broker_email}...")

    attachments = [
        {"filename": f"POD_{load.load_id}_{i + 1}.jpg", "data": data, "mime_type": mime}
        for i, (data, mime) in enumerate(files)
    ]

    try:
        await asyncio.to_thread(
            email_service.send_email,
            company_id=load.company_id,
            to_address=broker_email,
            subject=f"Load #{load.load_id} — POD",
            body=f"Please find the proof of delivery attached for load #{load.load_id}.",
            attachments=attachments,
        )
    except NotImplementedError:
        await bot.send_message(chat_id, "⚙️ Email isn't connected for this company yet - ask your dispatcher to connect Gmail from the dashboard's Settings page.")
        return
    except Exception:
        logger.exception("Failed to send POD email for load %s", load.load_id)
        await bot.send_message(
            chat_id,
            "⚠️ Something went wrong while sending the POD. Please try again or send it manually."
        )
        return

    update_load_status(load.id, "pod_sent")
    await bot.send_message(chat_id, f"✅ POD sent to {broker_email}.")


# ------------------------------------------------------------------
# /detention - manual trigger, sent by the driver or dispatcher once
# they're actually being held. Pulls the detention/layover terms Gemini
# already extracted from the RC (see gemini_service.py's "detention_terms"
# field) and emails the broker a request citing them - no GPS/time-based
# auto-firing, to avoid false positives from traffic, breaks, etc.
# ------------------------------------------------------------------
@dp.message(Command("detention"))
async def handle_detention(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        await update_group_title(message.chat.id, message.chat.title or "Unknown Group")

    try:
        driver = get_driver_by_group(message.chat.id)
    except NotImplementedError:
        await message.reply("⚙️ This feature isn't available for this group yet.")
        return

    if not driver:
        await message.reply("⚠️ This group isn't linked to a driver account yet. Please contact your dispatcher.")
        return

    load = get_load_by_group(message.chat.id)
    if not load or not load.raw_extracted_json:
        await message.reply("⚠️ No active load found for this group. Please pull in the RC first using /dispatch.")
        return

    if load.detention_requested_at:
        await message.reply(
            f"ℹ️ A detention/layover request was already sent for load {load.load_id} "
            f"on {load.detention_requested_at.strftime('%b %d, %Y %H:%M UTC')}."
        )
        return

    terms = (load.raw_extracted_json.get("detention_terms") or "").strip()
    if not terms:
        await message.reply(
            "⚠️ No detention/layover terms were found on this load's rate confirmation. "
            "Please contact your dispatcher directly to request detention pay."
        )
        return

    broker_email = load.raw_extracted_json.get("broker_contact_email")
    if not broker_email:
        await message.reply("⚠️ No broker contact email found for this load - please request detention pay manually.")
        return

    try:
        await asyncio.to_thread(
            email_service.send_email,
            company_id=load.company_id,
            to_address=broker_email,
            subject=f"Load #{load.load_id} — Detention/Layover Request",
            body=(
                f"This is a detention/layover request for load #{load.load_id}, per the "
                f"rate confirmation's stated terms:\n\n{terms}\n\nPlease advise on next steps."
            ),
        )
    except NotImplementedError:
        await message.reply("⚙️ Email isn't connected for this company yet - ask your dispatcher to connect Gmail from the dashboard's Settings page.")
        return
    except Exception:
        logger.exception("Failed to send detention request for load %s", load.load_id)
        await message.reply("⚠️ Something went wrong while sending the detention request. Please try again.")
        return

    mark_detention_requested(load.id)

    await notification_service.notify_async(
        driver.company_id,
        "load.detention",
        title=f"Detention requested on load {load.load_id}",
        body=f"{driver.driver_bot_id} has been sitting. The request went to {broker_email}.",
        link="/dashboard",
    )

    dispatcher_tag = f"@{driver.dispatcher_username}" if driver.dispatcher_username else "Your dispatcher"
    await message.reply(
        f"✅ Detention/layover request sent to {broker_email} for load {load.load_id}.\n"
        f"{dispatcher_tag} has been notified."
    )


# ------------------------------------------------------------------
# Document-based /bol and /pod - for when the driver sends a PDF file
# instead of a photo. Registered AFTER handle_photo_message, so photos are
# always caught by the album handler above; these only ever see documents.
#
# Unlike the `photo` message type (where Telegram itself guarantees the
# content is an actual, size-limited image), a `document` can be any file
# a user attaches - so it needs its own type/size check before being
# downloaded and handed to Gemini/email sending.
# ------------------------------------------------------------------
MAX_DOCUMENT_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB (Telegram bots cap downloads at 20MB anyway)
ALLOWED_DOCUMENT_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}


async def _validate_document(document, reply_target: Message) -> bool:
    """Returns False (having already sent a friendly reply via reply_target)
    if the document fails the type/size check. Takes the document object
    directly (rather than assuming it's on reply_target) so it also works
    for a document on a REPLIED-TO message, as /dispatch needs."""
    if document.mime_type and document.mime_type not in ALLOWED_DOCUMENT_MIME_TYPES:
        await reply_target.reply("⚠️ Please attach a PDF or image file - that file type isn't supported.")
        return False
    if document.file_size and document.file_size > MAX_DOCUMENT_UPLOAD_BYTES:
        await reply_target.reply(f"⚠️ That file is too large (max {MAX_DOCUMENT_UPLOAD_BYTES // (1024 * 1024)}MB).")
        return False
    return True


async def _download_document(document) -> tuple[bytes, str]:
    file = await bot.get_file(document.file_id)
    data = (await bot.download_file(file.file_path)).read()
    mime_type = document.mime_type or "application/pdf"
    return data, mime_type


@dp.message(F.document, _command_filter("bol"))
async def handle_bol_document(message: Message):
    if not await _validate_document(message.document, message):
        return
    data, mime_type = await _download_document(message.document)
    await _run_bol(message.chat.id, message, [(data, mime_type)])


@dp.message(F.document, _command_filter("pod"))
async def handle_pod_document(message: Message):
    if not await _validate_document(message.document, message):
        return
    data, mime_type = await _download_document(message.document)
    await _run_pod(message.chat.id, message, [(data, mime_type)])


@dp.message(_command_filter("bol"))
async def handle_bol_no_attachment(message: Message):
    """Reached only when /bol was sent with no photo/document attached."""
    await message.reply("⚠️ Please send the BOL photo(s) or file with the /bol caption.")


@dp.message(_command_filter("pod"))
async def handle_pod_no_attachment(message: Message):
    """Reached only when /pod was sent with no photo/document attached."""
    await message.reply("⚠️ Please send the POD photo(s) or file with the /pod caption.")


@dp.message(_command_filter("loadpics"))
async def handle_loadpics_no_attachment(message: Message):
    """Reached only when /loadpics was sent with no photo attached."""
    await message.reply("⚠️ Please send the load photo(s) with the /loadpics caption.")


# ------------------------------------------------------------------
# Catch-alls for a private chat with the bot - registered last, so they
# only ever fire once every specific command handler above has already had
# a chance to match. Scoped to private chats on purpose: a group can have
# other bots and ordinary conversation in it, where replying to every
# unmatched message would just be noise.
# ------------------------------------------------------------------
@dp.message(F.text.regexp(r"^/\w+"), F.chat.type == "private")
async def handle_unrecognized_command(message: Message):
    """Reached only when the text looks like a command (starts with /) but
    didn't match any command handler above."""
    await message.reply("Unrecognized command. Say what?")


@dp.message(F.text, F.chat.type == "private")
async def handle_plain_text_dm(message: Message):
    """Reached only for ordinary text in a private chat - not a command,
    and not a reply the bot was expecting for anything in progress."""
    await message.reply(
        f"If you're having trouble, please contact your dispatcher or company owner.\n\n"
        f"Dashboard: {MINIAPP_URL or 'ask your dispatcher for the link'}"
    )


# ------------------------------------------------------------------
# Background task: polls Samsara for each active load's vehicle location,
# and alerts the driver's group once the truck gets close to pickup/delivery.
#
# This is polling-based rather than webhook-based on purpose: webhooks need
# a public HTTPS endpoint, which isn't available until the bot is deployed
# to a server with a domain. Once that happens, this loop can be replaced
# with a FastAPI webhook route without touching samsara_service.py at all.
# ------------------------------------------------------------------
async def location_monitor_loop():
    logger.info(
        "Location monitor started (checking every %ss, alert radius %s miles).",
        SAMSARA_POLL_INTERVAL_SECONDS, SAMSARA_NEARBY_MILES,
    )
    while True:
        try:
            await _check_all_loads_once()
        except Exception:
            logger.exception("Error during location monitor pass - will retry next cycle.")
        await asyncio.sleep(SAMSARA_POLL_INTERVAL_SECONDS)


# ------------------------------------------------------------------
# "Your trial ends soon"
#
# A seven-day trial that turns into a charge is the kind of thing people
# forget they started. Guidance on trial-expiry email agrees on giving at
# least two days' notice and on saying the date, the amount and the way out,
# so that is what goes out and when.
#
# Two days is also our own choice rather than a legal one: California only
# requires the notice for free periods longer than 31 days, so a 7-day trial
# is not covered. It is sent because a surprise charge is a bad way to meet
# a customer, not because anyone made us.
# ------------------------------------------------------------------

TRIAL_REMINDER_HOURS_BEFORE = 48
TRIAL_REMINDER_INTERVAL_SECONDS = 60 * 60


def _trial_charge_label(tier: str, interval: str | None) -> str | None:
    """"$20 a month", or None for a plan with no price on record - in which
    case the email says "the price of your plan" rather than inventing one."""
    amounts = PLAN_PRICES.get(tier)
    if not amounts:
        return None
    period = "year" if interval == "year" else "month"
    return f"${amounts[period]} a {period}"


def _has_card_on_file(stripe_customer_id: str | None, company_id: int) -> bool | None:
    """True, False, or None when Stripe could not be asked.

    None matters: the email says something true either way rather than
    warning about a charge that may not be coming."""
    if not stripe_customer_id:
        return False
    try:
        from services import stripe_service

        return bool(stripe_service.list_payment_methods(company_id))
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        logger.warning(
            "Couldn't check payment methods for company %s: %s: %s",
            company_id, type(e).__name__, e,
        )
        return None


async def _send_trial_reminders_once() -> None:
    from services import email_otp_service

    due = companies_due_trial_reminder(TRIAL_REMINDER_HOURS_BEFORE)
    if not due:
        return

    if not email_otp_service.is_configured():
        logger.warning(
            "%s trial reminder(s) are due, but SMTP isn't configured - none sent.", len(due)
        )
        return

    for company in due:
        ends_on = company["trial_ends_at"].strftime("%d %B %Y")
        try:
            email_otp_service.send_trial_ending_email(
                company["email"],
                company_name=company["company_name"] or "",
                ends_on=ends_on,
                charge=_trial_charge_label(company["subscription_tier"], company["billing_interval"]),
                has_card=_has_card_on_file(company["stripe_customer_id"], company["id"]),
            )
        except Exception as e:  # noqa: BLE001 - reported, not swallowed
            # Left unmarked on purpose, so the next pass tries again. There
            # is time: the window is two days wide and this runs hourly.
            logger.warning(
                "Couldn't send the trial reminder to company %s: %s: %s",
                company["id"], type(e).__name__, e,
            )
            continue

        mark_trial_reminder_sent(company["id"])

        # Recorded on the bell as well, so the notice is findable after the
        # email is buried. Written directly rather than through notify():
        # this event defaults to email too, and the message above is the
        # better-written one - routing it through notify() would send a
        # second, blunter copy of the same news.
        try:
            create_notification(
                company["id"], "owner", company["id"],
                event="billing.trial_ending",
                title=f"Your trial ends on {ends_on}",
                body="After that the plan renews by itself. Manage it in Settings.",
                link="/settings",
            )
        except Exception:  # noqa: BLE001 - the email is what matters here
            logger.exception("Couldn't record the trial reminder for company %s", company["id"])

        logger.info("Trial reminder sent to company %s (trial ends %s).", company["id"], ends_on)


async def trial_reminder_loop():
    logger.info(
        "Trial reminder started (checking hourly, %s hours before a trial ends).",
        TRIAL_REMINDER_HOURS_BEFORE,
    )
    while True:
        try:
            await _send_trial_reminders_once()
        except Exception:
            logger.exception("Error during trial reminder pass - will retry next cycle.")
        await asyncio.sleep(TRIAL_REMINDER_INTERVAL_SECONDS)


# Built-in wording, used for a scenario until a company configures its own
# rules for it (see LocationAlertRule / Settings > Alerts). Kept byte-for-byte
# identical to what this used to say unconditionally, so a company that never
# touches the new settings sees no change at all.
DEFAULT_ALERT_MESSAGES = {
    "pu_near": "📍 Driver is ~{miles} miles from pickup on load #{load_id}. We'll inform you once they check in.",
    "del_near": "📍 Driver is ~{miles} miles from delivery on load #{load_id}. We'll inform you once they check in.",
}


def _render_alert_message(template: str | None, scenario: str, distance_miles: float, load_id: str) -> str:
    """Fills in a company's custom alert message (or the built-in default if
    they haven't set one). Supports {miles} and {load_id} placeholders. Falls
    back to the default wording if a company's template is malformed (e.g. a
    typo'd placeholder) instead of silently dropping the alert."""
    text = template or DEFAULT_ALERT_MESSAGES[scenario]
    try:
        return text.format(miles=round(distance_miles), load_id=load_id)
    except (KeyError, IndexError, ValueError):
        logger.warning("Malformed alert message template for %s: %r - using the default instead", scenario, template)
        return DEFAULT_ALERT_MESSAGES[scenario].format(miles=round(distance_miles), load_id=load_id)


async def _fire_scenario_alerts(load, scenario: str, distance_miles: float, rules: list[dict]) -> None:
    """Sends every alert `load` newly qualifies for under `scenario`.

    A company with no custom rules for this scenario gets the single
    built-in default alert, exactly like before this feature existed. A
    company that has configured rules gets each of its own distance
    thresholds instead (the default is not also applied) - each rule fires
    independently, at most once per load, as the truck gets closer."""
    if not rules:
        default_flag = "notified_pu_near" if scenario == "pu_near" else "notified_del_near"
        if getattr(load, default_flag) or distance_miles > SAMSARA_NEARBY_MILES:
            return
        text = _render_alert_message(None, scenario, distance_miles, load.load_id)
        await bot.send_message(load.telegram_group_id, text)
        mark_notified(load.id, "pu" if scenario == "pu_near" else "del")
        return

    for rule in rules:
        if rule["id"] in load.alerted_rule_ids or distance_miles > rule["distance_miles"]:
            continue
        text = _render_alert_message(rule["message_template"], scenario, distance_miles, load.load_id)
        await bot.send_message(load.telegram_group_id, text)
        mark_alert_rule_fired(load.id, rule["id"])
        load.alerted_rule_ids.append(rule["id"])  # keep this pass's in-memory copy in sync


async def _check_all_loads_once():
    loads = get_active_loads_for_monitoring()
    if not loads:
        return

    # Group by company so each company's fleet is fetched from Samsara in ONE
    # request per pass, rather than one request per truck.
    by_company: dict[int, list] = {}
    for load in loads:
        by_company.setdefault(load.company_id, []).append(load)

    for company_id, company_loads in by_company.items():
        vehicle_ids = sorted({ld.samsara_vehicle_id for ld in company_loads})
        try:
            locations = await samsara_service.get_fleet_locations(company_id, vehicle_ids)
        except NotImplementedError:
            continue  # this company hasn't connected Samsara yet
        except Exception:
            logger.exception("Failed to fetch Samsara locations for company %s", company_id)
            continue

        # Loaded lazily and cached per company per pass - every load in a
        # dispatched company shares the same pu_near rules, no need to
        # re-query per load.
        pu_rules = del_rules = None

        for load in company_loads:
            location = locations.get(load.samsara_vehicle_id)
            if not location or location.get("lat") is None:
                continue

            try:
                # Still heading to pickup: check distance to PU.
                if load.status == "dispatched" and load.pu_lat is not None:
                    if pu_rules is None:
                        pu_rules = get_enabled_alert_rules(company_id, "pu_near")
                    distance = geo_utils.haversine_miles(location["lat"], location["lng"], load.pu_lat, load.pu_lng)
                    await _fire_scenario_alerts(load, "pu_near", distance, pu_rules)

                # Already loaded: check distance to delivery instead.
                elif load.status in ("loaded", "bol_ok") and load.del_lat is not None:
                    if del_rules is None:
                        del_rules = get_enabled_alert_rules(company_id, "del_near")
                    distance = geo_utils.haversine_miles(location["lat"], location["lng"], load.del_lat, load.del_lng)
                    await _fire_scenario_alerts(load, "del_near", distance, del_rules)
            except Exception:
                # e.g. bot.send_message raising because the bot was removed/
                # blocked from this one load's group (TelegramForbiddenError)
                # - must not abort the loop, or every company later in
                # by_company.items() this pass would silently get skipped too.
                logger.exception("Failed to check/fire alerts for load %s (company %s)", load.id, company_id)


# ------------------------------------------------------------------
async def main():
    init_db()
    logger.info("Database ready.")

    # Populates Telegram's native "/" command menu next to the message box.
    await bot.set_my_commands([
        BotCommand(command="start", description="Welcome message and command summary"),
        BotCommand(command="faq", description="Frequently asked questions"),
        BotCommand(command="commands", description="Full command list"),
        BotCommand(command="dashboard", description="Open the owner/dispatcher web dashboard"),
        BotCommand(command="link", description="Direct dashboard link, for any browser"),
        BotCommand(command="verify2fa", description="Link this chat for 2FA codes"),
        BotCommand(command="linkdriver", description="Link this group to a driver (Settings → Drivers)"),
        BotCommand(command="dispatch", description="Find/build a load's RC and post it (driver group)"),
        BotCommand(command="loadpics", description="AI review of load photos (driver group)"),
        BotCommand(command="bol", description="Compare BOL against the RC (driver group)"),
        BotCommand(command="pod", description="Forward the POD to the broker (driver group)"),
        BotCommand(command="detention", description="Request detention/layover pay (driver group)"),
        BotCommand(command="setvehicle", description="Link this group to a Samsara vehicle"),
        BotCommand(command="readbio", description="Re-read this group's description (driver group)"),
        BotCommand(command="myid", description="Print the current chat/group ID"),
    ])

    if TELEGRAM_PROXY_URL:
        logger.info("Connecting to Telegram via proxy: %s", TELEGRAM_PROXY_URL)
    else:
        logger.info("Connecting to Telegram directly (no proxy configured).")

    asyncio.create_task(location_monitor_loop())
    asyncio.create_task(trial_reminder_loop())

    retry_delay = 5
    max_retry_delay = 60

    while True:
        try:
            await dp.start_polling(bot)
            break  # start_polling only reaches here when stopped (Ctrl+C)
        except TelegramNetworkError as e:
            logger.error(
                "Could not connect to Telegram (%s). Retrying in %s seconds. "
                "If this keeps happening, consider setting TELEGRAM_PROXY_URL in .env.",
                e, retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error in start_polling. Retrying in %s seconds.", retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped (Ctrl+C).")
