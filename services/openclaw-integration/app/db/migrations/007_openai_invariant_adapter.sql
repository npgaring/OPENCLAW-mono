-- OpenAI vessel + Invariant-C + Substrate adapter audit tables.
-- Idempotent PostgreSQL migration.

CREATE TABLE IF NOT EXISTS openai_vessel_events (
    id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(36) NOT NULL,
    ocgg_identity VARCHAR NOT NULL,
    intent VARCHAR NOT NULL,
    request_hash VARCHAR NOT NULL,
    candidate_plan_hash VARCHAR,
    model VARCHAR NOT NULL,
    request_payload JSONB NOT NULL DEFAULT '{}',
    raw_response JSONB NOT NULL DEFAULT '{}',
    schema_valid BOOLEAN NOT NULL DEFAULT FALSE,
    outcome VARCHAR NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_openai_vessel_events_trace_id ON openai_vessel_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_openai_vessel_events_request_hash ON openai_vessel_events (request_hash);
CREATE INDEX IF NOT EXISTS idx_openai_vessel_events_candidate_plan_hash ON openai_vessel_events (candidate_plan_hash);
CREATE INDEX IF NOT EXISTS idx_openai_vessel_events_created_at ON openai_vessel_events (created_at);

CREATE TABLE IF NOT EXISTS invariant_c_decisions (
    id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(36) NOT NULL,
    ocgg_identity VARCHAR NOT NULL,
    intent VARCHAR NOT NULL,
    candidate_plan_hash VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]',
    check_results JSONB NOT NULL DEFAULT '{}',
    decision_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_invariant_c_decisions_trace_id ON invariant_c_decisions (trace_id);
CREATE INDEX IF NOT EXISTS idx_invariant_c_decisions_candidate_plan_hash ON invariant_c_decisions (candidate_plan_hash);
CREATE INDEX IF NOT EXISTS idx_invariant_c_decisions_created_at ON invariant_c_decisions (created_at);

CREATE TABLE IF NOT EXISTS substrate_adapter_events (
    id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(36) NOT NULL,
    ocgg_identity VARCHAR NOT NULL,
    intent VARCHAR NOT NULL,
    candidate_plan_hash VARCHAR NOT NULL,
    integration_plan_hash VARCHAR,
    outcome VARCHAR NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]',
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_substrate_adapter_events_trace_id ON substrate_adapter_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_substrate_adapter_events_candidate_plan_hash ON substrate_adapter_events (candidate_plan_hash);
CREATE INDEX IF NOT EXISTS idx_substrate_adapter_events_integration_plan_hash ON substrate_adapter_events (integration_plan_hash);
CREATE INDEX IF NOT EXISTS idx_substrate_adapter_events_created_at ON substrate_adapter_events (created_at);

