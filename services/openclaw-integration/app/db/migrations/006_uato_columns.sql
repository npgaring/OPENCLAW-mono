-- UATO admissibility audit columns (PostgreSQL). Idempotent ADD COLUMN.
-- Aligns with app.models.task.GateDecisionRecord UATO fields.

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS uato_decision VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS uato_reason_codes JSONB NOT NULL DEFAULT '[]';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS uato_trust_level VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS uato_authority_level VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS uato_decision_version VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS uato_input_hash VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS uato_evaluated_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_tasks_uato_input_hash ON tasks (uato_input_hash);

ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS uato_decision VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS uato_reason_codes JSONB NOT NULL DEFAULT '[]';
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS uato_trust_level VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS uato_authority_level VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS uato_decision_version VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS uato_input_hash VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS uato_evaluated_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_gate_decisions_uato_input_hash ON gate_decisions (uato_input_hash);
