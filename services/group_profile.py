"""Reads a truck's Telegram group bio and proposes what it says.

Carriers run one Telegram group per truck. The unit number, the trailer, the
driver and their phone number go in the group's title and description, typed
by whoever set the group up - so no two are laid out the same way, and some
carry a co-driver, a VIN or an email while others do not.

That makes it a reading job rather than a parsing one, which is why the
extraction goes through Gemini (services/gemini_service.py). It also makes it
something to check: a bio is a note a dispatcher wrote, and it can be stale,
half-edited, or about a different truck than the one the driver is assigned
to. So nothing here writes to Driver or Truck. It reads, it says what it
found and what disagrees with the records, and it waits for a person to
confirm - from the dashboard or from Telegram, either one.
"""
from __future__ import annotations

import logging
import re

import requests

from config import TELEGRAM_BOT_TOKEN
from db import repository
from services import gemini_service

logger = logging.getLogger(__name__)

# A US truck VIN is 17 characters and never uses I, O or Q. Anything else in
# that field was misread or is not a VIN, and is worth a person's attention.
VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)

FIELD_LABELS = {
    "truck_number": "Truck #",
    "trailer_number": "Trailer #",
    "driver_name": "Driver",
    "driver_phone": "Phone",
    "co_driver_name": "Co-driver",
    "co_driver_phone": "Co-driver phone",
    "vin": "VIN",
    "driver_email": "Email",
}
FIELD_ORDER = list(FIELD_LABELS)


def clean_fields(raw: dict) -> dict:
    """Keeps the fields we know about and drops empty ones.

    Gemini is asked for null where a value is absent, but "N/A", "-" and an
    empty string all turn up in bios and all mean the same thing."""
    out: dict[str, str] = {}
    for key in FIELD_ORDER:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text or text.lower() in {"n/a", "na", "none", "-", "--", "null", "unknown"}:
            continue
        out[key] = text
    return out


def find_conflicts(fields: dict, driver_details: dict | None) -> list[str]:
    """Says what the bio disagrees with, in words a dispatcher can act on.

    Disagreement is not an error and never blocks confirming - the bio is
    often the thing that is right, and the records the thing that is stale.
    It is surfaced so the person confirming knows what they are changing."""
    conflicts: list[str] = []
    if not driver_details:
        driver_details = {}

    on_file_truck = (driver_details.get("truck_unit_number") or "").strip()
    from_bio_truck = fields.get("truck_number", "")
    if on_file_truck and from_bio_truck and on_file_truck != from_bio_truck:
        conflicts.append(
            f"The bio says truck {from_bio_truck}, but this driver is assigned to {on_file_truck}."
        )

    on_file_name = (driver_details.get("full_name") or "").strip()
    from_bio_name = fields.get("driver_name", "")
    if on_file_name and from_bio_name and on_file_name.casefold() != from_bio_name.casefold():
        conflicts.append(
            f"The bio names {from_bio_name}, but this driver is on file as {on_file_name}."
        )

    vin = fields.get("vin")
    if vin and not VIN_PATTERN.match(vin):
        conflicts.append(
            f"{vin} is not a valid VIN - a VIN is 17 characters and never uses I, O or Q."
        )

    for key in ("driver_phone", "co_driver_phone"):
        phone = fields.get(key)
        if phone and len(re.sub(r"\D", "", phone)) < 10:
            conflicts.append(f"{FIELD_LABELS[key]} {phone} is short for a US number.")

    return conflicts


async def read_and_propose(bot, *, company_id: int, driver_id: int, chat_id: int) -> dict | None:
    """Reads the group's bio and records what it says, for confirmation.

    Returns the proposal, or None when there was nothing to read or nothing
    could be made of it. Every failure here is logged and swallowed: this
    runs right after a group is linked, and linking a group must not fail
    because a bio was empty or Gemini was having a bad minute."""
    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        logger.warning("Could not read group %s: %s: %s", chat_id, type(e).__name__, e)
        return None

    title = getattr(chat, "title", None)
    description = getattr(chat, "description", None)
    if not (description or "").strip() and not (title or "").strip():
        logger.info("Group %s has no title or description to read.", chat_id)
        return None

    try:
        raw = gemini_service.extract_group_profile(title, description)
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        logger.warning("Could not read the bio of group %s: %s: %s", chat_id, type(e).__name__, e)
        return None

    fields = clean_fields(raw)
    if not fields:
        logger.info("Nothing recognisable in the bio of group %s.", chat_id)
        return None

    unclear = [k for k in (raw.get("unclear") or []) if k in fields]
    details = repository.get_driver_identity(driver_id, company_id)
    conflicts = find_conflicts(fields, details)

    return repository.save_group_profile_proposal(
        company_id,
        driver_id,
        chat_id,
        title=title,
        description=description,
        fields=fields,
        unclear=unclear,
        conflicts=conflicts,
    )


