# OpenClaw

Development workflow, CI/CD, and branch/commit standards are defined in **[docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md)**.

## Quick reference

- **Branches:** `main` (production), `develop` (integration), `feat/`, `fix/`, `hotfix/` with ticket and description.
- **Commits:** `<type>(<scope>): <description>` — types: feat, fix, refactor, test, docs, infra, security; scopes: spec, compiler, gate, token, runtime, ledger, telemetry, crash-guard.
- **CI** (PR to `develop`/`main`, push to `develop`): lint → unit tests → integration tests → security scan → determinism assertion.
- **Deploy** (push to `main`): deploy to **Vercel** production (optional manual approval via environment).

## Repo layout

- `services/` — dude-x (spec + compiler), openclaw-integration (gate + token + ledger; execution via OpenClaw Gateway `POST /v1/responses` at `OPENCLAW_BASE_URL`), runtime-worker.
- `libs/` — shared libraries.
- `tests/`, `tests/e2e/` — unit and end-to-end tests.
- `scripts/` — e.g. `assert_determinism.py` for CI.

Configure branch protection and GitHub secrets in the repo settings. **Deploy is off by default**: the Deploy workflow runs on push to `main` but skips until you set **ENABLE_DEPLOY** to `true` and add **VERCEL_TOKEN** (required). Optional: **VERCEL_ORG_ID**, **VERCEL_PROJECT_ID**; for monorepos set **VERCEL_ROOT_DIR** (e.g. `web`) to the app root.
