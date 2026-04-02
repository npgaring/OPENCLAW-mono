-- Convert UUID-typed columns to TEXT in openclaw-integration tables.
-- SQLAlchemy + asyncpg sends uuid4() as VARCHAR; PostgreSQL UUID columns
-- reject VARCHAR without explicit cast. TEXT accepts both.

BEGIN;

-- Drop FK constraints that reference UUID columns
ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS approval_requests_task_id_fkey;
ALTER TABLE evaluation_records DROP CONSTRAINT IF EXISTS evaluation_records_task_id_fkey;
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_approval_request_id_fkey;

-- tasks
ALTER TABLE tasks ALTER COLUMN task_id DROP DEFAULT;
ALTER TABLE tasks ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;
ALTER TABLE tasks ALTER COLUMN task_id SET DEFAULT gen_random_uuid()::TEXT;
ALTER TABLE tasks ALTER COLUMN approval_request_id TYPE TEXT USING approval_request_id::TEXT;

-- gate_decisions
ALTER TABLE gate_decisions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE gate_decisions ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE gate_decisions ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;
ALTER TABLE gate_decisions ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- audit_events
ALTER TABLE audit_events ALTER COLUMN id DROP DEFAULT;
ALTER TABLE audit_events ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE audit_events ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;
ALTER TABLE audit_events ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- used_execution_tokens
ALTER TABLE used_execution_tokens ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- approval_requests
ALTER TABLE approval_requests ALTER COLUMN id DROP DEFAULT;
ALTER TABLE approval_requests ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE approval_requests ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;
ALTER TABLE approval_requests ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- evaluation_records
ALTER TABLE evaluation_records ALTER COLUMN evaluation_id DROP DEFAULT;
ALTER TABLE evaluation_records ALTER COLUMN evaluation_id TYPE TEXT USING evaluation_id::TEXT;
ALTER TABLE evaluation_records ALTER COLUMN evaluation_id SET DEFAULT gen_random_uuid()::TEXT;
ALTER TABLE evaluation_records ALTER COLUMN task_id TYPE TEXT USING task_id::TEXT;

-- openai_vessel_events
ALTER TABLE openai_vessel_events ALTER COLUMN id DROP DEFAULT;
ALTER TABLE openai_vessel_events ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE openai_vessel_events ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

-- invariant_c_decisions
ALTER TABLE invariant_c_decisions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE invariant_c_decisions ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE invariant_c_decisions ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

-- substrate_adapter_events
ALTER TABLE substrate_adapter_events ALTER COLUMN id DROP DEFAULT;
ALTER TABLE substrate_adapter_events ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE substrate_adapter_events ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;

-- Re-create FK constraints (TEXT ↔ TEXT)
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
