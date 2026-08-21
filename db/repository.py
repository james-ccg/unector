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
            samsara_vehicle_id=row.samsara_vehicle_id,
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
def set_driver_vehicle(driver_pk: int, samsara_vehicle_id: str) -> None:
    """Links a driver to their Samsara vehicle ID (used by /setvehicle)."""
    with get_session() as session:
        row = session.get(models.Driver, driver_pk)
        if row:
            row.samsara_vehicle_id = samsara_vehicle_id
            session.commit()


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
    """Returns every load that (a) isn't finished yet, (b) has a driver linked
    to a Samsara vehicle, and (c) has at least one geocoded destination -
    i.e. everything the location-monitor loop needs to check on each pass."""
    with get_session() as session:
        rows = (
            session.query(models.Load, models.Driver)
            .join(models.Driver, models.Load.driver_id == models.Driver.id)
            .filter(models.Load.status.in_(["dispatched", "loaded", "bol_ok"]))
            .filter(models.Driver.samsara_vehicle_id.isnot(None))
            .filter(models.Driver.telegram_group_id.isnot(None))
            .all()
        )
        result = []
        for load, driver in rows:
            result.append(
                MonitoredLoad(
                    id=load.id,
                    company_id=load.company_id,
                    load_id=load.load_id,
                    status=load.status,
                    telegram_group_id=driver.telegram_group_id,
                    samsara_vehicle_id=driver.samsara_vehicle_id,
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
            id=row.id, mc_number=row.mc_number, company_name=row.company_name, password_hash=row.password_hash
        )


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
                    "samsara_vehicle_id": d.samsara_vehicle_id,
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
                except:
                    pass  # Keep original if parsing fails
            
            del_date_str = load.del_date
            if del_date_str and isinstance(load.del_date, str):
                try:
                    from datetime import datetime
                    parsed = datetime.fromisoformat(load.del_date.replace('Z', '+00:00'))
                    del_date_str = parsed.strftime('%d-%m-%Y')
                except:
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
            "samsara_vehicle_id": driver.samsara_vehicle_id,
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
        return [
            {
                "id": r.id,
                "username": r.username,
                "role": r.role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


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
