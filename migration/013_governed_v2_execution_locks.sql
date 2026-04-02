-- Governed v2 continuity lock table for execution-plan lineage.

CREATE TABLE IF NOT EXISTS execution_plan_locks_v2 (
    continuity_id VARCHAR NOT NULL PRIMARY KEY,
    trace_id VARCHAR(36) NOT NULL,
    ocgg_identity VARCHAR NOT NULL,
    build_sot_hash VARCHAR NOT NULL,
    execution_plan_hash VARCHAR NOT NULL,
    plan_hash VARCHAR NOT NULL,
    governance_evaluation_id VARCHAR NOT NULL,
    state_hash VARCHAR NULL,
    status VARCHAR NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    used_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_plan_locks_v2_trace_id ON execution_plan_locks_v2(trace_id);
CREATE INDEX IF NOT EXISTS idx_execution_plan_locks_v2_plan_hash ON execution_plan_locks_v2(plan_hash);
CREATE INDEX IF NOT EXISTS idx_execution_plan_locks_v2_build_sot_hash ON execution_plan_locks_v2(build_sot_hash);
CREATE INDEX IF NOT EXISTS idx_execution_plan_locks_v2_execution_plan_hash ON execution_plan_locks_v2(execution_plan_hash);
CREATE INDEX IF NOT EXISTS idx_execution_plan_locks_v2_status ON execution_plan_locks_v2(status);