def summarise(proposal: dict) -> str:
    """One plain line, for a notification body.

    describe() builds the Telegram message and is full of HTML tags, which
    would be shown literally anywhere that is not Telegram - the dashboard
    list and an email both being that."""
    fields = proposal.get("fields") or {}
    parts = [
        f"{FIELD_LABELS[key]} {fields[key]}"
        for key in ("truck_number", "trailer_number", "driver_name")
        if key in fields
    ]
    read = ", ".join(parts) if parts else "some details"

    conflicts = proposal.get("conflicts") or []
    if len(conflicts) == 1:
        return f"{read}. One thing disagrees with what is on file."
    if conflicts:
        return f"{read}. {len(conflicts)} things disagree with what is on file."
    return f"{read}. Nothing disagrees with what is on file."


def describe(proposal: dict) -> str:
    """The proposal as a person reads it, for the Telegram message."""
    fields = proposal.get("fields") or {}
    unclear = set(proposal.get("unclear") or [])

    lines = ["<b>From this group's description:</b>", ""]
    for key in FIELD_ORDER:
        if key not in fields:
            continue
        mark = "  ⚠️ check this" if key in unclear else ""
        lines.append(f"{FIELD_LABELS[key]}: <b>{fields[key]}</b>{mark}")

    conflicts = proposal.get("conflicts") or []
    if conflicts:
        lines.append("")
        for note in conflicts:
            lines.append(f"⚠️ {note}")

    lines.append("")
    lines.append("Confirm to save this to the dashboard, or edit it there instead.")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Writing the description back
#
# The other direction. Once a person has confirmed what the bio said - from
# the group or from the dashboard - the confirmed record is written back
# into the group's description, so the two stop disagreeing.
#
# This overwrites whatever a dispatcher typed there. That is the point: the
# text was read, checked and confirmed by a person, so the record is now
# the better copy. It is also why nothing writes without a confirmation.
# ------------------------------------------------------------------

# setChatDescription accepts 0-255 characters and refuses anything longer,
# so the fields go in by priority and stop when the next one would not fit.
DESCRIPTION_LIMIT = 255
TELEGRAM_TIMEOUT_SECONDS = 10


def compose_bio(details: dict) -> str:
    """The confirmed details as a group description.

    Written in the shape carriers already use - "Truck#", "Driver:",
    "CO-driver:" - for two reasons. It reads the way a dispatcher expects,
    and it is a shape extract_group_profile can read back, so a group whose
    description this wrote can still be re-read by /readbio without the
    round trip losing anything."""

    def value(key: str) -> str | None:
        raw = details.get(key)
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    truck, trailer = value("truck_unit_number"), value("trailer_number")
    first = " | ".join(
        part for part in (
            f"Truck# {truck}" if truck else None,
            f"Trailer# {trailer}" if trailer else None,
        ) if part
    )

    driver, phone = value("full_name"), value("phone")
    second = " | ".join(
        part for part in (
            f"Driver: {driver}" if driver else None,
            phone,
        ) if part
    )

    co, co_phone = value("co_driver_name"), value("co_driver_phone")
    third = " | ".join(
        part for part in (
            f"CO-driver: {co}" if co else None,
            co_phone,
        ) if part
    )

    # Ordered by what a dispatcher needs at a glance. VIN and email are
    # real but rarely urgent, so they are what gets dropped if the 255
    # characters run out.
    lines = [line for line in (first, second, third) if line]
    vin = value("vin")
    if vin:
        lines.append(f"VIN# {vin}")
    email = value("email")
    if email:
        lines.append(email)

    kept: list[str] = []
    for line in lines:
        candidate = "\n".join(kept + [line])
        if len(candidate) > DESCRIPTION_LIMIT:
            break
        kept.append(line)
    return "\n".join(kept)


def publish_bio(company_id: int, driver_id: int) -> dict:
    """Writes the driver's confirmed details into their group description.

    Reached over plain HTTP rather than through aiogram, because this runs
    in the API process as often as in the bot's and those share neither a
    Bot instance nor an event loop.

    Every failure is reported and swallowed. Confirming the details is the
    thing that mattered, and it already succeeded by the time this runs -
    a group where the bot was never made an admin should not turn a
    successful confirmation into an error."""
    if not TELEGRAM_BOT_TOKEN:
        return {"written": False, "reason": "no bot token"}

    details = repository.get_driver_identity(driver_id, company_id)
    if not details:
        return {"written": False, "reason": "driver not found"}

    chat_id = details.get("telegram_group_id")
    if not chat_id:
        return {"written": False, "reason": "no group linked"}

    text = compose_bio(details)
    if not text:
        # Nothing confirmed yet. Blanking a description somebody wrote by
        # hand because our own record is empty would be pure loss.
        return {"written": False, "reason": "nothing to write"}

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setChatDescription",
            json={"chat_id": chat_id, "description": text},
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
        if not response.ok:
            # The ordinary failure is the bot not being an admin with
            # "Change group info", which is a setup problem in Telegram
            # rather than a bug here.
            logger.warning(
                "Couldn't write the description of group %s: HTTP %s: %s",
                chat_id, response.status_code, response.text[:200],
            )
            return {"written": False, "reason": f"HTTP {response.status_code}"}
    except Exception as e:  # noqa: BLE001 - reported, not swallowed silently
        logger.warning(
            "Couldn't write the description of group %s: %s: %s",
            chat_id, type(e).__name__, e,
        )
        return {"written": False, "reason": type(e).__name__}

    logger.info("Wrote the description of group %s (%s chars).", chat_id, len(text))
    return {"written": True, "text": text}
