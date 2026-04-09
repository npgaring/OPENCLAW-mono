-- 018: Ownership-aware agent-team state for deterministic task builds
ALTER TABLE task_build_state ADD COLUMN IF NOT EXISTS work_packets_json JSONB;
ALTER TABLE task_build_state ADD COLUMN IF NOT EXISTS ownership_manifest_json JSONB;
ALTER TABLE task_build_state ADD COLUMN IF NOT EXISTS agent_results_json JSONB;
ALTER TABLE task_build_state ADD COLUMN IF NOT EXISTS verification_json JSONB;
ALTER TABLE task_build_state ADD COLUMN IF NOT EXISTS repair_history_json JSONB;
