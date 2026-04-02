-- Convert UUID-typed columns to TEXT in dude-x tables.
-- SQLAlchemy + asyncpg sends uuid4() as VARCHAR; PostgreSQL UUID columns
-- reject VARCHAR without explicit cast. TEXT accepts both.

ALTER TABLE stage_events_v2 ALTER COLUMN id DROP DEFAULT;
ALTER TABLE stage_events_v2 ALTER COLUMN id TYPE TEXT USING id::TEXT;
ALTER TABLE stage_events_v2 ALTER COLUMN id SET DEFAULT gen_random_uuid()::TEXT;
