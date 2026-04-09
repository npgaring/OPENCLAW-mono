-- 019: Add review_json column for the new Reviewer agent phase
ALTER TABLE task_build_state ADD COLUMN IF NOT EXISTS review_json JSONB;
