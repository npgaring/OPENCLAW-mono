-- 016: Add build monitoring columns to deployments table
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS build_logs TEXT;
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS fix_attempts INTEGER DEFAULT 0;
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS vercel_ready_state VARCHAR(64);
