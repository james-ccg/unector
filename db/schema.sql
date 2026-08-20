-- ============================================================
-- REFERENCE SCHEMA - for reading, not running.
--
-- The real schema is generated from db/models.py by SQLAlchemy
-- (db/database.py's init_db(), called on every bot.py startup) plus the
-- migrate_db_add_*.py scripts for columns added to already-existing tables.
-- This file is never executed by any code - it exists purely so the shape
-- of the database can be read at a glance without opening models.py. Keep
-- it in sync by hand when models.py changes.
--
-- MULTI-TENANT: one database, many companies. Every company-owned table
-- carries a company_id (directly, or via driver_id/load_id) - that's how
-- companies' data is isolated from each other (enforced in db/repository.py
-- and miniapp/api.py, since SQLite has no row-level security of its own).
-- ============================================================

-- 1. Companies (the MC# owner's login + billing record)
CREATE TABLE companies (
    id                     SERIAL PRIMARY KEY,
    mc_number              VARCHAR(20) UNIQUE NOT NULL,
    company_name           VARCHAR(200) NOT NULL,
    telegram_group_prefix  VARCHAR(20) UNIQUE NOT NULL,   -- e.g. "AXLE"
    email                  VARCHAR(200),                  -- owner's contact/billing email
    password_hash          TEXT,                          -- owner's Mini App login

    -- Billing (Stripe) - "free" needs no Stripe objects at all.
    subscription_tier      VARCHAR(50) DEFAULT 'free',     -- free | pro | max_5x | max_20x
    subscription_status    VARCHAR(20) DEFAULT 'none',     -- none|trialing|active|past_due|canceled
    stripe_customer_id     VARCHAR(100),
    stripe_subscription_id VARCHAR(100),
    trial_ends_at          TIMESTAMP,
    billing_interval       VARCHAR(10),                    -- "month" | "year"

    created_at             TIMESTAMP DEFAULT NOW()
);

-- 2. Each company's own secret credentials (stored ENCRYPTED via config.encrypt_value)
CREATE TABLE company_credentials (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    cred_type       VARCHAR(30) NOT NULL,   -- 'gmail_refresh_token', 'samsara_api_key', ...
    encrypted_value TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 3. Dispatchers (log in via the Mini App with their own username/password)
CREATE TABLE dispatchers (
    id                 SERIAL PRIMARY KEY,
    company_id         INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    username           VARCHAR(100) NOT NULL,
    password_hash      TEXT NOT NULL,
    telegram_user_id   BIGINT,
    telegram_username  VARCHAR(100),
    role               VARCHAR(20) DEFAULT 'dispatcher',  -- 'owner' | 'dispatcher'
    created_at         TIMESTAMP DEFAULT NOW()
);

-- 4. Drivers
CREATE TABLE drivers (
    id                     SERIAL PRIMARY KEY,
    company_id             INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    driver_bot_id          VARCHAR(20) NOT NULL,   -- bot-assigned ID#, used in the group name
    full_name              VARCHAR(150),
    telegram_group_id      BIGINT UNIQUE,          -- this driver's Telegram group
    telegram_group_title   VARCHAR(200),
    telegram_username      VARCHAR(100),
    samsara_vehicle_id     VARCHAR(50),
    dispatcher_id          INTEGER REFERENCES dispatchers(id),
    subscription_active    BOOLEAN DEFAULT TRUE,
    created_at             TIMESTAMP DEFAULT NOW(),
    UNIQUE(company_id, driver_bot_id)
);

-- 5. Loads
CREATE TABLE loads (
    id                     SERIAL PRIMARY KEY,
    company_id             INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    driver_id              INTEGER REFERENCES drivers(id),
    load_id                VARCHAR(50) NOT NULL,   -- the broker's load ID (e.g. "11111")
    broker_name            VARCHAR(150),
    broker_contact_email   VARCHAR(200),
    carrier_name           VARCHAR(150),
    pu_address             TEXT,                   -- full multi-line pickup address
    pu_date                VARCHAR(50),
    pu_time                VARCHAR(50),
    pu_reference           VARCHAR(100),
    del_address            TEXT,                   -- full multi-line delivery address
    del_date               VARCHAR(50),
    del_time               VARCHAR(50),
    weight                 VARCHAR(50),
    commodity              VARCHAR(200),
    reefer_temp            VARCHAR(20),
    rate_amount            NUMERIC(10,2),
    rc_pdf_path            TEXT,
    status                 VARCHAR(30) DEFAULT 'dispatched', -- dispatched -> loaded -> bol_ok -> pod_sent
    pu_lat                 NUMERIC(9,6),
    pu_lng                 NUMERIC(9,6),
    del_lat                NUMERIC(9,6),
    del_lng                NUMERIC(9,6),
    notified_pu_near       BOOLEAN DEFAULT FALSE,  -- default-alert fired? (only used when no LocationAlertRule exists)
    notified_del_near      BOOLEAN DEFAULT FALSE,
    alerted_rule_ids       JSONB,                  -- list[int] of LocationAlertRule ids already fired for this load
    detention_requested_at TIMESTAMP,
    raw_extracted_json     JSONB,                  -- the full JSON Gemini extracted from the RC
    created_at             TIMESTAMP DEFAULT NOW()
);

-- 6. Customizable GPS-proximity alert rules (Settings > Location alerts).
-- A company with no rows here for a given scenario gets the bot's built-in
-- default alert instead - see bot.py's _fire_scenario_alerts.
CREATE TABLE location_alert_rules (
    id                SERIAL PRIMARY KEY,
    company_id        INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    scenario          VARCHAR(20) NOT NULL,   -- "pu_near" | "del_near"
    distance_miles    NUMERIC(6,1) NOT NULL,
    message_template  TEXT,                   -- NULL = built-in default wording. May use {miles}, {load_id}
    enabled           BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT NOW()
);

-- ------------------------------------------------------------------
-- Two-factor authentication. Owner logins (account_type='owner',
-- account_id=companies.id) and dispatcher logins (account_type='dispatcher',
-- account_id=dispatchers.id) share these same tables via that generic pair,
-- instead of duplicating identical columns onto two different tables.
-- ------------------------------------------------------------------

-- 7. One row per login account - which 2FA methods are enabled + contact info
CREATE TABLE two_factor_secrets (
    id                     SERIAL PRIMARY KEY,
    account_type           VARCHAR(20) NOT NULL,
    account_id             INTEGER NOT NULL,

    totp_secret_encrypted  TEXT,
    totp_enabled           BOOLEAN DEFAULT FALSE,

    email_otp_enabled      BOOLEAN DEFAULT FALSE,
    contact_email          VARCHAR(200),

    sms_otp_enabled        BOOLEAN DEFAULT FALSE,
    phone_number           VARCHAR(30),

    telegram_otp_enabled   BOOLEAN DEFAULT FALSE,
    telegram_user_id       BIGINT,

    created_at             TIMESTAMP DEFAULT NOW(),
    updated_at             TIMESTAMP DEFAULT NOW(),
    UNIQUE(account_type, account_id)
);

-- 8. Registered security keys / platform authenticators (Touch ID, Windows
-- Hello, YubiKey, ...) - an account can have several.
CREATE TABLE webauthn_credentials (
    id             SERIAL PRIMARY KEY,
    account_type   VARCHAR(20) NOT NULL,
    account_id     INTEGER NOT NULL,

    credential_id  TEXT UNIQUE NOT NULL,   -- base64url
    public_key     TEXT NOT NULL,          -- base64url COSE key
    sign_count     INTEGER DEFAULT 0,
    label          VARCHAR(100),           -- "MacBook Touch ID"
    created_at     TIMESTAMP DEFAULT NOW()
);

-- 9. One-time-use backup codes, issued as a batch. Stored as a hash only -
-- the plaintext is shown once, at generation time.
CREATE TABLE recovery_codes (
    id            SERIAL PRIMARY KEY,
    account_type  VARCHAR(20) NOT NULL,
    account_id    INTEGER NOT NULL,

    code_hash     TEXT NOT NULL,
    used_at       TIMESTAMP,
    created_at    TIMESTAMP DEFAULT NOW()
);

-- 10. Short-lived OTP codes for email/SMS/Telegram 2FA (login or enrollment)
CREATE TABLE pending_otps (
    id            SERIAL PRIMARY KEY,
    account_type  VARCHAR(20) NOT NULL,
    account_id    INTEGER NOT NULL,

    channel       VARCHAR(20) NOT NULL,   -- "email" | "sms" | "telegram"
    purpose       VARCHAR(20) NOT NULL,   -- "login" | "enroll"
    code_hash     TEXT NOT NULL,
    expires_at    TIMESTAMP NOT NULL,
    consumed_at   TIMESTAMP,
    created_at    TIMESTAMP DEFAULT NOW()
);

-- 11. Short codes shown in the web UI ("send /verify2fa ABC123 to the bot")
-- that link a Telegram account to a login for 2FA delivery.
CREATE TABLE telegram_link_tokens (
    id            SERIAL PRIMARY KEY,
    account_type  VARCHAR(20) NOT NULL,
    account_id    INTEGER NOT NULL,

    code          VARCHAR(12) UNIQUE NOT NULL,
    expires_at    TIMESTAMP NOT NULL,
    consumed_at   TIMESTAMP,
    created_at    TIMESTAMP DEFAULT NOW()
);

-- 12. One row per company that has ever started a paid-plan free trial -
-- blocks a second free trial for a signup matching any prior identifying
-- signal (email, MC#, card fingerprint, or Gmail address) on a different
-- company. See services/stripe_service.py.
CREATE TABLE trial_redemptions (
    id               SERIAL PRIMARY KEY,
    company_id       INTEGER REFERENCES companies(id),

    email            VARCHAR(200),
    mc_number        VARCHAR(20),
    card_fingerprint VARCHAR(100),
    gmail_address    VARCHAR(200),

    redeemed_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_loads_company_loadid ON loads(company_id, load_id);
CREATE INDEX idx_drivers_group ON drivers(telegram_group_id);
