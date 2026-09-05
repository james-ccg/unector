"""
SQLAlchemy ORM models - the Python mirror of the tables in db/schema.sql.
Each class = one table. Used directly inside repository.py.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, ForeignKey, BigInteger, Boolean, DateTime, Numeric, Text, JSON, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    mc_number: Mapped[str] = mapped_column(String(20), unique=True)
    company_name: Mapped[str] = mapped_column(String(200))
    telegram_group_prefix: Mapped[str] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)  # owner's contact/billing email
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)  # owner's Mini App login

    # Billing - "free" needs no Stripe objects at all. Paid tiers get a Stripe customer
    # (and, once they've subscribed, a Stripe subscription) attached below.
    subscription_tier: Mapped[str] = mapped_column(String(50), default="free")  # free | pro | max_5x | max_20x
    subscription_status: Mapped[str] = mapped_column(String(20), default="none")  # none|trialing|active|past_due|canceled
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # When the "your trial ends soon" email went out. Its only job is to stop
    # a second one going: the reminder job runs on a timer, so without this
    # every pass through the window would send another.
    trial_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    billing_interval: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "month" | "year"

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class CompanyCredential(Base):
    __tablename__ = "company_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    cred_type: Mapped[str] = mapped_column(String(30))         # 'email_oauth', 'samsara_api', ...
    encrypted_value: Mapped[str] = mapped_column(Text)         # encrypted via config.encrypt_value()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Dispatcher(Base):
    __tablename__ = "dispatchers"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    username: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(Text)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="dispatcher")   # 'owner' | 'dispatcher'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Trailer(Base):
    """A trailer, identified by the unit number painted on it. Tracked
    separately from the truck because trailers get dropped, swapped and
    re-hooked constantly - the pairing is current state, not an identity."""
    __tablename__ = "trailers"
    __table_args__ = (UniqueConstraint("company_id", "unit_number", name="uq_trailer_unit_per_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    unit_number: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Truck(Base):
    """A truck, identified by its unit number - the fleet's stable unit.

    Drivers come and go against a given truck, so the truck (not the person)
    is what dispatch actually organises around: "where is 3001" outlives
    whoever is driving it this month. That's why the GPS link lives here
    rather than on Driver, where it used to sit - the telematics device is
    bolted to the vehicle.

    trailer_id is the trailer currently hooked to it, and is expected to
    change often; it is not ownership."""
    __tablename__ = "trucks"
    __table_args__ = (UniqueConstraint("company_id", "unit_number", name="uq_truck_unit_per_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    unit_number: Mapped[str] = mapped_column(String(30))
    samsara_vehicle_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Read off the group bio where dispatchers write it. Recorded for
    # identification only - nothing in the app looks it up.
    vin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trailer_id: Mapped[int | None] = mapped_column(ForeignKey("trailers.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    trailer: Mapped["Trailer"] = relationship(lazy="joined")


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    driver_bot_id: Mapped[str] = mapped_column(String(20))       # bot-assigned ID# (e.g. "D001")
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Contact details. Usually read out of the truck's Telegram group bio
    # (see GroupProfileProposal) and confirmed by a person, or typed in by
    # hand. Nullable throughout: a dispatch group's bio is free text and
    # often carries only some of this.
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Team trucks run two drivers. The second one shares the group and the
    # truck, so they are recorded here rather than as a Driver of their own.
    co_driver_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    co_driver_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    telegram_group_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    telegram_group_title: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Guruh nomi
    telegram_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Which truck this driver is currently on. Nullable: a driver can be
    # between trucks, and a truck can sit without a driver.
    truck_id: Mapped[int | None] = mapped_column(ForeignKey("trucks.id"), nullable=True)
    dispatcher_id: Mapped[int | None] = mapped_column(ForeignKey("dispatchers.id"), nullable=True)
    subscription_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    dispatcher: Mapped["Dispatcher"] = relationship(lazy="joined")
    truck: Mapped["Truck"] = relationship(lazy="joined")


class Load(Base):
    __tablename__ = "loads"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    load_id: Mapped[str] = mapped_column(String(50))             # the broker's load ID
    broker_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    broker_contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    carrier_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    pu_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    pu_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pu_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pu_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    del_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    del_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    del_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    weight: Mapped[str | None] = mapped_column(String(50), nullable=True)
    commodity: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reefer_temp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rate_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    rc_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="dispatched")
    pu_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    pu_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    del_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    del_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    notified_pu_near: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_del_near: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which company-defined LocationAlertRule ids have already fired for this
    # load - list[int], only used for scenarios where the company has custom
    # rules configured (see LocationAlertRule below). Scenarios still on the
    # built-in default keep using notified_pu_near/notified_del_near above.
    alerted_rule_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    detention_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_extracted_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The load card pinned in the driver's group, so the next dispatch can
    # take the old pin down. Null when nothing was pinned - the bot may not
    # have the right in that group, and that is not an error.
    pinned_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class LocationAlertRule(Base):
    """A company's own rule for when to message a driver's group about GPS
    proximity, and what to say. Several rules can stack per scenario (e.g. a
    heads-up at 50 miles out, then again at 5) - each one fires at most once
    per load, independently of the others, as the truck gets closer. A
    company with no rules for a scenario gets the built-in default instead
    (SAMSARA_NEARBY_MILES + a generic message) - see bot.py's
    location_monitor_loop."""
    __tablename__ = "location_alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    scenario: Mapped[str] = mapped_column(String(20))  # "pu_near" | "del_near"
    distance_miles: Mapped[float] = mapped_column(Numeric(6, 1))
    # None = use the built-in default wording. May reference {miles} and
    # {load_id}; see bot.py's _render_alert_message.
    message_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


# ------------------------------------------------------------------
# Two-factor authentication
#
# Both owner logins (Company) and dispatcher logins (Dispatcher) can enroll
# in 2FA, so these tables use a generic (account_type, account_id) pair
# instead of duplicating identical columns onto two different tables.
# account_type is "owner" (account_id = companies.id) or "dispatcher"
# (account_id = dispatchers.id).
# ------------------------------------------------------------------
class TwoFactorSecret(Base):
    """One row per login account. Tracks which 2FA methods are enabled and
    holds the TOTP secret + contact info used to deliver OTP codes."""
    __tablename__ = "two_factor_secrets"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # The last 30s time-step a TOTP code was successfully verified against -
    # without this, a single observed/leaked code stays valid (and
    # replayable) for its whole ~90s window (services/twofactor_service.py's
    # verify_totp_code enforces the "must be newer than this" check).
    totp_last_used_step: Mapped[int | None] = mapped_column(nullable=True)

    email_otp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    sms_otp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)

    telegram_otp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    __table_args__ = (UniqueConstraint("account_type", "account_id", name="uq_2fa_account"),)


class WebAuthnCredential(Base):
    """A registered security key / platform authenticator (Touch ID,
    Windows Hello, YubiKey, etc). An account can have several."""
    __tablename__ = "webauthn_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    credential_id: Mapped[str] = mapped_column(Text, unique=True)  # base64url
    public_key: Mapped[str] = mapped_column(Text)  # base64url COSE key
    sign_count: Mapped[int] = mapped_column(default=0)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)  # "MacBook Touch ID"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class RecoveryCode(Base):
    """One-time-use backup codes, issued as a batch. Each is stored as a
    hash - the plaintext is only ever shown once, at generation time."""
    __tablename__ = "recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    code_hash: Mapped[str] = mapped_column(Text)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class PendingOtp(Base):
    """Short-lived one-time codes for email/SMS/Telegram 2FA - both during
    login and while enrolling a new contact method."""
    __tablename__ = "pending_otps"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    channel: Mapped[str] = mapped_column(String(20))  # "email" | "sms" | "telegram"
    purpose: Mapped[str] = mapped_column(String(20))  # "login" | "enroll"
    code_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class TelegramLinkToken(Base):
    """A short code shown in the web UI ("send /link ABC123 to the bot").
    Once the driver/owner sends that command in Telegram, the bot stamps
    their telegram_user_id onto TwoFactorSecret for this account."""
    __tablename__ = "telegram_link_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    code: Mapped[str] = mapped_column(String(12), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class WebauthnChallenge(Base):
    """Server-side record of a challenge issued for a WebAuthn
    registration/authentication ceremony. WebAuthn's security model
    requires the relying party (this server) to independently remember
    the challenge it issued and verify the signed response against THAT
    exact value, then treat it as spent - trusting whatever challenge the
    client echoes back would let a captured (credential_json, challenge)
    pair be replayed indefinitely, since the challenge is otherwise just
    client-supplied data."""
    __tablename__ = "webauthn_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    purpose: Mapped[str] = mapped_column(String(20))  # "register" | "login"
    challenge: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class PasswordResetToken(Base):
    """A one-time, emailed link for an owner who forgot their password.
    Scoped to owners only for now (account_type is always "owner") -
    dispatcher accounts have no email on file to send a link to; a locked-out
    dispatcher asks their owner to set a new password from Settings instead."""
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    token: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class PendingRegistration(Base):
    """A Gmail account connected during registration, before a Company row
    exists to attach it to. Registration is now Gmail-first: connect Gmail,
    confirm you own that inbox (code or link, emailed from the platform's
    own address), THEN fill in company details - only when that final step
    submits does a real Company get created (see /api/auth/register). If
    the visitor abandons anywhere before then - closes the tab, never
    verifies, never fills the form - this row just expires unused and
    nothing is ever created."""
    __tablename__ = "pending_registrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)

    gmail_email: Mapped[str] = mapped_column(String(200))
    gmail_refresh_token_encrypted: Mapped[str] = mapped_column(Text)

    verify_code_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verify_link_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class AccountStatus(Base):
    """A short "what's happening" status message an owner or dispatcher
    sets for themselves - shown in their own profile menu, similar in
    spirit to GitHub/Slack's status feature. One row per account
    (account_type, account_id is unique together); optional expires_at
    clears it automatically without needing a background job - callers
    just filter out an expired row when reading."""
    __tablename__ = "account_statuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    emoji: Mapped[str | None] = mapped_column(String(8), nullable=True)
    text: Mapped[str] = mapped_column(String(80))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class AccountAvatar(Base):
    """A profile picture an owner or dispatcher sets for themselves, shown
    in their own profile menu and to teammates (owner/dispatchers can see
    each other's avatars). Stored as a data URI (small, client-resized
    image already base64-encoded with its MIME type) rather than a file on
    disk, so no separate static-file serving or storage service is needed
    for what's expected to stay a small image. One row per account
    (account_type, account_id is unique together)."""
    __tablename__ = "account_avatars"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    data_url: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class TrialRedemption(Base):
    """One row per company that has ever started a paid-plan free trial.
    Records every identifying signal we had at the time (login email, MC
    number, the card's Stripe fingerprint, and - once known - the connected
    Gmail address) so a new signup that matches ANY of them on a DIFFERENT
    company can be denied a second free week. See services/stripe_service.py
    for how this is checked and updated."""
    __tablename__ = "trial_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)

    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mc_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    card_fingerprint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gmail_address: Mapped[str | None] = mapped_column(String(200), nullable=True)

    redeemed_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class GameSession(Base):
    """A ticket to play one run, issued by the server before the run starts.

    This is what makes the leaderboard defensible. The server picks the seed,
    so it can regenerate the route (services/game_route.py) and know the most
    that route could possibly pay; a submitted score above that is a lie. The
    token is single-use, so the same good run can't be replayed for points.

    Issued in batches on purpose: the game has to work with no connection, and
    a client that can't reach the server can't ask for a ticket at kickoff.
    Handing out several while online lets someone play offline and submit
    later, without the client ever getting to choose its own seed."""
    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()

    seed: Mapped[int] = mapped_column()
    # Cached so validating a submission doesn't have to regenerate the route,
    # and so a later change to route generation can't retroactively invalidate
    # tickets already in someone's pocket.
    max_payout: Mapped[int] = mapped_column()

    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class GameScore(Base):
    """A completed, server-validated run.

    Only written after the submission passed every check in
    repository.record_game_score, so anything in this table can be shown on
    the leaderboard without further question."""
    __tablename__ = "game_scores"

    id: Mapped[int] = mapped_column(primary_key=True)

    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column()
    # Denormalised so the board can be listed without joining across owners
    # and dispatchers, which live in separate tables.
    display_name: Mapped[str] = mapped_column(String(120))

    payout: Mapped[int] = mapped_column()
    delivered: Mapped[int] = mapped_column()
    lost: Mapped[int] = mapped_column()
    seed: Mapped[int] = mapped_column()
    duration_ms: Mapped[int] = mapped_column()

    # When the server accepted it. Deliberately the basis for which week or
    # month a score belongs to, rather than any timestamp the client sent -
    # a device clock is not evidence.
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class GroupProfileProposal(Base):
    """Truck and driver details read out of a dispatch group's bio, waiting
    for a person to say yes.

    Carriers run one Telegram group per truck and write the unit number,
    trailer, driver and phone numbers into the group's description. The bot
    reads that when the group is linked and proposes it here. Nothing is
    copied onto the Driver or Truck record until someone confirms - from the
    dashboard or from Telegram, whichever comes first - because a bio is
    something a dispatcher typed in a hurry, not a source of record.

    The text it was read from is kept alongside the fields so whoever
    confirms can see where each value came from instead of trusting it."""
    __tablename__ = "group_profile_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True)
    telegram_group_id: Mapped[int] = mapped_column(BigInteger)

    # What was read, kept verbatim.
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # What was made of it: the fields, and the ones the reader was unsure of.
    fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    unclear: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Anything that disagrees with what is already on file, e.g. the bio says
    # truck 3001 but the driver is assigned to 3004. Shown, never auto-fixed.
    conflicts: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # pending -> applied | dismissed. One row per group at a time: a new read
    # supersedes any pending one rather than stacking up.
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    resolved_via: Mapped[str | None] = mapped_column(String(12), nullable=True)  # telegram | dashboard
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    driver: Mapped["Driver"] = relationship(lazy="joined")


# ------------------------------------------------------------------
# Notifications
#
# Recipients are offices, not drivers: an owner or a dispatcher. Drivers
# already hear everything in their own truck's group, and adding a second
# channel for them would only mean saying it twice.
#
# The (account_type, account_id) pair is the same shape TwoFactorSecret
# uses - "owner" points at companies.id, "dispatcher" at dispatchers.id -
# rather than two nullable foreign keys that are never both set.
# ------------------------------------------------------------------
class Notification(Base):
    """One thing worth telling somebody, and whether they have seen it.

    Written for every notification that gets sent, whatever channels it
    went out on. The site is the record: email can bounce and Telegram can
    be muted, and the bell is where anything the other channels dropped can
    still be found."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    account_type: Mapped[str] = mapped_column(String(20))   # owner | dispatcher
    account_id: Mapped[int] = mapped_column(index=True)

    # The catalogue key from services/notification_events.py.
    event: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where in the dashboard this is about, e.g. "/settings#drivers". Kept
    # relative: the host changes and a stored absolute URL would go stale.
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)

    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class NotificationPreference(Base):
    """One switch: this account, this event, this channel, on or off.

    A row per switch rather than a blob per account, so a new event in the
    catalogue needs no migration and no backfill - anything with no row
    falls back to the event's own default, which is what someone who has
    never opened the settings should get.

    Rows are written for mandatory events too, and ignored when they are
    read. Storing the choice and then not honouring it would be worse than
    refusing it, so the API rejects the write instead."""
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "account_type", "account_id", "event", "channel",
            name="uq_notification_preference",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int] = mapped_column(index=True)
    event: Mapped[str] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(20))        # site | telegram | email
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class BillingEvent(Base):
    """One line of a company's billing history, and who caused it.

    A company has one plan, shared by the owner and every dispatcher, and
    any of them can be the one who pays for it. That makes "who paid?" a
    real question with a real answer, and one nothing else records: Stripe
    knows the card and the amount but not which login clicked the button,
    and the company row only ever holds the current state, so an upgrade
    followed by a downgrade leaves no trace that the first one happened.

    The actor is stored as a type, an id AND a label captured at the time.
    The label is the reason: a dispatcher who paid in March and left in June
    should still be the answer to who paid in March, and joining to a row
    that no longer exists would either erase them or break the page.

    stripe_event_id is what makes this safe to write from a webhook. Stripe
    re-sends, and it re-sends on purpose - without a unique key on it, one
    payment would appear in the history two or three times.
    """
    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint("stripe_event_id", name="uq_billing_event_stripe_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    # subscribed | plan_changed | payment | trial_started | canceled | paused
    kind: Mapped[str] = mapped_column(String(30))
    tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billing_interval: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Money in the smallest unit, the way Stripe reports it - storing
    # dollars as a float is how a cent goes missing.
    amount_cents: Mapped[int | None] = mapped_column(nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    actor_type: Mapped[str | None] = mapped_column(String(20), nullable=True)   # owner | dispatcher
    actor_id: Mapped[int | None] = mapped_column(nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    stripe_event_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
