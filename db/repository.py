"""
Functions for talking to the database (repository layer).
bot.py never writes raw SQL/ORM code directly -- everything is centralized here.

Functions here convert db/models.py ORM objects into lightweight dataclasses,
so bot.py stays independent of DB implementation details.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from config import encrypt_value, decrypt_value
from db.database import get_session
from db import models

# A load counts toward gross revenue once it's actually been loaded, not just
# booked/dispatched - "pod_sent" is the real terminal status set by bot.py
# once the POD goes out; "delivered" doesn't exist anywhere else and nothing
# ever sets it, so including it here silently excluded every completed load.
GROSS_ELIGIBLE_STATUSES = ("loaded", "bol_ok", "pod_sent")


def current_week_start_utc() -> datetime:
    """Monday 00:00 UTC of the current week. Uses UTC rather than server-local
    time since created_at is stored in UTC - comparing against local time would
    shift the week boundary by the server's UTC offset."""
    today = models.now_utc()
    week_start = today - timedelta(days=today.weekday())
    return week_start.replace(hour=0, minute=0, second=0, microsecond=0)


def _to_float(value) -> float | None:
    """Safely converts a value like '2,300.00' or '$2,300' (as returned by
    Gemini) into a float. Returns None if it can't be parsed."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


@dataclass
class Driver:
    id: int
    company_id: int
    driver_bot_id: str
    telegram_username: str | None
    dispatcher_username: str | None
    telegram_group_id: int | None = None
    telegram_group_title: str | None = None
    samsara_vehicle_id: str | None = None


@dataclass
class Company:
    id: int
    mc_number: str
    company_name: str
    password_hash: str | None = None
    email: str | None = None


@dataclass
class Load:
    id: int
    company_id: int
    driver_id: int
    load_id: str
    raw_extracted_json: dict
    detention_requested_at: datetime | None = None


def get_driver_by_group(telegram_group_id: int) -> Driver | None:
    """Finds the driver linked to this Telegram group ID."""
    with get_session() as session:
        row = (
            session.query(models.Driver)
            .filter(models.Driver.telegram_group_id == telegram_group_id)
            .first()
        )
        if not row:
            return None
        dispatcher_username = row.dispatcher.username if row.dispatcher else None
        return Driver(
            id=row.id,
            company_id=row.company_id,
            driver_bot_id=row.driver_bot_id,
            telegram_username=row.telegram_username,
            dispatcher_username=dispatcher_username,
            telegram_group_id=row.telegram_group_id,
            telegram_group_title=row.telegram_group_title,
            # Resolved through the driver's truck - the column on drivers is
            # a leftover the trucks migration stopped writing to.
            samsara_vehicle_id=row.truck.samsara_vehicle_id if row.truck else None,
        )


def link_driver_group(driver_id: int, telegram_group_id: int, telegram_group_title: str | None) -> str:
    """Links a driver to the Telegram group /linkdriver was just sent in -
    the other half of the one-time-code flow started by create_driver's
    caller (see miniapp/api.py's POST /api/drivers and
    /api/drivers/{id}/link-token, and bot.py's handle_linkdriver). Returns
    "ok", "not_found" (bad driver_id - the driver was deleted after the code
    was generated), or "already_linked_elsewhere" (telegram_group_id is
    unique - this group already belongs to a different driver) rather than
    letting a raw IntegrityError surface to the bot handler."""
    with get_session() as session:
        driver = session.get(models.Driver, driver_id)
        if not driver:
            return "not_found"

        conflict = (
            session.query(models.Driver)
            .filter(models.Driver.telegram_group_id == telegram_group_id, models.Driver.id != driver_id)
            .first()
        )
        if conflict:
            return "already_linked_elsewhere"

        driver.telegram_group_id = telegram_group_id
        driver.telegram_group_title = telegram_group_title
        session.commit()
        return "ok"


def get_company(company_id: int) -> Company | None:
    with get_session() as session:
        row = session.get(models.Company, company_id)
        if not row:
            return None
        return Company(id=row.id, mc_number=row.mc_number, company_name=row.company_name)


def save_load(company_id: int, driver_id: int, load_id: str, extracted_data: dict) -> Load:
    """Creates a new load record (or updates it if this load_id already exists)."""
    with get_session() as session:
        row = (
            session.query(models.Load)
            .filter(
                models.Load.company_id == company_id,
                models.Load.load_id == load_id,
            )
            .first()
        )
        if row is None:
            row = models.Load(company_id=company_id, driver_id=driver_id, load_id=load_id)
            session.add(row)

        row.broker_name = extracted_data.get("broker_name")
        row.broker_contact_email = extracted_data.get("broker_contact_email")
        row.carrier_name = extracted_data.get("carrier_name")
        row.pu_address = extracted_data.get("pu_address")
        row.pu_date = extracted_data.get("pu_date")
        row.pu_time = extracted_data.get("pu_time")
        row.pu_reference = extracted_data.get("pu_reference")
        row.del_address = extracted_data.get("del_address")
        row.del_date = extracted_data.get("del_date")
        row.del_time = extracted_data.get("del_time")
        row.weight = extracted_data.get("weight")
        row.commodity = extracted_data.get("commodity")
        row.reefer_temp = extracted_data.get("reefer_temp")
        row.rate_amount = _to_float(extracted_data.get("rate_amount"))
        row.pu_lat = extracted_data.get("pu_lat")
        row.pu_lng = extracted_data.get("pu_lng")
        row.del_lat = extracted_data.get("del_lat")
        row.del_lng = extracted_data.get("del_lng")
        row.raw_extracted_json = extracted_data

        session.commit()
        session.refresh(row)

        return Load(
            id=row.id,
            company_id=row.company_id,
            driver_id=row.driver_id,
            load_id=row.load_id,
            raw_extracted_json=row.raw_extracted_json,
        )


def get_load_by_group(telegram_group_id: int) -> Load | None:
    """Finds the most recent (active) load for this Telegram group ID."""
    with get_session() as session:
        driver = (
            session.query(models.Driver)
            .filter(models.Driver.telegram_group_id == telegram_group_id)
            .first()
        )
        if not driver:
            return None

        row = (
            session.query(models.Load)
            .filter(models.Load.driver_id == driver.id)
            .order_by(models.Load.created_at.desc())
            .first()
        )
        if not row:
            return None

        return Load(
            id=row.id,
            company_id=row.company_id,
            driver_id=row.driver_id,
            load_id=row.load_id,
            raw_extracted_json=row.raw_extracted_json,
            detention_requested_at=row.detention_requested_at,
        )


# ------------------------------------------------------------------
# Company credentials (encrypted secrets like Gmail refresh tokens,
# Samsara API keys, etc.)
# ------------------------------------------------------------------
def save_company_credential(company_id: int, cred_type: str, plain_value: str) -> None:
    """Encrypts and stores a credential for a company (creates or overwrites)."""
    encrypted = encrypt_value(plain_value)
    with get_session() as session:
        row = (
            session.query(models.CompanyCredential)
            .filter(
                models.CompanyCredential.company_id == company_id,
                models.CompanyCredential.cred_type == cred_type,
            )
            .first()
        )
        if row is None:
            row = models.CompanyCredential(company_id=company_id, cred_type=cred_type)
            session.add(row)
        row.encrypted_value = encrypted
        session.commit()


def get_company_credential(company_id: int, cred_type: str) -> str | None:
    """Reads and decrypts a credential for a company. Returns None if not set."""
    with get_session() as session:
        row = (
            session.query(models.CompanyCredential)
            .filter(
                models.CompanyCredential.company_id == company_id,
                models.CompanyCredential.cred_type == cred_type,
            )
            .first()
        )
        if row is None:
            return None
        return decrypt_value(row.encrypted_value)


def delete_company_credential(company_id: int, cred_type: str) -> None:
    """Delete a credential for a company."""
    with get_session() as session:
        cred = session.query(models.CompanyCredential).filter_by(
            company_id=company_id, cred_type=cred_type
        ).first()
        if cred:
            session.delete(cred)
            session.commit()


def update_load_status(load_pk: int, status: str) -> None:
    """Updates a load's status (e.g. 'dispatched', 'loaded', 'bol_ok', 'pod_sent')."""
    with get_session() as session:
        row = session.get(models.Load, load_pk)
        if row:
            row.status = status
            session.commit()


# ------------------------------------------------------------------
# Samsara GPS monitoring
# ------------------------------------------------------------------
def set_driver_vehicle(driver_pk: int, samsara_vehicle_id: str) -> bool:
    """Links the Samsara vehicle ID to the truck this driver is on (used by
    /setvehicle). The device is fitted to the vehicle, so it belongs to the
    truck, not the person - which means the driver has to be on a truck for
    this to have anywhere to go. Returns False when they aren't, so the
    caller can say so rather than silently doing nothing."""
    with get_session() as session:
        driver = session.get(models.Driver, driver_pk)
        if not driver or not driver.truck_id:
            return False
        truck = session.get(models.Truck, driver.truck_id)
        if not truck:
            return False
        truck.samsara_vehicle_id = samsara_vehicle_id
        session.commit()
        return True


# ------------------------------------------------------------------
# Trucks and trailers - the fleet's own assets, managed by owner OR
# dispatcher. See models.Truck for why the truck (not the driver) is the
# unit dispatch organises around.
# ------------------------------------------------------------------
def list_trucks(company_id: int) -> list[dict]:
    """Every truck, with its current trailer and driver folded in - the
    dashboard shows all three together, so resolving them here keeps that to
    one query set instead of one per card."""
    with get_session() as session:
        trucks = (
            session.query(models.Truck)
            .filter(models.Truck.company_id == company_id)
            .order_by(models.Truck.unit_number)
            .all()
        )
        if not trucks:
            return []

        drivers = (
            session.query(models.Driver)
            .filter(models.Driver.truck_id.in_([t.id for t in trucks]))
            .all()
        )
        driver_by_truck = {d.truck_id: d for d in drivers}

        rows = []
        for t in trucks:
            driver = driver_by_truck.get(t.id)
            rows.append({
                "id": t.id,
                "unit_number": t.unit_number,
                "samsara_vehicle_id": t.samsara_vehicle_id,
                "active": t.active,
                "trailer": (
                    {"id": t.trailer.id, "unit_number": t.trailer.unit_number} if t.trailer else None
                ),
                "driver": (
                    {
                        "id": driver.id,
                        "full_name": driver.full_name,
                        "driver_bot_id": driver.driver_bot_id,
                        "telegram_group_title": driver.telegram_group_title,
                        "subscription_active": driver.subscription_active,
                    }
                    if driver else None
                ),
            })
        return rows


def create_truck(company_id: int, unit_number: str) -> dict | None:
    """None when that unit number is already on the books for this company -
    two trucks answering to "3001" would make every dispatch ambiguous."""
    unit_number = unit_number.strip()
    with get_session() as session:
        clash = (
            session.query(models.Truck)
            .filter(models.Truck.company_id == company_id, models.Truck.unit_number == unit_number)
            .first()
        )
        if clash:
            return None
        row = models.Truck(company_id=company_id, unit_number=unit_number)
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"id": row.id, "unit_number": row.unit_number, "active": row.active}


