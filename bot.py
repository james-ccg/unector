"""
Freight Pilot Bot - main entry point.

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

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BotCommand

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_PROXY_URL,
    SAMSARA_NEARBY_MILES,
    SAMSARA_POLL_INTERVAL_SECONDS,
    MINIAPP_URL,
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
    consume_telegram_link_token,
    set_telegram_otp,
)
from services import gemini_service, email_service, samsara_service, geo_utils

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
        "👋 **Welcome to Freight Pilot!**\n\n"
        "I help trucking companies automate dispatch: I pull rate confirmations from email, "
        "extract load details with AI, check your BOL/POD photos, and track GPS proximity to "
        "pickup/delivery.\n\n"
        "**Commands:**\n"
        "• /dispatch <id> - find and post a load's rate confirmation\n"
        "• /loadpics - (photo caption) AI reviews your load photos\n"
        "• /bol - (photo/document caption) compares the BOL against the RC\n"
        "• /pod - (photo/document caption) forwards the POD to the broker\n"
        "• /detention - request detention/layover pay from the broker\n"
        "• /setvehicle <id> - link this group to a Samsara vehicle for GPS alerts\n"
        "• /dashboard - open the owner/dispatcher web dashboard\n"
        "• /faq - frequently asked questions\n"
        "• /commands - full command list\n\n"
        "The load commands only work inside your driver+dispatch group - if you're not sure "
        "where that is, ask your dispatcher.",
        parse_mode="Markdown",
    )


@dp.message(Command("faq"))
async def handle_faq(message: Message):
    """Frequently asked questions - mirrors the web dashboard's FAQ page."""
    await message.reply(
        "**Frequently Asked Questions**\n\n"
        "**What is Freight Pilot?**\n"
        "An AI-powered dispatch management system that automates load management through "
        "Telegram - connects Gmail, extracts load details with AI, tracks GPS, and gives "
        "owners/dispatchers a real-time web dashboard.\n\n"
        "**How does billing work?**\n"
        "Free to look around. Pro is $20/mo (or $200/yr) for up to 5 active drivers. Max "
        "plans are $100/mo for up to 25 drivers, or $200/mo for up to 100 drivers. Every "
        "paid plan starts with a 7-day free trial.\n\n"
        "**How does Gmail integration work?**\n"
        "A secure OAuth 2.0 connection - the owner authorizes it once from the dashboard. "
        "The bot then automatically finds rate confirmations in that inbox.\n\n"
        "**How does GPS tracking work?**\n"
        "Through a Samsara integration - it checks each vehicle's GPS position every "
        "couple of minutes and automatically notifies the driver's group when they're "
        "near pickup or delivery.\n\n"
        "**What does the AI do?**\n"
        "Google Gemini extracts every load detail from a rate confirmation - load ID, "
        "addresses, dates, broker, rate, and more - eliminating manual data entry.\n\n"
        "**Can I add dispatchers?**\n"
        "Yes - add as many dispatchers as you need, each with their own dashboard login "
        "and permissions.\n\n"
        "For the full command list, use /commands. For anything else, use /dashboard to reach "
        "the web dashboard, or /link for the direct URL.",
        parse_mode="Markdown",
    )


@dp.message(Command("commands"))
async def handle_commands(message: Message):
    """Full command reference - everything /start only summarizes."""
    await message.reply(
        "**Full Command List**\n\n"
        "**Anywhere:**\n"
        "• /start - welcome message and command summary\n"
        "• /faq - frequently asked questions\n"
        "• /commands - this list\n"
        "• /dashboard - open the owner/dispatcher web dashboard\n"
        "• /link - direct dashboard link, for opening in any browser\n"
        "• /verify2fa <code> - links this chat for 2FA codes (code from Settings → Security)\n"
        "• /myid - prints the current chat/group ID\n\n"
        "**Inside a driver+dispatch group only:**\n"
        "• /dispatch <id> - finds the rate confirmation email and posts it to the group. "
        "With no id but a PDF attached, replied to, or sent alongside it, builds the load "
        "directly from that PDF instead\n"
        "• /loadpics - (photo caption) AI reviews load photos - send up to 10 as one album\n"
        "• /bol - (photo/document caption) compares the BOL against the RC\n"
        "• /pod - (photo/document caption) forwards the POD straight to the broker\n"
        "• /detention - sends a detention/layover request to the broker, citing the RC's "
        "terms, and notifies the dispatcher - send it when the driver is actually held\n"
        "• /setvehicle <id> - links this group's driver to a Samsara vehicle for GPS alerts",
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
        f"🔗 **Freight Pilot Dashboard Link**\n\n"
        f"`{MINIAPP_URL}`\n\n"
        f"📱 **How to use:**\n"
        f"• Copy the link above\n"
        f"• Open it in any browser (Chrome, Safari, Firefox)\n"
        f"• Works on: Phone 📱 • Computer 💻 • Tablet 📱\n\n"
        f"💡 **You can:**\n"
        f"• Share it with your team\n"
        f"• Bookmark it for quick access\n"
        f"• Open it from anywhere, anytime\n\n"
        f"🔐 Login required: Owner (MC#) or Dispatcher credentials",
        parse_mode="Markdown"
    )


