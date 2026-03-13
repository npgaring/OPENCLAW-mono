-- Idempotent: add identity columns if they don't exist (e.g. DB created before identity was added)
-- Safe to run after 001_dude_x_tables.sql; no-op if columns already exist.

ALTER TABLE specs ADD COLUMN IF NOT EXISTS identity VARCHAR;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS identity VARCHAR;

CREATE INDEX IF NOT EXISTS idx_specs_identity ON specs (identity);
CREATE INDEX IF NOT EXISTS idx_plans_identity ON plans (identity);
