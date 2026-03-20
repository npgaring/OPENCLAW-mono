-- Correlation id: compile → gate → task (governance audit trail)
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS trace_id VARCHAR(36);
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS trace_id VARCHAR(36);
CREATE INDEX IF NOT EXISTS idx_tasks_trace_id ON tasks(trace_id);
CREATE INDEX IF NOT EXISTS idx_gate_decisions_trace_id ON gate_decisions(trace_id);
