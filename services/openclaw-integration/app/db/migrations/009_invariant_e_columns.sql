-- Invariant-E execution admission (post-governance, pre-dispatch). Idempotent ADD COLUMN.

ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'invariant_e_denied';

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS invariant_e_decision VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS invariant_e_reason_codes JSONB NOT NULL DEFAULT '[]';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS invariant_e_decision_version VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS invariant_e_input_hash VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS invariant_e_evaluated_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS execution_envelope_hash VARCHAR;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS requested_capabilities_json JSONB NOT NULL DEFAULT '[]';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS allowed_capabilities_json JSONB NOT NULL DEFAULT '[]';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS budget_limit_json JSONB;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS dispatch_blocked BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_tasks_invariant_e_input_hash ON tasks (invariant_e_input_hash);
CREATE INDEX IF NOT EXISTS idx_tasks_execution_envelope_hash ON tasks (execution_envelope_hash);

ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS invariant_e_decision VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS invariant_e_reason_codes JSONB NOT NULL DEFAULT '[]';
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS invariant_e_decision_version VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS invariant_e_input_hash VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS invariant_e_evaluated_at TIMESTAMPTZ;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS execution_envelope_hash VARCHAR;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS requested_capabilities_json JSONB NOT NULL DEFAULT '[]';
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS allowed_capabilities_json JSONB NOT NULL DEFAULT '[]';
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS budget_limit_json JSONB;
ALTER TABLE gate_decisions ADD COLUMN IF NOT EXISTS dispatch_blocked BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_gate_decisions_invariant_e_input_hash ON gate_decisions (invariant_e_input_hash);
