-- Shared OpenClaw DB (Neon PostgreSQL): openclaw-integration schema
-- Run after 001 and 002. Creates tasks, gate_decisions, audit_events, used_execution_tokens.
-- PostgreSQL 9.6+

DO $$ BEGIN
    CREATE TYPE taskstatus AS ENUM (
        'submitted', 'completed', 'failed', 'error', 'auth_error',
        'invalid_plan', 'domain_rejected'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS tasks (
    task_id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    ocgg_identity VARCHAR NOT NULL,
    domain VARCHAR NOT NULL,
    plan_hash VARCHAR NOT NULL,
    spec_hash VARCHAR,
    policy_version VARCHAR,
    gate_outcome VARCHAR,
    reason_codes JSONB NOT NULL DEFAULT '[]',
    execution_token_hash VARCHAR,
    approval_reference VARCHAR,
    plan_json JSONB NOT NULL DEFAULT '{}',
    audit_history JSONB NOT NULL DEFAULT '[]',
    status taskstatus NOT NULL DEFAULT 'submitted',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    execution_id VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_tasks_ocgg_identity ON tasks (ocgg_identity);
CREATE INDEX IF NOT EXISTS idx_tasks_spec_hash ON tasks (spec_hash);
CREATE INDEX IF NOT EXISTS idx_tasks_execution_id ON tasks (execution_id);

CREATE TABLE IF NOT EXISTS gate_decisions (
    id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL,
    ocgg_identity VARCHAR NOT NULL,
    outcome VARCHAR NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]',
    defect_list JSONB NOT NULL DEFAULT '[]',
    policy_version VARCHAR NOT NULL,
    spec_hash VARCHAR NOT NULL,
    plan_hash VARCHAR NOT NULL,
    approver_id VARCHAR,
    approval_reference VARCHAR,
    execution_token_hash VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_gate_decisions_task_id ON gate_decisions (task_id);
CREATE INDEX IF NOT EXISTS idx_gate_decisions_ocgg_identity ON gate_decisions (ocgg_identity);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL,
    event_type VARCHAR NOT NULL,
    payload JSONB,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_audit_events_task_id ON audit_events (task_id);

CREATE TABLE IF NOT EXISTS used_execution_tokens (
    token_hash VARCHAR NOT NULL PRIMARY KEY,
    task_id UUID NOT NULL,
    used_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_used_execution_tokens_task_id ON used_execution_tokens (task_id);
