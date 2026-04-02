-- Convert all UUID-typed columns to TEXT across both services.
--
-- Root cause: SQLAlchemy + asyncpg sends Python uuid4() values as VARCHAR,
-- but PostgreSQL UUID columns reject VARCHAR input without explicit cast.
-- Changing DB columns to TEXT accepts both VARCHAR and UUID-typed inputs.
--
-- Safe to re-run: every ALTER uses IF EXISTS / USING guards.
-- Run this against the shared Neon database.

BEGIN;

-- ============================================================
-- 1. DUDE-X: stage_events_v2
-- ============================================================
ALTER TABLE stage_events_v2 ALTER COLUMN id DROP DEFAULT;
ALTER TABLE stage_events_v2 ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE stage_events_v2 ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

-- ============================================================
-- 2. OPENCLAW-INTEGRATION: drop FK constraints first
-- ============================================================
ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS approval_requests_task_id_fkey;
ALTER TABLE evaluation_records DROP CONSTRAINT IF EXISTS evaluation_records_task_id_fkey;
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_approval_request_id_fkey;

-- ============================================================
-- 3. tasks (PK referenced by multiple FKs)
-- ============================================================
ALTER TABLE tasks ALTER COLUMN task_id DROP DEFAULT;
ALTER TABLE tasks ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;
ALTER TABLE tasks ALTER COLUMN task_id SET DEFAULT gen_random_uuid()::TEXT;

ALTER TABLE tasks ALTER COLUMN approval_request_id TYPE TEXT USING approval_request_id::TEXT;

-- ============================================================
-- 4. gate_decisions
-- ============================================================
ALTER TABLE gate_decisions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE gate_decisions ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE gate_decisions ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

ALTER TABLE gate_decisions ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- ============================================================
-- 5. audit_events
-- ============================================================
ALTER TABLE audit_events ALTER COLUMN id DROP DEFAULT;
ALTER TABLE audit_events ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE audit_events ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

ALTER TABLE audit_events ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- ============================================================
-- 6. used_execution_tokens
-- ============================================================
ALTER TABLE used_execution_tokens ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- ============================================================
-- 7. approval_requests
-- ============================================================
ALTER TABLE approval_requests ALTER COLUMN id DROP DEFAULT;
ALTER TABLE approval_requests ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE approval_requests ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

ALTER TABLE approval_requests ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- ============================================================
-- 8. evaluation_records
-- ============================================================
ALTER TABLE evaluation_records ALTER COLUMN evaluation_id DROP DEFAULT;
ALTER TABLE evaluation_records ALTER COLUMN evaluation_id TYPE TEXT USING evaluation_id::TEXT;
ALTER TABLE evaluation_records ALTER COLUMN evaluation_id SET DEFAULT gen_random_uuid()::TEXT;

ALTER TABLE evaluation_records ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- ============================================================
-- 9. openai_vessel_events
-- ============================================================
ALTER TABLE openai_vessel_events ALTER COLUMN id DROP DEFAULT;
ALTER TABLE openai_vessel_events ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE openai_vessel_events ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

-- ============================================================
-- 10. invariant_c_decisions
-- ============================================================
ALTER TABLE invariant_c_decisions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE invariant_c_decisions ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE invariant_c_decisions ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

-- ============================================================
-- 11. substrate_adapter_events
-- ============================================================
ALTER TABLE substrate_adapter_events ALTER COLUMN id DROP DEFAULT;
ALTER TABLE substrate_adapter_events ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE substrate_adapter_events ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

-- ============================================================
-- 12. Re-create FK constraints (now TEXT ↔ TEXT)
-- ============================================================
ALTER TABLE approval_requests
  ADD CONSTRAINT approval_requests_task_id_fkey
  FOREIGN KEY (task_id) REFERENCES tasks(task_id);

ALTER TABLE evaluation_records
  ADD CONSTRAINT evaluation_records_task_id_fkey
  FOREIGN KEY (task_id) REFERENCES tasks(task_id);

ALTER TABLE tasks
  ADD CONSTRAINT tasks_approval_request_id_fkey
  FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id);

COMMIT;
