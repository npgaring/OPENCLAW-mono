#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Governed v2 QA =="
echo "1) DUDE-X governed v2 API tests + DB type regression"
PYTHONPATH=services/dude-x .venv/bin/pytest -q \
  services/dude-x/tests/test_governed_v2.py \
  services/dude-x/tests/test_governed_v2_db_types.py

echo "2) OpenClaw governed v2 lock + continuity tests"
PYTHONPATH=services/openclaw-integration .venv/bin/pytest -q \
  services/openclaw-integration/tests/test_governed_v2_lock.py

echo "3) Optional HTTP smoke"
if [[ -n "${QA_DUDEX_BASE:-}" && -n "${QA_INTEGRATION_BASE:-}" ]]; then
  if [[ -z "${INTEGRATION_API_KEY:-}" ]]; then
    echo "INTEGRATION_API_KEY is required for HTTP smoke."
    exit 1
  fi
  .venv/bin/python scripts/qa_governed_v2_smoke.py \
    --dudex-base "${QA_DUDEX_BASE}" \
    --integration-base "${QA_INTEGRATION_BASE}" \
    --api-key "${INTEGRATION_API_KEY}"
else
  echo "Skipped HTTP smoke (set QA_DUDEX_BASE and QA_INTEGRATION_BASE to enable)."
fi

echo "Governed v2 QA completed."