def delete_truck(truck_id: int, company_id: int) -> bool:
    with get_session() as session:
        row = (
            session.query(models.Truck)
            .filter(models.Truck.id == truck_id, models.Truck.company_id == company_id)
            .first()
        )
        if not row:
            return False
        # Unhook any driver first - the FK would otherwise leave them
        # pointing at a truck that no longer exists.
        session.query(models.Driver).filter(models.Driver.truck_id == truck_id).update(
            {"truck_id": None}, synchronize_session=False
        )
        session.delete(row)
        session.commit()
        return True


def assign_truck(truck_id: int, company_id: int, *, driver_id: int | None = ..., trailer_id: int | None = ...) -> bool:
    """Sets the truck's current driver and/or trailer. Ellipsis means "leave
    alone" so that None stays usable as a real value - unhooking the trailer
    or taking the driver off is exactly what this is for."""
    with get_session() as session:
        truck = (
            session.query(models.Truck)
            .filter(models.Truck.id == truck_id, models.Truck.company_id == company_id)
            .first()
        )
        if not truck:
            return False

        if trailer_id is not ...:
            if trailer_id is not None:
                trailer = (
                    session.query(models.Trailer)
                    .filter(models.Trailer.id == trailer_id, models.Trailer.company_id == company_id)
                    .first()
                )
                if not trailer:
                    return False
            truck.trailer_id = trailer_id

        if driver_id is not ...:
            # One driver per truck: clear whoever is on it now before seating
            # the new one, or a stale row would leave the truck showing two.
            session.query(models.Driver).filter(models.Driver.truck_id == truck_id).update(
                {"truck_id": None}, synchronize_session=False
            )
            if driver_id is not None:
                driver = (
                    session.query(models.Driver)
                    .filter(models.Driver.id == driver_id, models.Driver.company_id == company_id)
                    .first()
                )
                if not driver:
                    return False
                driver.truck_id = truck_id

        session.commit()
        return True


def delete_driver(driver_id: int, company_id: int) -> tuple[bool, str | None]:
    """Removes a driver. Returns (deleted, refusal_reason).

    Refuses while the driver still has loads against them: those rows carry
    the company's dispatch history and its gross figures, and cascading the
    delete would quietly rewrite past weeks' numbers. Deactivating the
    driver is the right move there, and the message says so."""
    with get_session() as session:
        row = (
            session.query(models.Driver)
            .filter(models.Driver.id == driver_id, models.Driver.company_id == company_id)
            .first()
        )
        if not row:
            return False, None

        load_count = session.query(models.Load).filter(models.Load.driver_id == driver_id).count()
        if load_count:
            return False, (
                f"This driver has {load_count} load(s) on record. Deleting them would remove that "
                "history from your totals - deactivate the driver instead."
            )

        session.delete(row)
        session.commit()
        return True, None


def list_trailers(company_id: int) -> list[dict]:
    with get_session() as session:
        rows = (
            session.query(models.Trailer)
            .filter(models.Trailer.company_id == company_id)
            .order_by(models.Trailer.unit_number)
            .all()
        )
        hooked = {
            t.trailer_id
            for t in session.query(models.Truck).filter(models.Truck.company_id == company_id).all()
            if t.trailer_id
        }
        return [
            {"id": r.id, "unit_number": r.unit_number, "in_use": r.id in hooked}
            for r in rows
        ]


def create_trailer(company_id: int, unit_number: str) -> dict | None:
    unit_number = unit_number.strip()
    with get_session() as session:
        clash = (
            session.query(models.Trailer)
            .filter(models.Trailer.company_id == company_id, models.Trailer.unit_number == unit_number)
            .first()
        )
        if clash:
            return None
        row = models.Trailer(company_id=company_id, unit_number=unit_number)
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"id": row.id, "unit_number": row.unit_number}


def delete_trailer(trailer_id: int, company_id: int) -> bool:
    with get_session() as session:
        row = (
            session.query(models.Trailer)
            .filter(models.Trailer.id == trailer_id, models.Trailer.company_id == company_id)
            .first()
        )
        if not row:
            return False
        # Unhook it from any truck first, same FK reason as delete_truck.
        session.query(models.Truck).filter(models.Truck.trailer_id == trailer_id).update(
            {"trailer_id": None}, synchronize_session=False
        )
        session.delete(row)
        session.commit()
        return True


@dataclass
class MonitoredLoad:
    id: int
    company_id: int
    load_id: str
    status: str
    telegram_group_id: int
    samsara_vehicle_id: str
    pu_lat: float | None
    pu_lng: float | None
    del_lat: float | None
    del_lng: float | None
    notified_pu_near: bool
    notified_del_near: bool
    alerted_rule_ids: list[int]


def get_active_loads_for_monitoring() -> list[MonitoredLoad]:
    """Returns every load that (a) isn't finished yet, (b) is on a truck with
    a Samsara vehicle linked, and (c) has at least one geocoded destination -
    i.e. everything the location-monitor loop needs to check on each pass.

    The GPS link now hangs off the truck rather than the driver (the device
    is fitted to the vehicle), so this reaches it through the driver's
    current truck."""
    with get_session() as session:
        rows = (
            session.query(models.Load, models.Driver, models.Truck)
            .join(models.Driver, models.Load.driver_id == models.Driver.id)
            .join(models.Truck, models.Driver.truck_id == models.Truck.id)
            .filter(models.Load.status.in_(["dispatched", "loaded", "bol_ok"]))
            .filter(models.Truck.samsara_vehicle_id.isnot(None))
            .filter(models.Driver.telegram_group_id.isnot(None))
            .all()
        )
        result = []
        for load, driver, truck in rows:
            result.append(
                MonitoredLoad(
                    id=load.id,
                    company_id=load.company_id,
                    load_id=load.load_id,
                    status=load.status,
                    telegram_group_id=driver.telegram_group_id,
                    samsara_vehicle_id=truck.samsara_vehicle_id,
                    pu_lat=float(load.pu_lat) if load.pu_lat is not None else None,
                    pu_lng=float(load.pu_lng) if load.pu_lng is not None else None,
                    del_lat=float(load.del_lat) if load.del_lat is not None else None,
                    del_lng=float(load.del_lng) if load.del_lng is not None else None,
                    notified_pu_near=load.notified_pu_near,
                    notified_del_near=load.notified_del_near,
                    alerted_rule_ids=load.alerted_rule_ids or [],
                )
            )
        return result


def mark_notified(load_pk: int, which: str) -> None:
    """Marks a load as having already sent its 'nearby' alert, so the monitor
    loop doesn't send it again. `which` is 'pu' or 'del'."""
    with get_session() as session:
        row = session.get(models.Load, load_pk)
        if not row:
            return
        if which == "pu":
            row.notified_pu_near = True
        elif which == "del":
            row.notified_del_near = True
        session.commit()


def mark_detention_requested(load_pk: int) -> None:
    """Marks a load as having already had its detention/layover email sent,
    so /detention can't fire it twice for the same load."""
    with get_session() as session:
        row = session.get(models.Load, load_pk)
        if row:
            row.detention_requested_at = models.now_utc()
            session.commit()


def mark_alert_rule_fired(load_pk: int, rule_id: int) -> None:
    """Records that a custom LocationAlertRule has already fired for a load,
    so the monitor loop's next pass doesn't send it again."""
    with get_session() as session:
        row = session.get(models.Load, load_pk)
        if not row:
            return
        fired = set(row.alerted_rule_ids or [])
        fired.add(rule_id)
        row.alerted_rule_ids = sorted(fired)
        session.commit()


