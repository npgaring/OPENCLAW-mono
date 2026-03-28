-- Atomic evaluation persistence (additive; does not replace tasks / gate_decisions).

CREATE TABLE IF NOT EXISTS evaluation_records (
    evaluation_id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(36) NOT NULL,
    state_hash VARCHAR NOT NULL,
    task_id UUID REFERENCES tasks(task_id),
    payload_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_evaluation_records_trace_id ON evaluation_records(trace_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_records_state_hash ON evaluation_records(state_hash);
CREATE INDEX IF NOT EXISTS idx_evaluation_records_task_id ON evaluation_records(task_id);
