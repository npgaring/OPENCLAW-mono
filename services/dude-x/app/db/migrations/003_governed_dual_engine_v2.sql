-- Governed DUDE-X v2 artifacts (raw intent, Build SoT, execution plan, stage events).

CREATE TABLE IF NOT EXISTS raw_intents_v2 (
    raw_intent_hash VARCHAR NOT NULL PRIMARY KEY,
    trace_id VARCHAR(36) NOT NULL,
    ocgg_identity VARCHAR NOT NULL,
    intent VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_raw_intents_v2_trace_id ON raw_intents_v2(trace_id);
CREATE INDEX IF NOT EXISTS idx_raw_intents_v2_identity ON raw_intents_v2(ocgg_identity);

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
CREATE INDEX IF NOT EXISTS idx_build_sot_v2_trace_id ON build_sot_v2(trace_id);
CREATE INDEX IF NOT EXISTS idx_build_sot_v2_raw_intent ON build_sot_v2(raw_intent_hash);
CREATE INDEX IF NOT EXISTS idx_build_sot_v2_parent ON build_sot_v2(parent_build_sot_hash);
CREATE INDEX IF NOT EXISTS idx_build_sot_v2_governance_plan_hash ON build_sot_v2(governance_plan_hash);

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
CREATE INDEX IF NOT EXISTS idx_execution_plans_v2_trace_id ON execution_plans_v2(trace_id);
CREATE INDEX IF NOT EXISTS idx_execution_plans_v2_build_sot_hash ON execution_plans_v2(build_sot_hash);
CREATE INDEX IF NOT EXISTS idx_execution_plans_v2_governance_plan_hash ON execution_plans_v2(governance_plan_hash);
CREATE INDEX IF NOT EXISTS idx_execution_plans_v2_continuity_id ON execution_plans_v2(continuity_id);

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
CREATE INDEX IF NOT EXISTS idx_stage_events_v2_trace_id ON stage_events_v2(trace_id);
CREATE INDEX IF NOT EXISTS idx_stage_events_v2_stage ON stage_events_v2(stage);
CREATE INDEX IF NOT EXISTS idx_stage_events_v2_artifact_hash ON stage_events_v2(artifact_hash);

