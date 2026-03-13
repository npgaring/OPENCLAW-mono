-- Shared OpenClaw DB (Neon PostgreSQL): dude-x schema
-- Run this on a blank database to create specs, plans, compile_events.
-- PostgreSQL 9.6+

-- Specs: immutable stored specs keyed by canonical spec hash
CREATE TABLE IF NOT EXISTS specs (
    spec_hash VARCHAR NOT NULL PRIMARY KEY,
    identity VARCHAR,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_specs_identity ON specs (identity);

-- Plans: compiled plans keyed by canonical plan hash
CREATE TABLE IF NOT EXISTS plans (
    plan_hash VARCHAR NOT NULL PRIMARY KEY,
    identity VARCHAR,
    payload JSONB NOT NULL,
    domain VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_plans_identity ON plans (identity);

-- Compile events: audit log of every compile attempt
CREATE TABLE IF NOT EXISTS compile_events (
    id VARCHAR NOT NULL PRIMARY KEY,
    event_type VARCHAR NOT NULL,
    spec_hash VARCHAR NOT NULL,
    plan_hash VARCHAR,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_compile_events_spec_hash ON compile_events (spec_hash);
CREATE INDEX IF NOT EXISTS idx_compile_events_timestamp ON compile_events (timestamp);
