-- Customer success radar: SQLite schema.
-- Three layers: source tables (what Salesforce, the Subscription Manager and the
-- platform would deliver), reference tables, and analysis output.

PRAGMA foreign_keys = ON;

-- Reference -------------------------------------------------------------------

CREATE TABLE regions (
    country        TEXT PRIMARY KEY,          -- NO, DK, SE, FI
    name           TEXT NOT NULL,
    nis2_status    TEXT NOT NULL,             -- 'In force' / 'Expected'
    nis2_in_force  TEXT,                      -- ISO date, null if not yet
    nis2_note      TEXT,
    market_note    TEXT,                      -- what we know about the market
    grid_pressure  TEXT,                      -- High / Medium: how hard it is to connect new load
    grid_note      TEXT
);

CREATE TABLE modules (
    code           TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL,             -- Software / Hardware / Service
    cluster        TEXT NOT NULL,             -- Platform / Security / Reliability / Capacity
    parent_code    TEXT REFERENCES modules(code),  -- add-ons point to their module
    list_price_eur INTEGER NOT NULL,          -- illustrative, per year, size factor 1.0
    description    TEXT
);

CREATE TABLE partners (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    country        TEXT NOT NULL REFERENCES regions(country)
);

-- Source: CRM (Salesforce) ------------------------------------------------------

CREATE TABLE accounts (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    country          TEXT NOT NULL REFERENCES regions(country),
    segment          TEXT NOT NULL,           -- DSO, TSO, Municipal utility, ...
    tier             TEXT NOT NULL,           -- Strategic / Core / Growth
    channel          TEXT NOT NULL,           -- Direct / Partner
    partner_id       INTEGER REFERENCES partners(id),
    size_factor      REAL NOT NULL,           -- scales prices and estate size
    sites_total      INTEGER NOT NULL,        -- substations / sites in the customer's estate
    ot_assets_expected INTEGER NOT NULL,      -- OT assets the customer believes it has
    nis2_in_scope    INTEGER NOT NULL,        -- 0/1
    contract_start   TEXT NOT NULL,
    renewal_date     TEXT NOT NULL,
    scenario         TEXT NOT NULL,           -- demo story the generator built (not shown as data)
    grid_area        TEXT,                    -- constrained grid area, if any
    grid_constrained INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE contacts (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    name         TEXT NOT NULL,
    title        TEXT NOT NULL,
    email        TEXT NOT NULL,
    is_champion  INTEGER NOT NULL DEFAULT 0,
    is_sponsor   INTEGER NOT NULL DEFAULT 0,
    left_on      TEXT                         -- null while still at the customer
);

CREATE TABLE reviews (
    id                    INTEGER PRIMARY KEY,
    account_id            INTEGER NOT NULL REFERENCES accounts(id),
    date                  TEXT NOT NULL,
    kind                  TEXT NOT NULL,      -- QBR / Success review / Partner review
    siemens_present       INTEGER NOT NULL,   -- 0 when only the partner met the customer
    objectives_documented INTEGER NOT NULL,
    sentiment             INTEGER NOT NULL    -- -1 / 0 / +1
);

CREATE TABLE surveys (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    date        TEXT NOT NULL,
    nps         INTEGER NOT NULL              -- 0..10
);

-- Source: support desk ----------------------------------------------------------

CREATE TABLE tickets (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    opened_on   TEXT NOT NULL,
    closed_on   TEXT,
    priority    TEXT NOT NULL,                -- Low / Medium / High / Critical
    topic       TEXT NOT NULL
);

-- Source: Subscription Manager -------------------------------------------------

CREATE TABLE subscriptions (
    id                  INTEGER PRIMARY KEY,
    account_id          INTEGER NOT NULL REFERENCES accounts(id),
    module_code         TEXT NOT NULL REFERENCES modules(code),
    start_date          TEXT NOT NULL,
    end_date            TEXT,                 -- set when cancelled
    licensed_users      INTEGER NOT NULL,
    contracted_devices  INTEGER NOT NULL,
    annual_value_eur    INTEGER NOT NULL
);

CREATE TABLE subscription_events (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    module_code  TEXT NOT NULL REFERENCES modules(code),
    date         TEXT NOT NULL,
    event        TEXT NOT NULL,               -- subscribe / upgrade / downgrade / cancel
    delta_eur    INTEGER NOT NULL
);

-- Source: platform telemetry (tenant, SiemensID, modules) ------------------------

CREATE TABLE devices (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    site          TEXT NOT NULL,
    device_type   TEXT NOT NULL,              -- IPC227E / Virtual / SICAM GridEdge
    onboarded_on  TEXT NOT NULL,
    last_seen     TEXT NOT NULL
);

CREATE TABLE usage_weekly (
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    module_code     TEXT NOT NULL REFERENCES modules(code),
    week_start      TEXT NOT NULL,
    active_users    INTEGER NOT NULL,
    logins          INTEGER NOT NULL,
    top_user_share  REAL NOT NULL,            -- share of activity from the most active user
    active_sites    INTEGER NOT NULL,
    ack_rate        REAL NOT NULL,            -- alarms/alerts acknowledged within target time
    PRIMARY KEY (account_id, module_code, week_start)
);

CREATE TABLE otc_weekly (                     -- OT Companion outcome data
    account_id               INTEGER NOT NULL REFERENCES accounts(id),
    week_start               TEXT NOT NULL,
    assets_inventoried       INTEGER NOT NULL,
    baseline_deviations_open INTEGER NOT NULL,
    crit_vulns_open          INTEGER NOT NULL, -- critical/high CVEs affecting own devices
    crit_vulns_unack         INTEGER NOT NULL, -- of those, never acknowledged
    mttp_days                REAL,             -- mean time to patch, rolling 90 days
    patch_tasks_created      INTEGER NOT NULL,
    patch_tasks_completed    INTEGER NOT NULL,
    PRIMARY KEY (account_id, week_start)
);

CREATE TABLE module_kpi_weekly (               -- outcome KPIs of the other modules (catalog.toml)
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    module_code  TEXT NOT NULL REFERENCES modules(code),
    week_start   TEXT NOT NULL,
    kpi          TEXT NOT NULL,
    value        REAL NOT NULL,
    PRIMARY KEY (account_id, module_code, week_start, kpi)
);

-- Analysis output ---------------------------------------------------------------

CREATE TABLE account_metrics (
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    as_of       TEXT NOT NULL,
    data_json   TEXT NOT NULL,
    PRIMARY KEY (account_id, as_of)
);

CREATE TABLE health_scores (
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    as_of         TEXT NOT NULL,
    total         REAL NOT NULL,
    onboarding    REAL NOT NULL,
    adoption      REAL NOT NULL,
    outcomes      REAL NOT NULL,
    relationship  REAL NOT NULL,
    PRIMARY KEY (account_id, as_of)
);

CREATE TABLE signals (
    id             INTEGER PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    as_of          TEXT NOT NULL,
    rule_id        TEXT NOT NULL,
    kind           TEXT NOT NULL,             -- risk / expansion
    severity       TEXT NOT NULL,             -- low / medium / high / critical
    title          TEXT NOT NULL,
    reason         TEXT NOT NULL,
    playbook       TEXT NOT NULL,
    suggested_action TEXT,
    area           TEXT,                      -- Security / Capacity / Reliability / General
    module_code    TEXT REFERENCES modules(code),
    est_value_eur  INTEGER
);

CREATE INDEX idx_usage_account ON usage_weekly(account_id, week_start);
CREATE INDEX idx_tickets_account ON tickets(account_id, opened_on);
CREATE INDEX idx_signals_account ON signals(account_id, kind);
