# Database migrations (shared Neon PostgreSQL)

**Migrations run automatically on every deploy:** both `openclaw-integration` and `dude-x` run the relevant SQL files at app startup when `DATABASE_URL` points to PostgreSQL. No manual step needed for Vercel or other hosts.

You can still run these manually against your Neon database (same `DATABASE_URL` for dude-x, openclaw-integration, and openclaw-execution):

1. **001_dude_x_tables.sql** — Creates `specs`, `plans`, and `compile_events` (dude-x schema).
2. **002_add_identity_columns.sql** — Idempotent: adds `identity` to `specs`/`plans` if missing.
3. **003_openclaw_integration_tables.sql** — Creates `tasks`, `gate_decisions`, `audit_events`, `used_execution_tokens` (openclaw-integration schema).
4. **005_trace_id.sql** — Adds compile→gate→task correlation columns (`trace_id`) and indexes.
5. **007_openai_invariant_adapter.sql** — Adds OpenAI vessel / Invariant-C / substrate adapter audit tables.
6. **008_uato_task_statuses.sql** — Adds UATO task lifecycle enum values (`pending_approval`, `uato_blocked`).
7. **009_governed_dual_engine_v2.sql** — Adds DUDE-X v2 artifacts (`raw_intents_v2`, `build_sot_v2`, `execution_plans_v2`, `stage_events_v2`).
8. **013_governed_v2_execution_locks.sql** — Adds integration continuity locks table (`execution_plan_locks_v2`).

Example (from repo root):

```bash
# Set your Neon connection string
export DATABASE_URL="postgresql://user:pass@host/db?sslmode=require"
psql "$DATABASE_URL" -f migration/001_dude_x_tables.sql
psql "$DATABASE_URL" -f migration/002_add_identity_columns.sql
psql "$DATABASE_URL" -f migration/003_openclaw_integration_tables.sql
psql "$DATABASE_URL" -f migration/005_trace_id.sql
psql "$DATABASE_URL" -f migration/007_openai_invariant_adapter.sql
psql "$DATABASE_URL" -f migration/008_uato_task_statuses.sql
psql "$DATABASE_URL" -f migration/009_governed_dual_engine_v2.sql
psql "$DATABASE_URL" -f migration/013_governed_v2_execution_locks.sql
```

Or from a GUI/client: run the SQL in each file in order.
