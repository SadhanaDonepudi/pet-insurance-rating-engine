-- ============================================================================
-- Pet Insurance Rating Engine — schema DDL
-- ALL DATA SYNTHETIC. This schema is PostgreSQL-compatible and runs as-is on
-- SQLite (used for local runs; see README for the PostgreSQL mapping).
-- Rate tables are modeled on the *public pattern* of a SERFF rate filing
-- (versioned tables with effective dates and filing IDs). The filing IDs and
-- all rates here are synthetic — this is NOT a real SERFF filing.
-- ============================================================================

CREATE TABLE IF NOT EXISTS rating_factors (
    factor_id   INTEGER PRIMARY KEY,
    factor_name TEXT NOT NULL UNIQUE,   -- exactly one of the 8 rating factors
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_versions (
    version_id     INTEGER PRIMARY KEY,
    version_label  TEXT NOT NULL UNIQUE,  -- 'v1' .. 'v6'
    filing_id      TEXT NOT NULL,         -- synthetic, SERFF-pattern filing id
    effective_date TEXT NOT NULL,         -- ISO-8601 date
    status         TEXT NOT NULL,         -- analytical | staging_uat | production | rolled_back
    created_at     TEXT NOT NULL,         -- ISO-8601 timestamp (UTC)
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS rate_factor_values (
    id           INTEGER PRIMARY KEY,
    version_id   INTEGER NOT NULL REFERENCES rate_versions(version_id),
    factor_name  TEXT NOT NULL,   -- one of the 8 rating factors
    factor_value TEXT NOT NULL,   -- e.g. 'french_bulldog', '500', '90'
    relativity   REAL NOT NULL,   -- multiplicative relativity vs the factor base
    UNIQUE (version_id, factor_name, factor_value)
);
CREATE INDEX IF NOT EXISTS idx_rfv_version ON rate_factor_values(version_id);

-- Synthetic quotes produced by the data generator, rated by the engine.
CREATE TABLE IF NOT EXISTS quotes (
    quote_id       INTEGER PRIMARY KEY,
    version_id     INTEGER NOT NULL REFERENCES rate_versions(version_id),
    species        TEXT NOT NULL,
    breed          TEXT NOT NULL,
    age_years      REAL NOT NULL,
    zip_code       TEXT NOT NULL,
    territory      TEXT NOT NULL,
    deductible     INTEGER NOT NULL,
    reimbursement  INTEGER NOT NULL,
    annual_limit   TEXT NOT NULL,
    discounts      TEXT NOT NULL,   -- JSON array of applied discount codes
    annual_premium REAL NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quotes_version ON quotes(version_id);

-- Release gates: analytical -> staging_uat -> production.
-- seq is a global monotonic sequence so gate ordering is checkable.
CREATE TABLE IF NOT EXISTS release_gates (
    gate_id       INTEGER PRIMARY KEY,
    version_id    INTEGER NOT NULL REFERENCES rate_versions(version_id),
    stage         TEXT NOT NULL,   -- analytical | staging_uat | production
    gate_name     TEXT NOT NULL,
    approver      TEXT NOT NULL,   -- role-based synthetic approver id
    approved_at   TEXT NOT NULL,   -- ISO-8601 timestamp (UTC)
    seq           INTEGER NOT NULL,
    checks_passed INTEGER NOT NULL -- number of UAT checks passed at this gate
);

-- Audit log: EVERY rate-table change, gate, and (had there been any) rollback.
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id    INTEGER PRIMARY KEY,
    version_id  INTEGER NOT NULL REFERENCES rate_versions(version_id),
    change_type TEXT NOT NULL,  -- rate_load | rate_change | version_created |
                                -- uat_passed | prod_signoff | rollback
    factor_name TEXT,            -- set for rate_load / rate_change rows
    old_value   TEXT,            -- JSON snapshot of previous factor values (NULL for loads)
    new_value   TEXT,            -- JSON snapshot of new factor values
    approver    TEXT NOT NULL,
    recorded_at TEXT NOT NULL,  -- ISO-8601 timestamp (UTC)
    seq         INTEGER NOT NULL,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_version ON audit_log(version_id);
