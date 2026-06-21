-- Agent data model.
-- Design rule: the LLM does fuzzy work (reading prose, proposing names);
-- everything countable lives here as deterministic, auditable rows.

CREATE TABLE IF NOT EXISTS issues (
    issue_id        TEXT PRIMARY KEY,        -- RSS guid/id of the post
    url             TEXT,
    published_date  TEXT,                    -- YYYY-MM-DD
    fetched_at      TEXT,                    -- ISO timestamp
    status          TEXT DEFAULT 'parsed'
);

CREATE TABLE IF NOT EXISTS deals (
    deal_id     TEXT PRIMARY KEY,            -- hash(company + round + issue_date)
    issue_id    TEXT REFERENCES issues(issue_id),
    company     TEXT,
    round_type  TEXT,
    amount_usd  INTEGER
);

CREATE TABLE IF NOT EXISTS firms (
    firm_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT UNIQUE NOT NULL,
    is_individual  INTEGER DEFAULT 0,
    first_seen     TEXT,
    last_seen      TEXT
);

-- Primary human-editable normalization lever.
CREATE TABLE IF NOT EXISTS firm_aliases (
    alias    TEXT PRIMARY KEY,               -- lowercased
    firm_id  INTEGER REFERENCES firms(firm_id)
);

-- The event log. One row per distinct (firm, deal). issue_date is
-- denormalized so windowed counts are a single fast query.
CREATE TABLE IF NOT EXISTS appearances (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id     INTEGER REFERENCES firms(firm_id),
    deal_id     TEXT REFERENCES deals(deal_id),
    role        TEXT,                         -- 'lead' | 'participation'
    issue_date  TEXT,                         -- YYYY-MM-DD
    UNIQUE(firm_id, deal_id)                  -- idempotency: re-runs can't double-count
);

CREATE INDEX IF NOT EXISTS idx_appearances_firm_date
    ON appearances(firm_id, issue_date);

-- Alert state machine: fire once on crossing the threshold, re-arm on falling below.
CREATE TABLE IF NOT EXISTS alert_state (
    firm_id       INTEGER PRIMARY KEY REFERENCES firms(firm_id),
    armed         INTEGER DEFAULT 1,
    last_fired_at TEXT
);