# ---- Location alert rules (customizable GPS-proximity messages) ----
def _alert_rule_to_dict(row: models.LocationAlertRule) -> dict:
    return {
        "id": row.id,
        "scenario": row.scenario,
        "distance_miles": float(row.distance_miles),
        "message_template": row.message_template,
        "enabled": row.enabled,
    }


def create_alert_rule(
    company_id: int, scenario: str, distance_miles: float,
    message_template: str | None, enabled: bool = True,
) -> dict:
    with get_session() as session:
        row = models.LocationAlertRule(
            company_id=company_id,
            scenario=scenario,
            distance_miles=distance_miles,
            message_template=message_template,
            enabled=enabled,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _alert_rule_to_dict(row)


def list_alert_rules(company_id: int) -> list[dict]:
    """All of a company's rules, for the Settings page - both scenarios,
    furthest-out first within each."""
    with get_session() as session:
        rows = (
            session.query(models.LocationAlertRule)
            .filter(models.LocationAlertRule.company_id == company_id)
            .order_by(
                models.LocationAlertRule.scenario,
                models.LocationAlertRule.distance_miles.desc(),
            )
            .all()
        )
        return [_alert_rule_to_dict(r) for r in rows]


def get_enabled_alert_rules(company_id: int, scenario: str) -> list[dict]:
    """Rules for the location monitor - enabled only, furthest-out first so
    a driver's group gets the heads-up alert before the imminent-arrival one."""
    with get_session() as session:
        rows = (
            session.query(models.LocationAlertRule)
            .filter(
                models.LocationAlertRule.company_id == company_id,
                models.LocationAlertRule.scenario == scenario,
                models.LocationAlertRule.enabled.is_(True),
            )
            .order_by(models.LocationAlertRule.distance_miles.desc())
            .all()
        )
        return [_alert_rule_to_dict(r) for r in rows]


def update_alert_rule(rule_id: int, company_id: int, fields: dict) -> dict | None:
    """`fields` should only contain keys the caller actually wants to change
    (e.g. a Pydantic model dumped with exclude_unset=True) - every key in it
    is applied unconditionally, so there's no ambiguity between "leave this
    alone" and "set it to None/False"."""
    with get_session() as session:
        row = session.get(models.LocationAlertRule, rule_id)
        if not row or row.company_id != company_id:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()
        session.refresh(row)
        return _alert_rule_to_dict(row)


def delete_alert_rule(rule_id: int, company_id: int) -> bool:
    with get_session() as session:
        deleted = session.query(models.LocationAlertRule).filter(
            models.LocationAlertRule.id == rule_id,
            models.LocationAlertRule.company_id == company_id,
        ).delete()
        session.commit()
        return deleted > 0


# ------------------------------------------------------------------
# Mini App: owner/dispatcher auth and driver management
# ------------------------------------------------------------------
def get_company_by_mc(mc_number: str) -> Company | None:
    """Looks up a company by MC# - used for the owner's Mini App login."""
    with get_session() as session:
        row = session.query(models.Company).filter(models.Company.mc_number == mc_number).first()
        if not row:
            return None
        return Company(
            id=row.id, mc_number=row.mc_number, company_name=row.company_name,
            password_hash=row.password_hash, email=row.email,
        )


def get_companies_by_email(email: str) -> list[Company]:
    """Every company registered under an email address, for "Continue with
    Google" sign-in. Returns a list rather than one row because email is not
    unique-constrained - the caller decides what to do when an address maps
    to more than one account, instead of this silently picking the first.
    Matched case-insensitively: addresses arrive from Google normalized to
    lowercase, but older rows were stored however they were typed."""
    from sqlalchemy import func

    with get_session() as session:
        rows = (
            session.query(models.Company)
            .filter(func.lower(models.Company.email) == email.strip().lower())
            .all()
        )
        return [
            Company(
                id=r.id, mc_number=r.mc_number, company_name=r.company_name,
                password_hash=r.password_hash, email=r.email,
            )
            for r in rows
        ]


def get_company_email(company_id: int) -> str | None:
    """The address this company's Google account is connected as. Used as
    the login_hint on a reconnect, so Google reopens the mailbox that is
    already linked instead of asking which one - the moment an owner with
    two addresses connects the wrong inbox without noticing."""
    with get_session() as session:
        row = session.get(models.Company, company_id)
        return row.email if row and row.email else None


def set_company_email(company_id: int, email: str) -> None:
    """Records the address a company's Google account is connected as, so
    password reset and Google sign-in can find them later. Kept lowercase to
    match get_companies_by_email's comparison."""
    with get_session() as session:
        row = session.get(models.Company, company_id)
        if row:
            row.email = email.strip().lower()
            session.commit()


def set_company_password(company_id: int, password_hash: str) -> None:
    """Sets/updates the owner's Mini App login password (already hashed)."""
    with get_session() as session:
        row = session.get(models.Company, company_id)
        if row:
            row.password_hash = password_hash
            session.commit()


@dataclass
class DispatcherAuth:
    id: int
    company_id: int
    username: str
    password_hash: str


def get_dispatcher_by_username(username: str) -> DispatcherAuth | None:
    with get_session() as session:
        row = session.query(models.Dispatcher).filter(models.Dispatcher.username == username).first()
        if not row:
            return None
        return DispatcherAuth(
            id=row.id, company_id=row.company_id, username=row.username, password_hash=row.password_hash
        )


def create_dispatcher(company_id: int, username: str, password_hash: str) -> int:
    """Creates a new dispatcher login (already-hashed password) for a company."""
    with get_session() as session:
        row = models.Dispatcher(
            company_id=company_id, username=username, password_hash=password_hash, role="dispatcher"
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def update_dispatcher(
    dispatcher_id: int, company_id: int, *, username: str | None = None, password_hash: str | None = None,
) -> str | None:
    """Updates a dispatcher's username and/or password. Both the caller's
    company_id and the dispatcher's own must match - the API layer resolves
    the dispatcher by id alone, so this is the tenant-isolation check that
    stops one company's owner from editing another company's dispatcher.
    Returns "ok", "not_found" (wrong id or wrong company), or
    "username_taken" (usernames are unique across all companies)."""
    with get_session() as session:
        row = session.get(models.Dispatcher, dispatcher_id)
        if not row or row.company_id != company_id:
            return "not_found"
        if username is not None and username != row.username:
            existing = session.query(models.Dispatcher).filter(models.Dispatcher.username == username).first()
            if existing:
                return "username_taken"
            row.username = username
        if password_hash is not None:
            row.password_hash = password_hash
        session.commit()
        return "ok"


def delete_dispatcher(dispatcher_id: int, company_id: int) -> bool:
    """Deletes a dispatcher login. Returns False if it doesn't exist or
    belongs to a different company (see update_dispatcher's docstring)."""
    with get_session() as session:
        row = session.get(models.Dispatcher, dispatcher_id)
        if not row or row.company_id != company_id:
            return False
        session.delete(row)
        session.commit()
        return True


def create_driver(company_id: int, full_name: str) -> dict:
    """Creates a driver with no Telegram group linked yet - the owner links
    it afterward via a one-time code (see link_driver_group). driver_bot_id
    is auto-assigned as "D<n>" from how many drivers this company already
    has; it's only ever shown as a friendly label (bot.py and the dashboard
    both fall back to it when full_name is blank), never used to look
    anything up, so a collision from a since-deleted driver is harmless."""
    with get_session() as session:
        existing = session.query(models.Driver).filter(models.Driver.company_id == company_id).count()
        row = models.Driver(
            company_id=company_id,
            driver_bot_id=f"D{existing + 1:03d}",
            full_name=full_name,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {
            "id": row.id,
            "driver_bot_id": row.driver_bot_id,
            "full_name": row.full_name,
            "telegram_group_id": row.telegram_group_id,
            "telegram_group_title": row.telegram_group_title,
            "subscription_active": row.subscription_active,
        }


def get_drivers_by_company(company_id: int) -> list[dict]:
    """Returns every driver under a company, with a couple of useful
    aggregates, for the Mini App's driver list screen. Aggregates come from
    3 grouped queries total (not 3 queries per driver) - dispatcher.username
    is a no-op extra query too, since Driver.dispatcher is eager-loaded."""
    from sqlalchemy import func

    with get_session() as session:
        drivers = session.query(models.Driver).filter(models.Driver.company_id == company_id).all()
        if not drivers:
            return []

        driver_ids = [d.id for d in drivers]
        week_start = current_week_start_utc()

        load_counts = dict(
            session.query(models.Load.driver_id, func.count(models.Load.id))
            .filter(models.Load.driver_id.in_(driver_ids))
            .group_by(models.Load.driver_id)
            .all()
        )
        weekly_gross_by_driver = dict(
            session.query(models.Load.driver_id, func.sum(models.Load.rate_amount))
            .filter(
                models.Load.driver_id.in_(driver_ids),
                models.Load.created_at >= week_start,
                models.Load.status.in_(GROSS_ELIGIBLE_STATUSES),
            )
            .group_by(models.Load.driver_id)
            .all()
        )
        weekly_loads_by_driver = dict(
            session.query(models.Load.driver_id, func.count(models.Load.id))
            .filter(
                models.Load.driver_id.in_(driver_ids),
                models.Load.created_at >= week_start,
            )
            .group_by(models.Load.driver_id)
            .all()
        )

        result = []
        for d in drivers:
            result.append(
                {
                    "id": d.id,
                    "driver_bot_id": d.driver_bot_id,
                    "full_name": d.full_name or d.driver_bot_id,
                    "telegram_group_id": d.telegram_group_id,
                    "telegram_group_title": d.telegram_group_title,
                    "dispatcher_username": d.dispatcher.username if d.dispatcher else None,
                    "subscription_active": d.subscription_active,
                    "samsara_vehicle_id": d.truck.samsara_vehicle_id if d.truck else None,
                    "truck": (
                        {"id": d.truck.id, "unit_number": d.truck.unit_number} if d.truck else None
                    ),
                    "trailer": (
                        {"id": d.truck.trailer.id, "unit_number": d.truck.trailer.unit_number}
                        if d.truck and d.truck.trailer else None
                    ),
                    "load_count": load_counts.get(d.id, 0),
                    "weekly_gross": float(weekly_gross_by_driver.get(d.id) or 0.0),
                    "weekly_loads": weekly_loads_by_driver.get(d.id, 0),
                }
            )
        return result


def toggle_driver_subscription(driver_id: int, active: bool, company_id: int) -> None:
    with get_session() as session:
        row = session.get(models.Driver, driver_id)
        if row and row.company_id == company_id:
            row.subscription_active = active
            session.commit()


def get_driver_details(driver_id: int, company_id: int) -> dict | None:
    """Returns detailed information about a specific driver including load history."""
    from sqlalchemy import func, desc

    with get_session() as session:
        driver = session.get(models.Driver, driver_id)
        if not driver or driver.company_id != company_id:
            return None

        week_start = current_week_start_utc()

        # Get all loads for this driver
        loads = session.query(models.Load).filter(
            models.Load.driver_id == driver_id
        ).order_by(desc(models.Load.created_at)).limit(50).all()

        # Weekly stats
        weekly_gross = session.query(func.sum(models.Load.rate_amount)).filter(
            models.Load.driver_id == driver_id,
            models.Load.created_at >= week_start,
            models.Load.status.in_(GROSS_ELIGIBLE_STATUSES)
        ).scalar() or 0.0

        weekly_loads = session.query(models.Load).filter(
            models.Load.driver_id == driver_id,
            models.Load.created_at >= week_start
        ).count()

        # All-time stats
        total_gross = session.query(func.sum(models.Load.rate_amount)).filter(
            models.Load.driver_id == driver_id,
            models.Load.status.in_(GROSS_ELIGIBLE_STATUSES)
        ).scalar() or 0.0

        # A real count, not len(loads) - the load-history list above is
        # capped at 50, so a driver with more than that would otherwise be
        # shown a "total loads" figure stuck at 50 forever.
        total_loads = session.query(models.Load).filter(models.Load.driver_id == driver_id).count()

        load_list = []
        for load in loads:
            # Format dates in dd-MM-yyyy HH:mm:ss format
            created_at_str = None
            if load.created_at:
                created_at_str = load.created_at.strftime('%d-%m-%Y %H:%M:%S')
            
            pu_date_str = load.pu_date
            if pu_date_str and isinstance(load.pu_date, str):
                try:
                    # Try to parse and reformat if it's a datetime string
                    from datetime import datetime
                    parsed = datetime.fromisoformat(load.pu_date.replace('Z', '+00:00'))
                    pu_date_str = parsed.strftime('%d-%m-%Y')
                except ValueError:
                    pass  # Keep original if parsing fails
            
            del_date_str = load.del_date
            if del_date_str and isinstance(load.del_date, str):
                try:
                    from datetime import datetime
                    parsed = datetime.fromisoformat(load.del_date.replace('Z', '+00:00'))
                    del_date_str = parsed.strftime('%d-%m-%Y')
                except ValueError:
                    pass
            
            load_list.append({
                "id": load.id,
                "load_id": load.load_id,
                "broker_name": load.broker_name,
                "pu_address": load.pu_address,
                "del_address": load.del_address,
                "pu_date": pu_date_str,
                "del_date": del_date_str,
                "rate_amount": float(load.rate_amount) if load.rate_amount else None,
                "status": load.status,
                "created_at": created_at_str,
            })
        
        return {
            "id": driver.id,
            "driver_bot_id": driver.driver_bot_id,
            "full_name": driver.full_name or driver.driver_bot_id,
            "telegram_group_id": driver.telegram_group_id,
            "telegram_group_title": driver.telegram_group_title,
            "telegram_username": driver.telegram_username,
            "dispatcher_username": driver.dispatcher.username if driver.dispatcher else None,
            "subscription_active": driver.subscription_active,
            "samsara_vehicle_id": driver.truck.samsara_vehicle_id if driver.truck else None,
            "truck": (
                {"id": driver.truck.id, "unit_number": driver.truck.unit_number}
                if driver.truck else None
            ),
            "trailer": (
                {"id": driver.truck.trailer.id, "unit_number": driver.truck.trailer.unit_number}
                if driver.truck and driver.truck.trailer else None
            ),
            "weekly_gross": float(weekly_gross),
            "weekly_loads": weekly_loads,
            "total_gross": float(total_gross),
            "total_loads": total_loads,
            "loads": load_list,
        }


def get_company_billing_info(company_id: int) -> dict | None:
    """Everything services/stripe_service.py and the /api/billing route need:
    the company's current plan/subscription state plus how many active
    drivers count against its PLAN_LIMITS cap."""
    with get_session() as session:
        row = session.get(models.Company, company_id)
        if not row:
            return None
        active_drivers = (
            session.query(models.Driver)
            .filter(models.Driver.company_id == company_id, models.Driver.subscription_active == True)
            .count()
        )
        return {
            "id": row.id,
            "email": row.email,
            "mc_number": row.mc_number,
            "company_name": row.company_name,
            "subscription_tier": row.subscription_tier,
            "subscription_status": row.subscription_status,
            "stripe_customer_id": row.stripe_customer_id,
            "stripe_subscription_id": row.stripe_subscription_id,
            "trial_ends_at": row.trial_ends_at,
            "billing_interval": row.billing_interval,
            "active_drivers": active_drivers,
        }


def set_company_stripe_customer(company_id: int, stripe_customer_id: str) -> None:
    with get_session() as session:
        row = session.get(models.Company, company_id)
        if row:
            row.stripe_customer_id = stripe_customer_id
            session.commit()


_UNSET = object()


def update_company_subscription(
    company_id: int,
    *,
    tier=_UNSET,
    status=_UNSET,
    stripe_subscription_id=_UNSET,
    billing_interval=_UNSET,
    trial_ends_at=_UNSET,
) -> None:
    """Updates whichever subscription fields are passed, leaving the rest
    untouched - called from the Stripe webhook handler as a subscription
    moves through its lifecycle (trialing -> active -> canceled, etc).
    Uses a sentinel default rather than None so callers can explicitly
    clear trial_ends_at back to None (e.g. once a trial converts)."""
    with get_session() as session:
        row = session.get(models.Company, company_id)
        if not row:
            return
        if tier is not _UNSET:
            row.subscription_tier = tier
        if status is not _UNSET:
            row.subscription_status = status
        if stripe_subscription_id is not _UNSET:
            row.stripe_subscription_id = stripe_subscription_id
        if billing_interval is not _UNSET:
            row.billing_interval = billing_interval
        if trial_ends_at is not _UNSET:
            row.trial_ends_at = trial_ends_at
        session.commit()


def find_trial_redemption(
    email: str | None = None,
    mc_number: str | None = None,
    card_fingerprint: str | None = None,
    gmail_address: str | None = None,
) -> dict | None:
    """Returns an existing trial redemption matching ANY of the given
    signals (on any company), or None if none matches - None means
    "eligible for a free trial"."""
    from sqlalchemy import or_

    conditions = []
    if email:
        conditions.append(models.TrialRedemption.email == email)
    if mc_number:
        conditions.append(models.TrialRedemption.mc_number == mc_number)
    if card_fingerprint:
        conditions.append(models.TrialRedemption.card_fingerprint == card_fingerprint)
    if gmail_address:
        conditions.append(models.TrialRedemption.gmail_address == gmail_address)
    if not conditions:
        return None

    with get_session() as session:
        row = session.query(models.TrialRedemption).filter(or_(*conditions)).first()
        if not row:
            return None
        return {
            "id": row.id,
            "company_id": row.company_id,
            "email": row.email,
            "mc_number": row.mc_number,
            "card_fingerprint": row.card_fingerprint,
            "gmail_address": row.gmail_address,
        }


def upsert_trial_redemption(
    company_id: int,
    email: str | None = None,
    mc_number: str | None = None,
    card_fingerprint: str | None = None,
    gmail_address: str | None = None,
) -> None:
    """One row per company - inserts on that company's first trial, updates
    in place on Stripe webhook retries or once a later signal (e.g. a
    connected Gmail address) becomes known."""
    with get_session() as session:
        row = (
            session.query(models.TrialRedemption)
            .filter(models.TrialRedemption.company_id == company_id)
            .first()
        )
        if not row:
            row = models.TrialRedemption(company_id=company_id)
            session.add(row)
        if email:
            row.email = email
        if mc_number:
            row.mc_number = mc_number
        if card_fingerprint:
            row.card_fingerprint = card_fingerprint
        if gmail_address:
            row.gmail_address = gmail_address
        session.commit()


def get_dispatchers_by_company(company_id: int) -> list[dict]:
    """Returns every dispatcher login under a company, for the Settings page."""
    with get_session() as session:
        rows = session.query(models.Dispatcher).filter(models.Dispatcher.company_id == company_id).all()
        avatars = get_account_avatars([("dispatcher", r.id) for r in rows])
        return [
            {
                "id": r.id,
                "username": r.username,
                "role": r.role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "avatar": avatars.get(("dispatcher", r.id)),
            }
            for r in rows
        ]


def get_team_roster(company_id: int) -> list[dict]:
    """The owner plus every dispatcher under a company, each with their
    display name and avatar - lets teammates see each other regardless of
    which one of them is logged in (unlike get_dispatchers_by_company,
    which is owner-only CRUD data)."""
    company = get_company(company_id)
    if company is None:
        return []
    with get_session() as session:
        dispatchers = session.query(models.Dispatcher).filter(models.Dispatcher.company_id == company_id).all()

    pairs = [("owner", company_id)] + [("dispatcher", d.id) for d in dispatchers]
    avatars = get_account_avatars(pairs)
    roster = [{"role": "owner", "name": company.company_name, "avatar": avatars.get(("owner", company_id))}]
    roster += [
        {"role": "dispatcher", "name": d.username, "avatar": avatars.get(("dispatcher", d.id))}
        for d in dispatchers
    ]
    return roster


# ------------------------------------------------------------------
# Two-factor authentication
# ------------------------------------------------------------------
from datetime import datetime, timezone


def _get_or_create_2fa_row(session, account_type: str, account_id: int):
    row = (
        session.query(models.TwoFactorSecret)
        .filter(
            models.TwoFactorSecret.account_type == account_type,
            models.TwoFactorSecret.account_id == account_id,
        )
        .first()
    )
    if row is None:
        row = models.TwoFactorSecret(account_type=account_type, account_id=account_id)
        session.add(row)
        session.flush()
    return row


def get_2fa_status(account_type: str, account_id: int) -> dict:
    """Returns which 2FA methods are enabled for this account, for the
    Settings > Security page and to decide whether login needs a second step."""
    with get_session() as session:
        row = (
            session.query(models.TwoFactorSecret)
            .filter(
                models.TwoFactorSecret.account_type == account_type,
                models.TwoFactorSecret.account_id == account_id,
            )
            .first()
        )
        webauthn_count = (
            session.query(models.WebAuthnCredential)
            .filter(
                models.WebAuthnCredential.account_type == account_type,
                models.WebAuthnCredential.account_id == account_id,
            )
            .count()
        )
        recovery_count = (
            session.query(models.RecoveryCode)
            .filter(
                models.RecoveryCode.account_type == account_type,
                models.RecoveryCode.account_id == account_id,
                models.RecoveryCode.used_at.is_(None),
            )
            .count()
        )

        totp_enabled = bool(row and row.totp_enabled)
        email_enabled = bool(row and row.email_otp_enabled)
        sms_enabled = bool(row and row.sms_otp_enabled)
        telegram_enabled = bool(row and row.telegram_otp_enabled)
        webauthn_enabled = webauthn_count > 0

        return {
            "totp_enabled": totp_enabled,
            "email_otp_enabled": email_enabled,
            "contact_email": decrypt_value(row.contact_email) if row and row.contact_email else None,
            "sms_otp_enabled": sms_enabled,
            "phone_number": decrypt_value(row.phone_number) if row and row.phone_number else None,
            "telegram_otp_enabled": telegram_enabled,
            "telegram_linked": bool(row and row.telegram_user_id),
            "webauthn_count": webauthn_count,
            "recovery_codes_remaining": recovery_count,
            "any_enabled": any([totp_enabled, email_enabled, sms_enabled, telegram_enabled, webauthn_enabled]),
        }


def is_2fa_enabled(account_type: str, account_id: int) -> bool:
    return get_2fa_status(account_type, account_id)["any_enabled"]


def get_2fa_delivery_info(account_type: str, account_id: int) -> dict | None:
    """Returns the raw row (contact email/phone/telegram id + encrypted TOTP
    secret) needed to actually deliver/verify a code - not for display."""
    with get_session() as session:
        row = (
            session.query(models.TwoFactorSecret)
            .filter(
                models.TwoFactorSecret.account_type == account_type,
                models.TwoFactorSecret.account_id == account_id,
            )
            .first()
        )
        if not row:
            return None
        return {
            "totp_secret_encrypted": row.totp_secret_encrypted,
            "totp_enabled": row.totp_enabled,
            "totp_last_used_step": row.totp_last_used_step,
            "contact_email": decrypt_value(row.contact_email) if row.contact_email else None,
            "email_otp_enabled": row.email_otp_enabled,
            "phone_number": decrypt_value(row.phone_number) if row.phone_number else None,
            "sms_otp_enabled": row.sms_otp_enabled,
            "telegram_user_id": row.telegram_user_id,
            "telegram_otp_enabled": row.telegram_otp_enabled,
        }


def save_totp_secret(account_type: str, account_id: int, encrypted_secret: str) -> None:
    with get_session() as session:
        row = _get_or_create_2fa_row(session, account_type, account_id)
        row.totp_secret_encrypted = encrypted_secret
        session.commit()


def set_totp_enabled(account_type: str, account_id: int, enabled: bool) -> None:
    with get_session() as session:
        row = _get_or_create_2fa_row(session, account_type, account_id)
        row.totp_enabled = enabled
        session.commit()


def update_totp_last_used_step(account_type: str, account_id: int, step: int) -> None:
    """Records the time-step a TOTP code was just successfully verified
    against, so verify_totp_code can reject that same code (or an earlier
    one) if it's replayed within its remaining validity window."""
    with get_session() as session:
        row = _get_or_create_2fa_row(session, account_type, account_id)
        row.totp_last_used_step = step
        session.commit()


def set_email_otp(account_type: str, account_id: int, contact_email: str | None, enabled: bool) -> None:
    with get_session() as session:
        row = _get_or_create_2fa_row(session, account_type, account_id)
        if contact_email is not None:
            row.contact_email = encrypt_value(contact_email)
        row.email_otp_enabled = enabled
        session.commit()


def set_sms_otp(account_type: str, account_id: int, phone_number: str | None, enabled: bool) -> None:
    with get_session() as session:
        row = _get_or_create_2fa_row(session, account_type, account_id)
        if phone_number is not None:
            row.phone_number = encrypt_value(phone_number)
        row.sms_otp_enabled = enabled
        session.commit()


def set_telegram_otp(account_type: str, account_id: int, telegram_user_id: int | None, enabled: bool) -> None:
    with get_session() as session:
        row = _get_or_create_2fa_row(session, account_type, account_id)
        if telegram_user_id is not None:
            row.telegram_user_id = telegram_user_id
        row.telegram_otp_enabled = enabled
        session.commit()


# ---- Pending OTP codes (email/SMS/Telegram delivery) ----
def create_pending_otp(account_type: str, account_id: int, channel: str, purpose: str, code_hash: str, expires_at) -> None:
    with get_session() as session:
        session.add(
            models.PendingOtp(
                account_type=account_type,
                account_id=account_id,
                channel=channel,
                purpose=purpose,
                code_hash=code_hash,
                expires_at=expires_at,
            )
        )
        session.commit()


def consume_pending_otp(account_type: str, account_id: int, channel: str, purpose: str, code_hash: str) -> bool:
    """Finds a matching, unexpired, unused OTP and marks it consumed. Returns
    True if a valid match was found (i.e. the code was correct)."""
    with get_session() as session:
        row = (
            session.query(models.PendingOtp)
            .filter(
                models.PendingOtp.account_type == account_type,
                models.PendingOtp.account_id == account_id,
                models.PendingOtp.channel == channel,
                models.PendingOtp.purpose == purpose,
                models.PendingOtp.code_hash == code_hash,
                models.PendingOtp.consumed_at.is_(None),
                models.PendingOtp.expires_at > datetime.now(timezone.utc),
            )
            .order_by(models.PendingOtp.created_at.desc())
            .first()
        )
        if not row:
            return False
        row.consumed_at = datetime.now(timezone.utc)
        session.commit()
        return True


# ---- Recovery codes ----
def save_recovery_codes(account_type: str, account_id: int, code_hashes: list[str]) -> None:
    """Replaces any existing recovery codes with a fresh batch."""
    with get_session() as session:
        session.query(models.RecoveryCode).filter(
            models.RecoveryCode.account_type == account_type,
            models.RecoveryCode.account_id == account_id,
        ).delete()
        for code_hash in code_hashes:
            session.add(models.RecoveryCode(account_type=account_type, account_id=account_id, code_hash=code_hash))
        session.commit()


def consume_recovery_code(account_type: str, account_id: int, code_hash: str) -> bool:
    with get_session() as session:
        row = (
            session.query(models.RecoveryCode)
            .filter(
                models.RecoveryCode.account_type == account_type,
                models.RecoveryCode.account_id == account_id,
                models.RecoveryCode.code_hash == code_hash,
                models.RecoveryCode.used_at.is_(None),
            )
            .first()
        )
        if not row:
            return False
        row.used_at = datetime.now(timezone.utc)
        session.commit()
        return True


# ---- WebAuthn credentials ----
def add_webauthn_credential(account_type: str, account_id: int, credential_id: str, public_key: str, sign_count: int, label: str | None) -> None:
    with get_session() as session:
        session.add(
            models.WebAuthnCredential(
                account_type=account_type,
                account_id=account_id,
                credential_id=credential_id,
                public_key=public_key,
                sign_count=sign_count,
                label=label,
            )
        )
        session.commit()


def list_webauthn_credentials(account_type: str, account_id: int) -> list[dict]:
    with get_session() as session:
        rows = (
            session.query(models.WebAuthnCredential)
            .filter(
                models.WebAuthnCredential.account_type == account_type,
                models.WebAuthnCredential.account_id == account_id,
            )
            .all()
        )
        return [
            {
                "id": r.id,
                "credential_id": r.credential_id,
                "public_key": r.public_key,
                "sign_count": r.sign_count,
                "label": r.label,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def get_webauthn_credential_by_id(credential_id: str) -> dict | None:
    with get_session() as session:
        row = session.query(models.WebAuthnCredential).filter(
            models.WebAuthnCredential.credential_id == credential_id
        ).first()
        if not row:
            return None
        return {
            "id": row.id,
            "account_type": row.account_type,
            "account_id": row.account_id,
            "credential_id": row.credential_id,
            "public_key": row.public_key,
            "sign_count": row.sign_count,
        }


def update_webauthn_sign_count(credential_id: str, new_sign_count: int) -> None:
    with get_session() as session:
        row = session.query(models.WebAuthnCredential).filter(
            models.WebAuthnCredential.credential_id == credential_id
        ).first()
        if row:
            row.sign_count = new_sign_count
            session.commit()


def delete_webauthn_credential(account_type: str, account_id: int, credential_pk: int) -> bool:
    """Returns True if a credential was actually deleted, False if credential_pk
    didn't exist or belonged to a different account."""
    with get_session() as session:
        deleted = session.query(models.WebAuthnCredential).filter(
            models.WebAuthnCredential.id == credential_pk,
            models.WebAuthnCredential.account_type == account_type,
            models.WebAuthnCredential.account_id == account_id,
        ).delete()
        session.commit()
        return deleted > 0


# ---- Telegram account-linking tokens ----
def create_telegram_link_token(account_type: str, account_id: int, code: str, expires_at) -> None:
    with get_session() as session:
        session.add(
            models.TelegramLinkToken(
                account_type=account_type, account_id=account_id, code=code, expires_at=expires_at
            )
        )
        session.commit()


def consume_telegram_link_token(code: str) -> dict | None:
    """Looks up an unexpired, unused link code and marks it consumed.
    Returns {account_type, account_id} on success, None if invalid/expired."""
    with get_session() as session:
        row = (
            session.query(models.TelegramLinkToken)
            .filter(
                models.TelegramLinkToken.code == code,
                models.TelegramLinkToken.consumed_at.is_(None),
                models.TelegramLinkToken.expires_at > datetime.now(timezone.utc),
            )
            .first()
        )
        if not row:
            return None
        row.consumed_at = datetime.now(timezone.utc)
        session.commit()
        return {"account_type": row.account_type, "account_id": row.account_id}


# ---- WebAuthn challenges - see models.WebauthnChallenge's docstring for why
# these exist (a client-echoed challenge alone isn't a valid anti-replay
# control) ----
WEBAUTHN_CHALLENGE_TTL_SECONDS = 5 * 60  # plenty of time to complete the browser/authenticator prompt


def create_webauthn_challenge(account_type: str, account_id: int, purpose: str, challenge: str) -> None:
    with get_session() as session:
        session.add(
            models.WebauthnChallenge(
                account_type=account_type,
                account_id=account_id,
                purpose=purpose,
                challenge=challenge,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=WEBAUTHN_CHALLENGE_TTL_SECONDS),
            )
        )
        session.commit()


def consume_webauthn_challenge(account_type: str, account_id: int, purpose: str) -> str | None:
    """Looks up the most recent unexpired, unused challenge issued for this
    account/purpose and marks it consumed. Returns the challenge to verify
    against, or None if there isn't a valid one - callers must treat that
    as a hard failure (a fresh options call is required), never fall back
    to trusting a client-supplied challenge instead."""
    with get_session() as session:
        row = (
            session.query(models.WebauthnChallenge)
            .filter(
                models.WebauthnChallenge.account_type == account_type,
                models.WebauthnChallenge.account_id == account_id,
                models.WebauthnChallenge.purpose == purpose,
                models.WebauthnChallenge.consumed_at.is_(None),
                models.WebauthnChallenge.expires_at > datetime.now(timezone.utc),
            )
            .order_by(models.WebauthnChallenge.created_at.desc())
            .first()
        )
        if not row:
            return None
        row.consumed_at = datetime.now(timezone.utc)
        session.commit()
        return row.challenge


PASSWORD_RESET_TTL_SECONDS = 60 * 60  # 1 hour - long enough to find the email, short enough to limit exposure


def create_password_reset_token(company_id: int, token: str) -> None:
    with get_session() as session:
        session.add(
            models.PasswordResetToken(
                account_type="owner",
                account_id=company_id,
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=PASSWORD_RESET_TTL_SECONDS),
            )
        )
        session.commit()


def consume_password_reset_token(token: str) -> int | None:
    """Looks up an unexpired, unused reset token and marks it consumed.
    Returns the company_id to reset the password for, or None if the token
    is invalid/expired/already used - callers must treat that as a hard
    failure (request a new link), never fall back to any other check."""
    with get_session() as session:
        row = (
            session.query(models.PasswordResetToken)
            .filter(
                models.PasswordResetToken.token == token,
                models.PasswordResetToken.consumed_at.is_(None),
                models.PasswordResetToken.expires_at > datetime.now(timezone.utc),
            )
            .first()
        )
        if not row:
            return None
        row.consumed_at = datetime.now(timezone.utc)
        session.commit()
        return row.account_id


PENDING_REGISTRATION_TTL_SECONDS = 60 * 60  # 1 hour to connect, verify, and fill in company details


def create_pending_registration(token: str, gmail_email: str, gmail_refresh_token: str) -> None:
    with get_session() as session:
        session.add(
            models.PendingRegistration(
                token=token,
                gmail_email=gmail_email,
                gmail_refresh_token_encrypted=encrypt_value(gmail_refresh_token),
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=PENDING_REGISTRATION_TTL_SECONDS),
            )
        )
        session.commit()


def get_pending_registration(token: str) -> dict | None:
    """Non-sensitive view for the frontend to poll/display - never returns
    the refresh token itself. None if the token doesn't exist or expired."""
    with get_session() as session:
        row = (
            session.query(models.PendingRegistration)
            .filter(
                models.PendingRegistration.token == token,
                models.PendingRegistration.expires_at > datetime.now(timezone.utc),
            )
            .first()
        )
        if not row:
            return None
        return {"gmail_email": row.gmail_email, "email_verified": row.email_verified_at is not None}


def set_pending_registration_verification(token: str, code_hash: str, link_token: str) -> bool:
    """Stores a fresh code/link pair to verify against - called each time
    the confirmation email is (re)sent, so only the most recently sent
    code/link actually works. Returns False if the token doesn't exist."""
    with get_session() as session:
        row = session.query(models.PendingRegistration).filter_by(token=token).first()
        if not row:
            return False
        row.verify_code_hash = code_hash
        row.verify_link_token = link_token
        session.commit()
        return True


def verify_pending_registration_code(token: str, code_hash: str) -> bool:
    with get_session() as session:
        row = (
            session.query(models.PendingRegistration)
            .filter(
                models.PendingRegistration.token == token,
                models.PendingRegistration.expires_at > datetime.now(timezone.utc),
            )
            .first()
        )
        if not row or not row.verify_code_hash or row.verify_code_hash != code_hash:
            return False
        row.email_verified_at = datetime.now(timezone.utc)
        session.commit()
        return True


def verify_pending_registration_link(link_token: str) -> str | None:
    """Same idea as verify_pending_registration_code but for the clicked-link
    path - returns the pending registration's own token (so the frontend can
    resume that session) or None if the link is invalid/expired."""
    with get_session() as session:
        row = (
            session.query(models.PendingRegistration)
            .filter(
                models.PendingRegistration.verify_link_token == link_token,
                models.PendingRegistration.expires_at > datetime.now(timezone.utc),
            )
            .first()
        )
        if not row:
            return None
        row.email_verified_at = datetime.now(timezone.utc)
        session.commit()
        return row.token


def consume_pending_registration(token: str) -> dict | None:
    """Called once, at the final /api/auth/register submit - returns the
    verified Gmail address + decrypted refresh token to attach to the new
    Company, and deletes the pending row (one-time use). None if the token
    doesn't exist, expired, or was never actually verified - callers must
    treat that as a hard failure, never fall back to creating the account
    without a connected/verified Gmail."""
    with get_session() as session:
        row = (
            session.query(models.PendingRegistration)
            .filter(
                models.PendingRegistration.token == token,
                models.PendingRegistration.expires_at > datetime.now(timezone.utc),
            )
            .first()
        )
        if not row or not row.email_verified_at:
            return None
        result = {
            "gmail_email": row.gmail_email,
            "gmail_refresh_token": decrypt_value(row.gmail_refresh_token_encrypted),
        }
        session.delete(row)
        session.commit()
        return result


def get_account_status(account_type: str, account_id: int) -> dict | None:
    """None if never set, cleared, or its expires_at has passed - an
    expired status is treated exactly like no status at all, rather than
    needing a background job to clear it. The not-yet-expired check is done
    as a SQL filter (not a Python-side comparison against the fetched row)
    because SQLite's DateTime doesn't round-trip timezone awareness -
    comparing a fetched (naive) value against datetime.now(timezone.utc)
    (aware) raises TypeError, same reason every other expiring-token table
    in this file filters expires_at in the query instead."""
    from sqlalchemy import or_

    with get_session() as session:
        row = (
            session.query(models.AccountStatus)
            .filter(
                models.AccountStatus.account_type == account_type,
                models.AccountStatus.account_id == account_id,
                or_(models.AccountStatus.expires_at.is_(None), models.AccountStatus.expires_at > datetime.now(timezone.utc)),
            )
            .first()
        )
        if not row:
            return None
        return {"emoji": row.emoji, "text": row.text, "expires_at": row.expires_at}


def set_account_status(
    account_type: str, account_id: int, emoji: str | None, text: str, expires_at: datetime | None,
) -> None:
    with get_session() as session:
        row = (
            session.query(models.AccountStatus)
            .filter(
                models.AccountStatus.account_type == account_type,
                models.AccountStatus.account_id == account_id,
            )
            .first()
        )
        if row is None:
            row = models.AccountStatus(account_type=account_type, account_id=account_id)
            session.add(row)
        row.emoji = emoji
        row.text = text
        row.expires_at = expires_at
        session.commit()


def clear_account_status(account_type: str, account_id: int) -> None:
    with get_session() as session:
        session.query(models.AccountStatus).filter(
            models.AccountStatus.account_type == account_type,
            models.AccountStatus.account_id == account_id,
        ).delete()
        session.commit()


# The bot walks a load through these in order: /dispatch creates it as
# "dispatched", /loadpics marks it "loaded", /bol marks it "bol_ok", /pod
# marks it "pod_sent" and the load is done. Anything before pod_sent is
# still live work someone may need to chase.
LOAD_STAGE_ORDER = ("dispatched", "loaded", "bol_ok", "pod_sent")
_OPEN_LOAD_STATUSES = ("dispatched", "loaded", "bol_ok")


def get_fleet_status(company_id: int) -> list[dict]:
    """One row per driver who currently has an open load, for the dashboard's
    fleet view. Answers "what is every truck doing, and which ones need me"
    without opening each driver in turn.

    `attention` flags the rows worth looking at first: detention is running
    (money is accruing and the broker needs chasing), or the load is past its
    delivery date and still not delivered."""
    from sqlalchemy import func

    with get_session() as session:
        drivers = (
            session.query(models.Driver)
            .filter(models.Driver.company_id == company_id)
            .all()
        )
        if not drivers:
            return []

        by_id = {d.id: d for d in drivers}
        # Newest-first, so the first open load seen per driver is their
        # current one. One query for the whole fleet, not one per driver.
        open_loads = (
            session.query(models.Load)
            .filter(
                models.Load.driver_id.in_(list(by_id)),
                models.Load.status.in_(_OPEN_LOAD_STATUSES),
            )
            .order_by(models.Load.created_at.desc())
            .all()
        )

        current: dict[int, models.Load] = {}
        for load in open_loads:
            current.setdefault(load.driver_id, load)

        rows = []
        for driver_id, load in current.items():
            driver = by_id[driver_id]
            reasons = []
            if load.detention_requested_at:
                reasons.append("detention")
            if _is_past_due(load):
                reasons.append("overdue")

            rows.append({
                "driver_id": driver.id,
                "driver_name": driver.full_name or driver.driver_bot_id,
                "driver_bot_id": driver.driver_bot_id,
                "load_id": load.load_id,
                "status": load.status,
                "broker_name": load.broker_name,
                "pickup": _first_line(load.pu_address),
                "delivery": _first_line(load.del_address),
                "del_date": load.del_date,
                "rate_amount": float(load.rate_amount) if load.rate_amount else None,
                "detention_since": load.detention_requested_at.isoformat()
                if load.detention_requested_at else None,
                "attention": reasons,
            })

        # Rows needing attention first, then earliest stage first - a load
        # still sitting at "dispatched" is the one most likely to need a
        # nudge, and a finished-but-not-POD'd one the least.
        rows.sort(key=lambda r: (not r["attention"], LOAD_STAGE_ORDER.index(r["status"])))
        return rows


def _first_line(address: str | None) -> str | None:
    """RC addresses are stored as a multi-line block (company, street,
    city/state/zip); a fleet row only has space for the first line."""
    return address.splitlines()[0] if address else None


def _is_past_due(load) -> bool:
    """del_date comes straight off the rate confirmation as free text, in
    whatever format that broker writes - so this parses leniently and simply
    declines to flag anything it can't read, rather than guessing."""
    if not load.del_date:
        return False
    parsed = _parse_loose_date(load.del_date)
    if parsed is None:
        return False
    return parsed.date() < datetime.now(timezone.utc).date()


def _parse_loose_date(value: str) -> datetime | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def get_account_avatar(account_type: str, account_id: int) -> str | None:
    with get_session() as session:
        row = (
            session.query(models.AccountAvatar)
            .filter(
                models.AccountAvatar.account_type == account_type,
                models.AccountAvatar.account_id == account_id,
            )
            .first()
        )
        return row.data_url if row else None


def get_account_avatars(pairs: list[tuple[str, int]]) -> dict[tuple[str, int], str]:
    """Bulk lookup for teammate listings (e.g. the dispatcher list an owner
    sees, or a team roster) - one query per account_type instead of one per
    account. Grouped in Python rather than a tuple-IN query, since that's a
    row-value comparison SQLAlchemy would need to emit per-dialect."""
    if not pairs:
        return {}
    ids_by_type: dict[str, list[int]] = {}
    for account_type, account_id in pairs:
        ids_by_type.setdefault(account_type, []).append(account_id)

    result: dict[tuple[str, int], str] = {}
    with get_session() as session:
        for account_type, ids in ids_by_type.items():
            rows = (
                session.query(models.AccountAvatar)
                .filter(models.AccountAvatar.account_type == account_type, models.AccountAvatar.account_id.in_(ids))
                .all()
            )
            for row in rows:
                result[(row.account_type, row.account_id)] = row.data_url
    return result


def set_account_avatar(account_type: str, account_id: int, data_url: str) -> None:
    with get_session() as session:
        row = (
            session.query(models.AccountAvatar)
            .filter(
                models.AccountAvatar.account_type == account_type,
                models.AccountAvatar.account_id == account_id,
            )
            .first()
        )
        if row is None:
            row = models.AccountAvatar(account_type=account_type, account_id=account_id)
            session.add(row)
        row.data_url = data_url
        session.commit()


def clear_account_avatar(account_type: str, account_id: int) -> None:
    with get_session() as session:
        session.query(models.AccountAvatar).filter(
            models.AccountAvatar.account_type == account_type,
            models.AccountAvatar.account_id == account_id,
        ).delete()
        session.commit()


# ------------------------------------------------------------------
# Offline truck game - sessions, score validation, leaderboard
# ------------------------------------------------------------------
# A ticket is good for this long. Long enough to cover a stretch offline,
# short enough that a hoard of them isn't a way to bank scores indefinitely.
GAME_SESSION_TTL = timedelta(days=7)
# The route is 3600px and the rig cruises at roughly 90px/s, so nothing
# honest finishes anywhere near this fast. Purely a floor against a script
# posting instant runs.
MIN_RUN_MS = 8_000
MAX_RUN_MS = 60 * 60 * 1000


def issue_game_sessions(account_type: str, account_id: int, count: int) -> list[dict]:
    """Mints single-use tickets, each pinned to a server-chosen seed.

    The client never picks its own seed - that is the whole point. Handing
    out a batch is what lets the game be played with no connection."""
    import secrets

    from services.game_route import generate_route

    issued = []
    with get_session() as session:
        for _ in range(count):
            seed = secrets.randbelow(2**31)
            route = generate_route(seed)
            token = secrets.token_urlsafe(32)
            session.add(models.GameSession(
                token=token,
                account_type=account_type,
                account_id=account_id,
                seed=seed,
                max_payout=route.max_payout,
            ))
            issued.append({"token": token, "seed": seed, "max_payout": route.max_payout})
        session.commit()
    return issued


def count_unconsumed_sessions(account_type: str, account_id: int) -> int:
    with get_session() as session:
        return (
            session.query(models.GameSession)
            .filter(
                models.GameSession.account_type == account_type,
                models.GameSession.account_id == account_id,
                models.GameSession.consumed_at.is_(None),
                models.GameSession.issued_at > datetime.now(timezone.utc) - GAME_SESSION_TTL,
            )
            .count()
        )


class GameScoreRejected(Exception):
    """A submission that failed validation. The message is safe to show."""


def record_game_score(
    account_type: str,
    account_id: int,
    display_name: str,
    token: str,
    payout: int,
    delivered: int,
    lost: int,
    duration_ms: int,
) -> dict:
    """Validates a submitted run and records it, or raises GameScoreRejected.

    Every check here exists because the client is not trusted: it runs the
    physics, so it could claim anything. What the server can prove is that the
    ticket was real, unused, and issued to this account, and that the claimed
    payout is within what the route it named could possibly pay.

    This does NOT re-simulate the run - see the note in
    miniapp/api.py's submit endpoint about what that would take and what this
    does and doesn't stop."""
    if payout < 0 or delivered < 0 or lost < 0:
        raise GameScoreRejected("Score values must not be negative.")
    if not MIN_RUN_MS <= duration_ms <= MAX_RUN_MS:
        raise GameScoreRejected("That run time isn't possible.")

    with get_session() as session:
        ticket = (
            session.query(models.GameSession)
            .filter(models.GameSession.token == token)
            .first()
        )
        if ticket is None:
            raise GameScoreRejected("Unknown game session.")
        # Tied to the account it was issued to, so a token can't be handed
        # around to post scores under someone else's name.
        if ticket.account_type != account_type or ticket.account_id != account_id:
            raise GameScoreRejected("That session belongs to another account.")
        if ticket.consumed_at is not None:
            raise GameScoreRejected("That run has already been submitted.")
        if ticket.issued_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - GAME_SESSION_TTL:
            raise GameScoreRejected("That session has expired.")
        if payout > ticket.max_payout:
            raise GameScoreRejected("Score is higher than that route can pay.")

        ticket.consumed_at = datetime.now(timezone.utc)
        score = models.GameScore(
            account_type=account_type,
            account_id=account_id,
            display_name=display_name[:120],
            payout=payout,
            delivered=delivered,
            lost=lost,
            seed=ticket.seed,
            duration_ms=duration_ms,
        )
        session.add(score)
        session.commit()
        session.refresh(score)
        return {
            "id": score.id,
            "payout": score.payout,
            "recorded_at": score.recorded_at.isoformat(),
        }


def get_game_leaderboard(period: str, limit: int = 20) -> list[dict]:
    """Best single run per account for the current week or month.

    Ranked on one run rather than a total, so the board rewards the best haul
    someone managed rather than how many times they played."""
    from sqlalchemy import func

    now = datetime.now(timezone.utc)
    if period == "week":
        # Monday as the week start, matching ISO convention.
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unknown leaderboard period: {period!r}")

    with get_session() as session:
        rows = (
            session.query(
                models.GameScore.account_type,
                models.GameScore.account_id,
                func.max(models.GameScore.payout).label("best"),
            )
            .filter(models.GameScore.recorded_at >= start)
            .group_by(models.GameScore.account_type, models.GameScore.account_id)
            .order_by(func.max(models.GameScore.payout).desc())
            .limit(limit)
            .all()
        )

        board = []
        for rank, (acc_type, acc_id, best) in enumerate(rows, start=1):
            # The name is read off the run itself, so a display name that has
            # since changed still shows as it was when the score was set.
            detail = (
                session.query(models.GameScore)
                .filter(
                    models.GameScore.account_type == acc_type,
                    models.GameScore.account_id == acc_id,
                    models.GameScore.payout == best,
                    models.GameScore.recorded_at >= start,
                )
                .order_by(models.GameScore.recorded_at.asc())
                .first()
            )
            board.append({
                "rank": rank,
                "name": detail.display_name if detail else "—",
                "payout": int(best),
                "delivered": detail.delivered if detail else 0,
                "lost": detail.lost if detail else 0,
                "recorded_at": detail.recorded_at.isoformat() if detail else None,
            })
        return board


# ------------------------------------------------------------------
# Truck/driver details read out of a dispatch group's bio
#
# The bot proposes, a person disposes: nothing below writes to Driver or
# Truck until apply_group_profile_proposal is called, and that only happens
# when someone confirms - from the dashboard or from Telegram.
# ------------------------------------------------------------------

def get_driver_identity(driver_id: int, company_id: int) -> dict | None:
    """The driver's own details, with nothing filled in for them.

    get_driver_details falls back to the bot-assigned ID when a driver has
    no name, which is right for display and wrong here: comparing a bio
    against "D001" would report a conflict with a name nobody ever set."""
    with get_session() as session:
        driver = session.get(models.Driver, driver_id)
        if not driver or driver.company_id != company_id:
            return None
        return {
            "id": driver.id,
            "full_name": driver.full_name,
            "phone": driver.phone,
            "email": driver.email,
            "co_driver_name": driver.co_driver_name,
            "co_driver_phone": driver.co_driver_phone,
            "truck_unit_number": driver.truck.unit_number if driver.truck else None,
        }


def _proposal_dict(row: models.GroupProfileProposal) -> dict:
    return {
        "id": row.id,
        "driver_id": row.driver_id,
        "driver_name": row.driver.full_name if row.driver else None,
        "telegram_group_id": row.telegram_group_id,
        "source_title": row.source_title,
        "source_description": row.source_description,
        "fields": row.fields or {},
        "unclear": row.unclear or [],
        "conflicts": row.conflicts or [],
        "status": row.status,
        "resolved_via": row.resolved_via,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def save_group_profile_proposal(
    company_id: int,
    driver_id: int,
    telegram_group_id: int,
    *,
    title: str | None,
    description: str | None,
    fields: dict,
    unclear: list | None = None,
    conflicts: list | None = None,
) -> dict:
    """Records what the bio said, for someone to confirm.

    A re-read supersedes whatever was pending for the same driver rather
    than queueing behind it - the bio was edited, so the older reading is
    simply out of date and confirming it would write stale details."""
    with get_session() as session:
        session.query(models.GroupProfileProposal).filter(
            models.GroupProfileProposal.driver_id == driver_id,
            models.GroupProfileProposal.status == "pending",
        ).update({"status": "dismissed", "resolved_via": "superseded",
                  "resolved_at": models.now_utc()}, synchronize_session=False)

        row = models.GroupProfileProposal(
            company_id=company_id,
            driver_id=driver_id,
            telegram_group_id=telegram_group_id,
            source_title=title,
            source_description=description,
            fields=fields,
            unclear=unclear or [],
            conflicts=conflicts or [],
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _proposal_dict(row)


def get_pending_proposal_for_group(telegram_group_id: int) -> dict | None:
    with get_session() as session:
        row = (
            session.query(models.GroupProfileProposal)
            .filter(
                models.GroupProfileProposal.telegram_group_id == telegram_group_id,
                models.GroupProfileProposal.status == "pending",
            )
            .order_by(models.GroupProfileProposal.id.desc())
            .first()
        )
        return _proposal_dict(row) if row else None


def list_pending_proposals(company_id: int) -> list[dict]:
    with get_session() as session:
        rows = (
            session.query(models.GroupProfileProposal)
            .filter(
                models.GroupProfileProposal.company_id == company_id,
                models.GroupProfileProposal.status == "pending",
            )
            .order_by(models.GroupProfileProposal.id.desc())
            .all()
        )
        return [_proposal_dict(r) for r in rows]


def apply_group_profile_proposal(
    proposal_id: int, via: str, *, company_id: int | None = None
) -> tuple[bool, str]:
    """Copies a confirmed reading onto the driver and their truck.

    Returns (ok, reason). "already_resolved" is the ordinary case rather
    than an error: the same proposal is confirmable from two places, and
    whoever gets there second should be told it is already done, not shown
    a failure.

    Missing fields are left alone - a bio that names no trailer must not
    blank out the trailer already on file. A truck or trailer number that
    the company does not have yet is created, because the bio naming it is
    the company telling us it exists."""
    with get_session() as session:
        row = session.get(models.GroupProfileProposal, proposal_id)
        if not row or (company_id is not None and row.company_id != company_id):
            return False, "not_found"
        if row.status != "pending":
            return False, "already_resolved"

        driver = session.get(models.Driver, row.driver_id)
        if not driver:
            return False, "driver_gone"

        fields = row.fields or {}

        def value(key: str) -> str | None:
            raw = fields.get(key)
            if raw is None:
                return None
            text = str(raw).strip()
            return text or None

        for column, key in (
            ("full_name", "driver_name"),
            ("phone", "driver_phone"),
            ("email", "driver_email"),
            ("co_driver_name", "co_driver_name"),
            ("co_driver_phone", "co_driver_phone"),
        ):
            found = value(key)
            if found:
                setattr(driver, column, found)

        truck = None
        unit = value("truck_number")
        if unit:
            truck = (
                session.query(models.Truck)
                .filter(models.Truck.company_id == row.company_id, models.Truck.unit_number == unit)
                .first()
            )
            if not truck:
                truck = models.Truck(company_id=row.company_id, unit_number=unit)
                session.add(truck)
                session.flush()
            driver.truck_id = truck.id
        elif driver.truck_id:
            truck = session.get(models.Truck, driver.truck_id)

        if truck:
            vin = value("vin")
            if vin:
                truck.vin = vin

            trailer_unit = value("trailer_number")
            if trailer_unit:
                trailer = (
                    session.query(models.Trailer)
                    .filter(
                        models.Trailer.company_id == row.company_id,
                        models.Trailer.unit_number == trailer_unit,
                    )
                    .first()
                )
                if not trailer:
                    trailer = models.Trailer(company_id=row.company_id, unit_number=trailer_unit)
                    session.add(trailer)
                    session.flush()
                truck.trailer_id = trailer.id

        row.status = "applied"
        row.resolved_via = via
        row.resolved_at = models.now_utc()
        session.commit()
        return True, "ok"


def dismiss_group_profile_proposal(
    proposal_id: int, via: str, *, company_id: int | None = None
) -> tuple[bool, str]:
    with get_session() as session:
        row = session.get(models.GroupProfileProposal, proposal_id)
        if not row or (company_id is not None and row.company_id != company_id):
            return False, "not_found"
        if row.status != "pending":
            return False, "already_resolved"
        row.status = "dismissed"
        row.resolved_via = via
        row.resolved_at = models.now_utc()
        session.commit()
        return True, "ok"
