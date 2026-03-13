# Database migrations (shared Neon PostgreSQL)

**Migrations run automatically on every deploy:** both `openclaw-integration` and `dude-x` run the relevant SQL files at app startup when `DATABASE_URL` points to PostgreSQL. No manual step needed for Vercel or other hosts.

You can still run these manually against your Neon database (same `DATABASE_URL` for dude-x, openclaw-integration, and openclaw-execution):

1. **001_dude_x_tables.sql** — Creates `specs`, `plans`, and `compile_events` (dude-x schema).
2. **002_add_identity_columns.sql** — Idempotent: adds `identity` to `specs`/`plans` if missing.
3. **003_openclaw_integration_tables.sql** — Creates `tasks`, `gate_decisions`, `audit_events`, `used_execution_tokens` (openclaw-integration schema).

Example (from repo root):

```bash
# Set your Neon connection string
export DATABASE_URL="postgresql://user:pass@host/db?sslmode=require"
psql "$DATABASE_URL" -f migration/001_dude_x_tables.sql
psql "$DATABASE_URL" -f migration/002_add_identity_columns.sql
psql "$DATABASE_URL" -f migration/003_openclaw_integration_tables.sql
```

Or from a GUI/client: run the SQL in each file in order.