@dp.message(Command("verify2fa"))
async def handle_verify2fa(message: Message):
    """Links this Telegram account to a Freight Pilot login, so it can be
    used to receive 2FA codes. Usage: /verify2fa <code shown on the
    Settings > Security page>"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "Usage: /verify2fa <code>\n\n"
            "Get a code from Settings → Security → Telegram in the Freight Pilot dashboard."
        )
        return

    code = args[1].strip().upper()
    result = consume_telegram_link_token(code)
    if not result:
        await message.reply("❌ That code is invalid or has expired. Generate a new one from Settings → Security.")
        return

    set_telegram_otp(result["account_type"], result["account_id"], message.from_user.id, enabled=True)
    await message.reply(
        "✅ Telegram linked! You can now receive verification codes here, and enable "
        "Telegram as a two-factor method in Settings → Security."
    )


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
            f"📊 **Freight Pilot Dashboard**\n\n"
            f"To access the dashboard from any device:\n\n"
            f"**Option 1 (Telegram):**\n"
            f"Open a private chat with me and send /dashboard\n\n"
            f"**Option 2 (Direct link):**\n"
            f"Open this link in any browser:\n"
            f"`{MINIAPP_URL}`\n\n"
            f"Works on: 📱 Phone • 💻 Computer • 📱 Tablet",
            parse_mode="Markdown"
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Open Freight Pilot Dashboard", web_app=WebAppInfo(url=MINIAPP_URL))],
            [InlineKeyboardButton(text="🔗 Direct Link", url=MINIAPP_URL)]
        ]
    )
    await message.reply(
        "**📊 Freight Pilot Dashboard**\n\n"
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
        await message.reply("⚙️ This feature isn't fully set up yet (waiting on database connection).")
        return

    if not driver:
        await message.reply("⚠️ This group isn't linked to a driver account yet. Please contact your dispatcher.")
        return

    vehicle_id = args[1].strip()
    set_driver_vehicle(driver.id, vehicle_id)
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
            "⚙️ This feature isn't fully set up yet (waiting on database connection). "
            "It'll be ready soon."
        )
        return None

    if not driver:
        await message.reply("⚠️ This group isn't linked to a driver account yet. Please contact your dispatcher.")
        return None

    return driver, get_company(driver.company_id)


async def _post_load_template(message: Message, driver, company, load_id: str, pdf_bytes: bytes):
    """Extracts RC data from `pdf_bytes`, geocodes, saves the load, and
    posts the formatted template to the group - the tail end both the
    email-search and direct-PDF paths share."""
    try:
        data = gemini_service.extract_rc_data(pdf_bytes)

        # Geocode the pickup/delivery addresses now, so the location monitor
        # has coordinates to compare against later - no need to re-geocode
        # every time we poll Samsara.
        pu_coords = await geo_utils.geocode_address(data.get("pu_address"))
        if pu_coords:
            data["pu_lat"], data["pu_lng"] = pu_coords
        del_coords = await geo_utils.geocode_address(data.get("del_address"))
        if del_coords:
            data["del_lat"], data["del_lng"] = del_coords

        save_load(company.id, driver.id, load_id, data)
    except Exception:
        logger.exception("Failed to extract/save RC data for load %s", load_id)
        await message.reply(
            f"⚠️ Found the RC, but something went wrong while processing it "
            f"(load {load_id}). Please try again, or check the logs."
        )
        return

    text = format_load_template(load_id, data)
    dispatcher_tag = f"@{driver.dispatcher_username}" if driver.dispatcher_username else ""
    driver_tag = f"@{driver.telegram_username}" if driver.telegram_username else ""

    await message.answer(f"{text}\n\n{driver_tag} {dispatcher_tag}", parse_mode="HTML")


async def _dispatch_by_load_number(message: Message, driver, company, load_id: str):
    """/dispatch <number> - searches the connected inbox for the RC."""
    await message.reply(f"🔎 Checking email for load {load_id}...")

    try:
        pdf_bytes = email_service.find_rc_pdf_by_load_id(company.id, load_id)
    except NotImplementedError as e:
        await message.reply(f"⚙️ Email integration isn't connected yet.\n({e})")
        return

    if pdf_bytes is None:
        await message.reply(f"❌ No RC email found for load {load_id}.")
        return

    await _post_load_template(message, driver, company, load_id, pdf_bytes)


async def _dispatch_from_pdf(message: Message, driver, company, document):
    """Bare /dispatch (no load number) with a PDF attached or replied to -
    builds the template directly from that PDF instead of searching email.
    The load number itself comes from Gemini's own extraction (RCs list
    their own load/order number), with a placeholder fallback if it can't
    find one, so this never just dead-ends."""
    if not await _validate_document(document, message):
        return

    await message.reply("🔎 Reading the attached PDF...")
    pdf_bytes, _mime_type = await _download_document(document)

    try:
        data = gemini_service.extract_rc_data(pdf_bytes)
    except Exception:
        logger.exception("Failed to extract RC data from attached PDF")
        await message.reply("⚠️ Something went wrong while reading that PDF. Please try again.")
        return

    load_id = data.get("load_id") or f"PDF-{message.message_id}"
    if not data.get("load_id"):
        await message.reply(
            "⚠️ Couldn't find a load number on this PDF - using a placeholder ID "
            f"({load_id}). Re-run with /dispatch <load number> if you know it."
        )

    await _post_load_template(message, driver, company, load_id, pdf_bytes)


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
        "Usage: /dispatch <load number>  (e.g. /dispatch 11111)\n\n"
        "Or attach a PDF (or reply to one) with /dispatch and no number to build "
        "the load straight from that PDF instead of searching email."
    )


# These four lines are the carrier's own standing policy - they must appear
# in every load message exactly as written, regardless of what the RC says.
MANDATORY_NOTES = [
    "MUST ACCEPT TRUCKING WHICH BROKER SENT, BROKER MIGHT CHARGE FOR NOT ACCEPTING",
    "LATE FEE; $500",
    "PLEASE USE STRAPS AND LOADBARS TO SECURE THE LOAD",
    "MUST SCALE AFTER PU (IF MORE THAN 35,000 LBS) $100 CHARGE IF NOT SCALE",
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


def format_load_template(load_id: str, data: dict) -> str:
    """Turns the JSON extracted from the RC into the dispatch group's message template.
    Uses Telegram HTML formatting - bold for section headers and value-carrying labels,
    blockquote for address/detail boxes, italic for the AI-generated summary. Every
    dynamic value is HTML-escaped, which is safer against special characters than
    Markdown mode.

    Note: Telegram only supports one visual style of blockquote - it can't be colored
    differently per section, so the PU address, the weight/commodity box, and the DEL
    address all render with the same left-bar/tinted-background look."""
    e = html.escape  # short alias, used a lot below

    broker = e(data.get("broker_name") or "—")
    carrier = e(data.get("carrier_name") or "")

    # --- Header: broker + carrier + LOAD# label are bold, the load number itself is plain ---
    header_bold = f"📌Broker: {broker}"
    if carrier:
        header_bold += f"\n{carrier}"
    header_bold += "\nLOAD#:"
    lines = [f"<b>{header_bold}</b> {e(load_id)}"]
    lines.append("")

    # --- PU section ---
    lines.append("<b>🟢PU :1</b>")
    lines.append(f"<pre><code class='language-PERFORMANCE'>{e(data.get('pu_address') or '—')}</code></pre>")
    lines.append("")
    pu_date_time_bold = f"📅date: {e(data.get('pu_date') or '—')}\n🕔time:"
    lines.append(f"<b>{pu_date_time_bold}</b> {e(_normalize_time(data.get('pu_time')) or '—')}")
    lines.append("")

    # --- Weight / Commodity / PU# box ---
    box_lines = []
    if data.get("weight"):
        box_lines.append(f"<b>⚖️Weight: {e(data['weight'])}</b>")
    box_lines.append(f"<b>📤Commodity:</b> {e(data.get('commodity') or '—')}")
    if data.get("reefer_temp"):
        box_lines.append(f"TEMP#: {e(data['reefer_temp'])}")
    if data.get("pu_reference"):
        box_lines.append(f"PU#: {e(data['pu_reference'])}")
    box_content = "\n".join(box_lines)
    lines.append(f"<blockquote>{box_content}</blockquote>")
    lines.append("")
    lines.append("")

    # --- DEL section ---
    lines.append("<b>🔴DEL:</b>")
    lines.append(f"<pre><code class='language-PERFORMANCE'>{e(data.get('del_address') or '—')}</code></pre>")
    lines.append("")
    del_date_time_bold = f"📅date: {e(data.get('del_date') or '—')}\n🕔time:"
    lines.append(f"<b>{del_date_time_bold}</b> {e(_normalize_time(data.get('del_time')) or '—')}")
    lines.append("")

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


@dp.message(F.photo)
async def handle_photo_message(message: Message):
    group_id = message.media_group_id

    if not group_id:
        # Not part of an album - handle it right away as a single-photo group.
        await _process_photo_group([message])
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
    await _process_photo_group(entry["messages"])


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
        result = gemini_service.check_load_picture(rc_json, files)
    except Exception:
        logger.exception("Failed to review load photo(s) for chat %s", chat_id)
        await bot.send_message(chat_id, "⚠️ Something went wrong while reviewing the photos. Please try again.")
        return

    if result.get("loading_ok") and load:
        update_load_status(load.id, "loaded")

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
        f"<b>Bol</b> - {bol_weight}",
        f"<b>Rc</b> - {rc_weight}",
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
    lines.append(f"<b>Del address:</b>")
    blockquote_lines = [
        f"<b>Bol</b> - <i>{bol_addr}</i>",
        f"<b>Rc</b> - <i>{rc_addr}</i>",
        f"<b>Status</b> - {addr_status} {addr_emoji}"
    ]
    lines.append(f"<blockquote>{'&#10;'.join(blockquote_lines)}</blockquote>")
    lines.append("")

    # Temperature section
    temp = result.get("temperature", {})
    rc_temp = g(temp, "rc", "didn't show")
    bol_temp = g(temp, "bol", "didn't show")
    temp_status = g(temp, "status", "Not checked")
    lines.append(f"<b>Temp:</b>")
    blockquote_lines = [
        f"<b>Rc</b> - {rc_temp}",
        f"<b>Bol</b> - {bol_temp}",
        f"<b>Status</b> - {temp_status}"
    ]
    lines.append(f"<blockquote>{'&#10;'.join(blockquote_lines)}</blockquote>")
    lines.append("")

    # Seal match status section
    seal = result.get("seal", {})
    seal_summary = g(seal, "summary", "Not checked")
    lines.append(f"<b>Seal match status:</b>")
    lines.append(seal_summary)
    lines.append("")

    # Final verdict
    if result.get("mismatches") and len(result["mismatches"]) > 0:
        lines.append("<b>Please review before proceeding.</b>")
    else:
        lines.append("<b>Good to go!</b>")

    return "\n".join(lines)


async def _run_bol(chat_id: int, trigger_message: Message, files: list[tuple[bytes, str]]):
    try:
        load = get_load_by_group(chat_id)
    except NotImplementedError:
        await bot.send_message(chat_id, "⚙️ This feature isn't fully set up yet (waiting on database connection).")
        return

    if not load or not load.raw_extracted_json:
        await bot.send_message(chat_id, "⚠️ Please load the RC first using /dispatch.")
        return

    label = "document" if len(files) == 1 else f"{len(files)} documents"
    await bot.send_message(chat_id, f"🔍 Comparing the {label} against the rate confirmation...")

    try:
        result = gemini_service.compare_bol_with_rc(load.raw_extracted_json, files)
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
            email_service.send_email(
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
        await bot.send_message(chat_id, "⚙️ This feature isn't fully set up yet (waiting on database connection).")
        return

    if not load or not load.raw_extracted_json:
        await bot.send_message(chat_id, "⚠️ Please load the RC first using /dispatch.")
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
        email_service.send_email(
            company_id=load.company_id,
            to_address=broker_email,
            subject=f"Load #{load.load_id} — POD",
            body=f"Please find the proof of delivery attached for load #{load.load_id}.",
            attachments=attachments,
        )
    except NotImplementedError as e:
        await bot.send_message(chat_id, f"⚙️ Email integration isn't connected yet.\n({e})")
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
        await message.reply("⚙️ This feature isn't fully set up yet (waiting on database connection).")
        return

    if not driver:
        await message.reply("⚠️ This group isn't linked to a driver account yet. Please contact your dispatcher.")
        return

    load = get_load_by_group(message.chat.id)
    if not load or not load.raw_extracted_json:
        await message.reply("⚠️ No active load found for this group. Please load the RC first using /dispatch.")
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
        email_service.send_email(
            company_id=load.company_id,
            to_address=broker_email,
            subject=f"Load #{load.load_id} — Detention/Layover Request",
            body=(
                f"This is a detention/layover request for load #{load.load_id}, per the "
                f"rate confirmation's stated terms:\n\n{terms}\n\nPlease advise on next steps."
            ),
        )
    except NotImplementedError as e:
        await message.reply(f"⚙️ Email integration isn't connected yet.\n({e})")
        return
    except Exception:
        logger.exception("Failed to send detention request for load %s", load.load_id)
        await message.reply("⚠️ Something went wrong while sending the detention request. Please try again.")
        return

    mark_detention_requested(load.id)

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
    await message.reply("Please send the BOL photo(s) or file with the /bol caption.")


@dp.message(_command_filter("pod"))
async def handle_pod_no_attachment(message: Message):
    """Reached only when /pod was sent with no photo/document attached."""
    await message.reply("Please send the POD photo(s) or file with the /pod caption.")


@dp.message(_command_filter("loadpics"))
async def handle_loadpics_no_attachment(message: Message):
    """Reached only when /loadpics was sent with no photo attached."""
    await message.reply("Please send the load photo(s) with the /loadpics caption.")


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


async def _check_all_loads_once():
    for load in get_active_loads_for_monitoring():
        try:
            location = await samsara_service.get_vehicle_location(load.company_id, load.samsara_vehicle_id)
        except NotImplementedError:
            continue  # this company hasn't connected Samsara yet
        except Exception:
            logger.exception("Failed to fetch Samsara location for vehicle %s", load.samsara_vehicle_id)
            continue

        if not location or location.get("lat") is None:
            continue

        # Still heading to pickup: check distance to PU, only if not already alerted.
        if load.status == "dispatched" and not load.notified_pu_near and load.pu_lat is not None:
            distance = geo_utils.haversine_miles(location["lat"], location["lng"], load.pu_lat, load.pu_lng)
            if distance <= SAMSARA_NEARBY_MILES:
                await bot.send_message(
                    load.telegram_group_id,
                    f"📍 Driver is ~{distance:.0f} miles from pickup on load #{load.load_id}. "
                    "We'll inform you once he checks in.",
                )
                mark_notified(load.id, "pu")

        # Already loaded: check distance to delivery instead.
        elif load.status in ("loaded", "bol_ok") and not load.notified_del_near and load.del_lat is not None:
            distance = geo_utils.haversine_miles(location["lat"], location["lng"], load.del_lat, load.del_lng)
            if distance <= SAMSARA_NEARBY_MILES:
                await bot.send_message(
                    load.telegram_group_id,
                    f"📍 Driver is ~{distance:.0f} miles from delivery on load #{load.load_id}. "
                    "We'll inform you once he checks in.",
                )
                mark_notified(load.id, "del")


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
        BotCommand(command="dispatch", description="Find/build a load's RC and post it (driver group)"),
        BotCommand(command="loadpics", description="AI review of load photos (driver group)"),
        BotCommand(command="bol", description="Compare BOL against the RC (driver group)"),
        BotCommand(command="pod", description="Forward the POD to the broker (driver group)"),
        BotCommand(command="detention", description="Request detention/layover pay (driver group)"),
        BotCommand(command="setvehicle", description="Link this group to a Samsara vehicle"),
        BotCommand(command="myid", description="Print the current chat/group ID"),
    ])

    if TELEGRAM_PROXY_URL:
        logger.info("Connecting to Telegram via proxy: %s", TELEGRAM_PROXY_URL)
    else:
        logger.info("Connecting to Telegram directly (no proxy configured).")

    asyncio.create_task(location_monitor_loop())

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
