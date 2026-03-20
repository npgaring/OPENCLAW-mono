# Gate / task mutation matrix

Stakeholder-facing summary of **deny paths** for `POST /task` and related flows.  
Authoritative test names: `services/openclaw-integration/tests/test_gate_mutation_matrix.py`, `tests/test_gate_engine.py`.

| Mutation | HTTP | Layer | Expected outcome / codes |
|----------|------|-------|----------------------------|
| Missing `plan_hash` | **422** | Pydantic / FastAPI | Request rejected before gate |
| Missing `operations` | **422** | Pydantic / FastAPI | Request rejected before gate |
| `operations` not a JSON array | **422** | Pydantic / FastAPI | Request rejected before gate |
| Empty `plan_hash` | 200 | GateEngine | `gate_outcome`: **BLOCK**, `MISSING_FIELD` |
| Wrong `plan_hash` | 200 | GateEngine | **BLOCK**, `PLAN_HASH_MISMATCH` |
| Empty `operations` list | 200 | GateEngine | **BLOCK**, `MISSING_FIELD` |
| `deployment_target` production without approver / approval ref | 200 | GateEngine | **BLOCK**, `PROD_DEPLOY_NO_APPROVAL` (prod rules unchanged) |
| Unknown `ocgg_identity` | 422 | API | `INVALID_PAYLOAD` (integration) |

**Notes**

- **422 vs 200+BLOCK**: Both are valid “deny” behaviors; 422 means the payload never reached `GateEngine`. Tests assert 422 for the three rows above and gate BLOCK for the rest.
- **Gate-only evaluate**: `POST /gate/evaluate` accepts a looser body (`operations` optional in schema); task submit is stricter.
- Regenerate or extend this table when adding rows to `test_gate_mutation_matrix.py`.
