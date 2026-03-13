# Development Workflow

## Git Branching Model

| Branch | Purpose | Protection Rules |
|--------|---------|------------------|
| **main** | Production-ready code | No direct push; 2 reviews required; CI must pass; signed commits |
| **develop** | Integration branch | 1 review required; CI must pass |
| **feat/[ticket]-[description]** | Feature development | Author can push; CI runs on PR open |
| **fix/[ticket]-[description]** | Bug fixes | Same as feat |
| **hotfix/[ticket]-[description]** | Emergency production fixes | Fast-path: 1 review; deploys to prod on merge to main |

Configure branch protection in GitHub: **Settings → Branches → Add rule** for `main` and `develop`.

---

## Commit Standards

**Format:** `<type>(<scope>): <description>`

**Types:** `feat` | `fix` | `refactor` | `test` | `docs` | `infra` | `security`

**Scope:** `spec` | `compiler` | `gate` | `token` | `runtime` | `ledger` | `telemetry` | `crash-guard`

### Examples

```
feat(compiler): add canonical hash assertion in compile endpoint
fix(token): enforce jti uniqueness on Redis replay store
security(gate): reject specs with P6 constraint violations
test(runtime): add parallel K8s job execution test
```

---

## Pull Request Policy

- Every PR must **reference a ticket number** in the title (e.g. `[OC-123] Add canonical hash assertion`).
- Every PR must **include or update tests** — no test-free merges for non-docs changes.
- **Security-sensitive changes** (token-service, gate-service, runtime-worker) require explicit security reviewer sign-off.
- **No force-push** to `develop` or `main` after CI has started.
- PR description must include: **what changed**, **why**, **how to test**, **rollback plan**.

---

## Lifecycle of a Change

1. Engineer creates **feat/** branch from **develop**.
2. Engineer implements change with tests; runs locally via **docker-compose**.
3. Engineer opens PR against **develop**; CI pipeline starts automatically.
4. CI runs: **lint → unit tests → integration tests → security scan → determinism assertion**.
5. Reviewer(s) approve; PR merges to **develop**.
6. **develop → main** via release PR (weekly cadence or on-demand for fixes).
7. **main** merge triggers deploy pipeline to staging, then prod (with manual gate for prod).

---

## CI/CD Overview

- **CI** (on PR to `develop`/`main` and push to `develop`): lint, unit tests, integration tests, security scan, determinism assertion.
- **Deploy** (on push to `main`): build and push images to ECR → deploy to staging → manual approval → deploy to production.

See `.github/workflows/ci.yml` and `.github/workflows/deploy.yml` for pipeline definitions.
