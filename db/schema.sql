-- ============================================================
-- MULTI-TENANT SCHEMA
-- One database, many companies. Every table has a company_id --
-- that's how companies' data is isolated from each other.
-- ============================================================

-- 1. Companies (the MC# owner)
CREATE TABLE companies (
    id              SERIAL PRIMARY KEY,
    mc_number       VARCHAR(20) UNIQUE NOT NULL,
    company_name    VARCHAR(200) NOT NULL,
    telegram_group_prefix VARCHAR(20) UNIQUE NOT NULL,  -- e.g. "AXLE"
    subscription_tier VARCHAR(50) DEFAULT 'trial',
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 2. Each company's secret credentials (stored ENCRYPTED!)
-- Plain-text passwords/tokens are never stored here.
CREATE TABLE company_credentials (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    cred_type       VARCHAR(30) NOT NULL,   -- 'email_oauth', 'samsara_api', 'sendgrid'
    encrypted_value TEXT NOT NULL,          -- encrypted with Fernet/AES
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(company_id, cred_type)
);

-- 3. Dispatchers (log in via the mini-app)
CREATE TABLE dispatchers (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    username        VARCHAR(100) NOT NULL,
    password_hash   TEXT NOT NULL,
    telegram_user_id BIGINT,
    telegram_username VARCHAR(100),
    role            VARCHAR(20) DEFAULT 'dispatcher',  -- 'owner' | 'dispatcher'
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 4. Drivers
CREATE TABLE drivers (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    driver_bot_id   VARCHAR(20) NOT NULL,   -- bot-assigned ID#, used in the group name
    full_name       VARCHAR(150),
    telegram_group_id BIGINT UNIQUE,        -- this driver's Telegram group
    telegram_username VARCHAR(100),
    dispatcher_id   INTEGER REFERENCES dispatchers(id),
    subscription_active BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(company_id, driver_bot_id)
);

-- 5. Loads
CREATE TABLE loads (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    driver_id       INTEGER REFERENCES drivers(id),
    load_id         VARCHAR(50) NOT NULL,   -- the broker's load ID (e.g. "11111")
    broker_name     VARCHAR(150),
    broker_contact_email VARCHAR(200),
    carrier_name    VARCHAR(150),
    pu_address      TEXT,                   -- full multi-line pickup address
    pu_date         VARCHAR(50),
    pu_time         VARCHAR(50),
    pu_reference    VARCHAR(100),
    del_address     TEXT,                   -- full multi-line delivery address
    del_date        VARCHAR(50),
    del_time        VARCHAR(50),
    weight          VARCHAR(50),
    commodity       VARCHAR(200),
    reefer_temp     VARCHAR(20),
    rate_amount     NUMERIC(10,2),
    rc_pdf_path     TEXT,                   -- path to the stored RC file
    status          VARCHAR(30) DEFAULT 'dispatched', -- dispatched/loaded/bol_ok/pod_sent
    raw_extracted_json JSONB,               -- the full JSON returned by Gemini
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 6. Weekly gross-earnings log
CREATE TABLE driver_earnings (
    id              SERIAL PRIMARY KEY,
    driver_id       INTEGER REFERENCES drivers(id),
    load_id         INTEGER REFERENCES loads(id),
    amount          NUMERIC(10,2),
    week_start_date DATE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_loads_company_loadid ON loads(company_id, load_id);
CREATE INDEX idx_drivers_group ON drivers(telegram_group_id);
