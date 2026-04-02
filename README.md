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

## Governed Builder Console

- Root `/` now serves a React + TypeScript operator frontend (`frontend/`) that runs the full governed v2 flow:
  1. raw intent -> Build SoT (`/dude-x/v2/raw-intents`)
  2. Build SoT lock eval (`/dude-x/v2/build-sot/{hash}/governance/evaluate`)
  3. SoT approval (`/dude-x/v2/build-sot/{hash}/approval/decide`)
  4. compile (`/dude-x/v2/build-sot/{hash}/compile`)
  5. execution lock (`/openclaw-integration/v2/execution-plan/lock`)
  6. task dispatch (`/openclaw-integration/task`)
- Set `INTEGRATION_API_KEY` and paste it in the UI as Bearer token.
- The compiled plan view highlights GitHub and Vercel provisioning operations to validate auto-build/auto-deploy contract integrity before dispatch.
- Local frontend dev:
  1. `cd frontend`
  2. `npm install`
  3. `npm run dev`

Configure branch protection and GitHub secrets in the repo settings. **Deploy is off by default**: the Deploy workflow runs on push to `main` but skips until you set **ENABLE_DEPLOY** to `true` and add **VERCEL_TOKEN** (required). Optional: **VERCEL_ORG_ID**, **VERCEL_PROJECT_ID**; for monorepos set **VERCEL_ROOT_DIR** (e.g. `web`) to the app root.
