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
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)  # owner's Mini App login
    subscription_tier: Mapped[str] = mapped_column(String(50), default="trial")
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


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    driver_bot_id: Mapped[str] = mapped_column(String(20))       # bot-assigned ID# (e.g. "D001")
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    telegram_group_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    telegram_group_title: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Guruh nomi
    telegram_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    samsara_vehicle_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dispatcher_id: Mapped[int | None] = mapped_column(ForeignKey("dispatchers.id"), nullable=True)
    subscription_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    dispatcher: Mapped["Dispatcher"] = relationship(lazy="joined")


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
    raw_extracted_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class DriverEarning(Base):
    __tablename__ = "driver_earnings"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    load_id: Mapped[int] = mapped_column(ForeignKey("loads.id"))
    amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    week_start_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
