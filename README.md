# OpenClaw

Development workflow, CI/CD, and branch/commit standards are defined in **[docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md)**.

## Quick reference

- **Branches:** `main` (production), `develop` (integration), `feat/`, `fix/`, `hotfix/` with ticket and description.
- **Commits:** `<type>(<scope>): <description>` — types: feat, fix, refactor, test, docs, infra, security; scopes: spec, compiler, gate, token, runtime, ledger, telemetry, crash-guard.
- **CI** (PR to `develop`/`main`, push to `develop`): lint → unit tests → integration tests → security scan → determinism assertion.
- **Deploy** (push to `main`): build/push images → staging → manual approval → production.

## Repo layout

- `services/` — spec-service, compiler-service, gate-service, token-service, ledger-service, runtime-worker.
- `libs/` — shared libraries.
- `tests/`, `tests/e2e/` — unit and end-to-end tests.
- `scripts/` — e.g. `assert_determinism.py` for CI.

Configure branch protection and GitHub secrets (AWS, ECR, KUBECONFIG, etc.) in the repo settings.
