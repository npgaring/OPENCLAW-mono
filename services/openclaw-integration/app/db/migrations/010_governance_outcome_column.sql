-- Persist GateEngine outcome separately from execution-dispatch denial (Invariant-E may deny after PASS).
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS governance_outcome VARCHAR;
UPDATE tasks SET governance_outcome = gate_outcome WHERE governance_outcome IS NULL AND gate_outcome IS NOT NULL;
