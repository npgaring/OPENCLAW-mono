-- Mirror of app/db/migrations/003_governed_dual_engine_v2.sql for local ops.

CREATE TABLE IF NOT EXISTS raw_intents_v2 (
    raw_intent_hash VARCHAR NOT NULL PRIMARY KEY,
    trace_id VARCHAR(36) NOT NULL,
    ocgg_identity VARCHAR NOT NULL,
    intent VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE TABLE IF NOT EXISTS build_sot_v2 (
    build_sot_hash VARCHAR NOT NULL PRIMARY KEY,
    trace_id VARCHAR(36) NOT NULL,
    raw_intent_hash VARCHAR NULL,
    parent_build_sot_hash VARCHAR NULL,
    ocgg_identity VARCHAR NOT NULL,
    intent VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    approval_required BOOLEAN NOT NULL DEFAULT TRUE,
    approval_status VARCHAR NOT NULL DEFAULT 'NOT_REQUESTED',
    approver_id VARCHAR NULL,
    approval_comment VARCHAR NULL,
    approved_at TIMESTAMPTZ NULL,
    governance_plan_hash VARCHAR NULL,
    governance_state_hash VARCHAR NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE TABLE IF NOT EXISTS execution_plans_v2 (
    execution_plan_hash VARCHAR NOT NULL PRIMARY KEY,
    trace_id VARCHAR(36) NOT NULL,
    build_sot_hash VARCHAR NOT NULL,
    ocgg_identity VARCHAR NOT NULL,
    intent VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    governance_plan_hash VARCHAR NULL,
    governance_state_hash VARCHAR NULL,
    governance_evaluation_id VARCHAR NULL,
    continuity_id VARCHAR NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE TABLE IF NOT EXISTS stage_events_v2 (
    id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(36) NOT NULL,
    stage VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    artifact_hash VARCHAR NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

