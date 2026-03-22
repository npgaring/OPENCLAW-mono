-- First-class approval workflow: pause, human decision, backend-controlled resume.

CREATE TABLE IF NOT EXISTS approval_requests (
    id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(36) NOT NULL,
    task_id UUID REFERENCES tasks(task_id),
    source_layer VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    reason_code VARCHAR,
    approval_scope VARCHAR,
    snapshot_hash VARCHAR NOT NULL,
    requested_by VARCHAR,
    approved_by VARCHAR,
    rejected_by VARCHAR,
    comment TEXT,
    resume_from_stage VARCHAR NOT NULL,
    checkpoint_payload_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    decided_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_trace_id ON approval_requests(trace_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_task_id ON approval_requests(task_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_approval_requests_snapshot_hash ON approval_requests(snapshot_hash);

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approval_request_id UUID REFERENCES approval_requests(id);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS blocked_stage VARCHAR;

CREATE INDEX IF NOT EXISTS idx_tasks_approval_request_id ON tasks(approval_request_id);
