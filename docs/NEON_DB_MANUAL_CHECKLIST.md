# Neon DB Manual Checklist

This document is the canonical manual-check reference for the project database schema.

Source of truth used:
- `services/openclaw-integration/app/db/migrations/001_dude_x_tables.sql` through `012_evaluation_records.sql`
- Runtime model check for `TaskStatus` in `services/openclaw-integration/app/models/task.py`

## Expected Coverage

- Expected tables in `public`: `12`
- Expected columns total: `147`
- Expected enum type: `taskstatus`

## Required Tables and Columns

Use this as a manual checklist against Neon.

| Table | Required columns (name:type) |
|---|---|
| `specs` | `spec_hash`: `VARCHAR`<br>`identity`: `VARCHAR`<br>`payload`: `JSONB`<br>`received_at`: `TIMESTAMPTZ` |
| `plans` | `plan_hash`: `VARCHAR`<br>`identity`: `VARCHAR`<br>`payload`: `JSONB`<br>`domain`: `VARCHAR`<br>`created_at`: `TIMESTAMPTZ` |
| `compile_events` | `id`: `VARCHAR`<br>`event_type`: `VARCHAR`<br>`spec_hash`: `VARCHAR`<br>`plan_hash`: `VARCHAR`<br>`timestamp`: `TIMESTAMPTZ`<br>`metadata`: `JSONB` |
| `tasks` | `task_id`: `UUID`<br>`ocgg_identity`: `VARCHAR`<br>`domain`: `VARCHAR`<br>`plan_hash`: `VARCHAR`<br>`spec_hash`: `VARCHAR`<br>`policy_version`: `VARCHAR`<br>`gate_outcome`: `VARCHAR`<br>`reason_codes`: `JSONB`<br>`execution_token_hash`: `VARCHAR`<br>`approval_reference`: `VARCHAR`<br>`plan_json`: `JSONB`<br>`audit_history`: `JSONB`<br>`status`: `taskstatus`<br>`created_at`: `TIMESTAMPTZ`<br>`updated_at`: `TIMESTAMPTZ`<br>`execution_id`: `VARCHAR`<br>`trace_id`: `VARCHAR(36)`<br>`uato_decision`: `VARCHAR`<br>`uato_reason_codes`: `JSONB`<br>`uato_trust_level`: `VARCHAR`<br>`uato_authority_level`: `VARCHAR`<br>`uato_decision_version`: `VARCHAR`<br>`uato_input_hash`: `VARCHAR`<br>`uato_evaluated_at`: `TIMESTAMPTZ`<br>`invariant_e_decision`: `VARCHAR`<br>`invariant_e_reason_codes`: `JSONB`<br>`invariant_e_decision_version`: `VARCHAR`<br>`invariant_e_input_hash`: `VARCHAR`<br>`invariant_e_evaluated_at`: `TIMESTAMPTZ`<br>`execution_envelope_hash`: `VARCHAR`<br>`requested_capabilities_json`: `JSONB`<br>`allowed_capabilities_json`: `JSONB`<br>`budget_limit_json`: `JSONB`<br>`dispatch_blocked`: `BOOLEAN`<br>`governance_outcome`: `VARCHAR`<br>`approval_request_id`: `UUID`<br>`blocked_stage`: `VARCHAR` |
| `gate_decisions` | `id`: `UUID`<br>`task_id`: `UUID`<br>`ocgg_identity`: `VARCHAR`<br>`outcome`: `VARCHAR`<br>`reason_codes`: `JSONB`<br>`defect_list`: `JSONB`<br>`policy_version`: `VARCHAR`<br>`spec_hash`: `VARCHAR`<br>`plan_hash`: `VARCHAR`<br>`approver_id`: `VARCHAR`<br>`approval_reference`: `VARCHAR`<br>`execution_token_hash`: `VARCHAR`<br>`created_at`: `TIMESTAMPTZ`<br>`trace_id`: `VARCHAR(36)`<br>`uato_decision`: `VARCHAR`<br>`uato_reason_codes`: `JSONB`<br>`uato_trust_level`: `VARCHAR`<br>`uato_authority_level`: `VARCHAR`<br>`uato_decision_version`: `VARCHAR`<br>`uato_input_hash`: `VARCHAR`<br>`uato_evaluated_at`: `TIMESTAMPTZ`<br>`invariant_e_decision`: `VARCHAR`<br>`invariant_e_reason_codes`: `JSONB`<br>`invariant_e_decision_version`: `VARCHAR`<br>`invariant_e_input_hash`: `VARCHAR`<br>`invariant_e_evaluated_at`: `TIMESTAMPTZ`<br>`execution_envelope_hash`: `VARCHAR`<br>`requested_capabilities_json`: `JSONB`<br>`allowed_capabilities_json`: `JSONB`<br>`budget_limit_json`: `JSONB`<br>`dispatch_blocked`: `BOOLEAN` |
| `audit_events` | `id`: `UUID`<br>`task_id`: `UUID`<br>`event_type`: `VARCHAR`<br>`payload`: `JSONB`<br>`timestamp`: `TIMESTAMPTZ` |
| `used_execution_tokens` | `token_hash`: `VARCHAR`<br>`task_id`: `UUID`<br>`used_at`: `TIMESTAMPTZ` |
| `openai_vessel_events` | `id`: `UUID`<br>`trace_id`: `VARCHAR(36)`<br>`ocgg_identity`: `VARCHAR`<br>`intent`: `VARCHAR`<br>`request_hash`: `VARCHAR`<br>`candidate_plan_hash`: `VARCHAR`<br>`model`: `VARCHAR`<br>`request_payload`: `JSONB`<br>`raw_response`: `JSONB`<br>`schema_valid`: `BOOLEAN`<br>`outcome`: `VARCHAR`<br>`reason_codes`: `JSONB`<br>`created_at`: `TIMESTAMPTZ` |
| `invariant_c_decisions` | `id`: `UUID`<br>`trace_id`: `VARCHAR(36)`<br>`ocgg_identity`: `VARCHAR`<br>`intent`: `VARCHAR`<br>`candidate_plan_hash`: `VARCHAR`<br>`decision`: `VARCHAR`<br>`reason_codes`: `JSONB`<br>`check_results`: `JSONB`<br>`decision_version`: `VARCHAR`<br>`created_at`: `TIMESTAMPTZ` |
| `substrate_adapter_events` | `id`: `UUID`<br>`trace_id`: `VARCHAR(36)`<br>`ocgg_identity`: `VARCHAR`<br>`intent`: `VARCHAR`<br>`candidate_plan_hash`: `VARCHAR`<br>`integration_plan_hash`: `VARCHAR`<br>`outcome`: `VARCHAR`<br>`reason_codes`: `JSONB`<br>`payload`: `JSONB`<br>`created_at`: `TIMESTAMPTZ` |
| `approval_requests` | `id`: `UUID`<br>`trace_id`: `VARCHAR(36)`<br>`task_id`: `UUID`<br>`source_layer`: `VARCHAR`<br>`status`: `VARCHAR`<br>`reason_code`: `VARCHAR`<br>`approval_scope`: `VARCHAR`<br>`snapshot_hash`: `VARCHAR`<br>`requested_by`: `VARCHAR`<br>`approved_by`: `VARCHAR`<br>`rejected_by`: `VARCHAR`<br>`comment`: `TEXT`<br>`resume_from_stage`: `VARCHAR`<br>`checkpoint_payload_json`: `JSONB`<br>`created_at`: `TIMESTAMPTZ`<br>`decided_at`: `TIMESTAMPTZ`<br>`expires_at`: `TIMESTAMPTZ` |
| `evaluation_records` | `evaluation_id`: `UUID`<br>`trace_id`: `VARCHAR(36)`<br>`state_hash`: `VARCHAR`<br>`task_id`: `UUID`<br>`payload_json`: `JSONB`<br>`created_at`: `TIMESTAMPTZ` |

## Required Enum Values

`taskstatus` must include all values below:

- `submitted`
- `completed`
- `failed`
- `error`
- `auth_error`
- `invalid_plan`
- `domain_rejected`
- `partial`
- `needs_review`
- `execution_aborted`
- `pending_approval`
- `uato_blocked`
- `invariant_e_denied`

Note: `execution_aborted` is runtime-required by the backend model and should exist in Neon.

## Manual Validation SQL (Neon)

### 1) List all tables and columns

```sql
SELECT
  c.table_schema,
  c.table_name,
  c.column_name,
  c.data_type,
  c.udt_name,
  c.ordinal_position
FROM information_schema.columns c
WHERE c.table_schema = 'public'
ORDER BY c.table_name, c.ordinal_position;
```

### 2) Check required tables

```sql
SELECT t.table_name
FROM information_schema.tables t
WHERE t.table_schema = 'public'
  AND t.table_name IN (
    'specs',
    'plans',
    'compile_events',
    'tasks',
    'gate_decisions',
    'audit_events',
    'used_execution_tokens',
    'openai_vessel_events',
    'invariant_c_decisions',
    'substrate_adapter_events',
    'approval_requests',
    'evaluation_records'
  )
ORDER BY t.table_name;
```

### 3) Check `taskstatus` enum values

```sql
SELECT e.enumlabel
FROM pg_enum e
JOIN pg_type t ON t.oid = e.enumtypid
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
  AND t.typname = 'taskstatus'
ORDER BY e.enumsortorder;
```

### 4) Full schema existence check (tables + columns)

Run this single query in Neon.  
If it returns **zero rows**, all required tables/columns exist.

```sql
WITH expected AS (
  SELECT *
  FROM (
    VALUES
      ('specs', ARRAY[
        'spec_hash','identity','payload','received_at'
      ]::text[]),
      ('plans', ARRAY[
        'plan_hash','identity','payload','domain','created_at'
      ]::text[]),
      ('compile_events', ARRAY[
        'id','event_type','spec_hash','plan_hash','timestamp','metadata'
      ]::text[]),
      ('tasks', ARRAY[
        'task_id','ocgg_identity','domain','plan_hash','spec_hash','policy_version',
        'gate_outcome','reason_codes','execution_token_hash','approval_reference',
        'plan_json','audit_history','status','created_at','updated_at','execution_id',
        'trace_id','uato_decision','uato_reason_codes','uato_trust_level',
        'uato_authority_level','uato_decision_version','uato_input_hash','uato_evaluated_at',
        'invariant_e_decision','invariant_e_reason_codes','invariant_e_decision_version',
        'invariant_e_input_hash','invariant_e_evaluated_at','execution_envelope_hash',
        'requested_capabilities_json','allowed_capabilities_json','budget_limit_json',
        'dispatch_blocked','governance_outcome','approval_request_id','blocked_stage'
      ]::text[]),
      ('gate_decisions', ARRAY[
        'id','task_id','ocgg_identity','outcome','reason_codes','defect_list',
        'policy_version','spec_hash','plan_hash','approver_id','approval_reference',
        'execution_token_hash','created_at','trace_id','uato_decision','uato_reason_codes',
        'uato_trust_level','uato_authority_level','uato_decision_version','uato_input_hash',
        'uato_evaluated_at','invariant_e_decision','invariant_e_reason_codes',
        'invariant_e_decision_version','invariant_e_input_hash','invariant_e_evaluated_at',
        'execution_envelope_hash','requested_capabilities_json','allowed_capabilities_json',
        'budget_limit_json','dispatch_blocked'
      ]::text[]),
      ('audit_events', ARRAY[
        'id','task_id','event_type','payload','timestamp'
      ]::text[]),
      ('used_execution_tokens', ARRAY[
        'token_hash','task_id','used_at'
      ]::text[]),
      ('openai_vessel_events', ARRAY[
        'id','trace_id','ocgg_identity','intent','request_hash','candidate_plan_hash',
        'model','request_payload','raw_response','schema_valid','outcome','reason_codes','created_at'
      ]::text[]),
      ('invariant_c_decisions', ARRAY[
        'id','trace_id','ocgg_identity','intent','candidate_plan_hash','decision',
        'reason_codes','check_results','decision_version','created_at'
      ]::text[]),
      ('substrate_adapter_events', ARRAY[
        'id','trace_id','ocgg_identity','intent','candidate_plan_hash',
        'integration_plan_hash','outcome','reason_codes','payload','created_at'
      ]::text[]),
      ('approval_requests', ARRAY[
        'id','trace_id','task_id','source_layer','status','reason_code','approval_scope',
        'snapshot_hash','requested_by','approved_by','rejected_by','comment',
        'resume_from_stage','checkpoint_payload_json','created_at','decided_at','expires_at'
      ]::text[]),
      ('evaluation_records', ARRAY[
        'evaluation_id','trace_id','state_hash','task_id','payload_json','created_at'
      ]::text[])
  ) v(table_name, column_names)
),
expected_columns AS (
  SELECT e.table_name, unnest(e.column_names) AS column_name
  FROM expected e
),
missing_tables AS (
  SELECT DISTINCT ec.table_name
  FROM expected_columns ec
  LEFT JOIN information_schema.tables t
    ON t.table_schema = 'public'
   AND t.table_name = ec.table_name
  WHERE t.table_name IS NULL
),
missing_columns AS (
  SELECT ec.table_name, ec.column_name
  FROM expected_columns ec
  LEFT JOIN information_schema.columns c
    ON c.table_schema = 'public'
   AND c.table_name = ec.table_name
   AND c.column_name = ec.column_name
  WHERE c.column_name IS NULL
)
SELECT
  'MISSING_TABLE' AS issue_type,
  mt.table_name,
  NULL::text AS column_name
FROM missing_tables mt
UNION ALL
SELECT
  'MISSING_COLUMN' AS issue_type,
  mc.table_name,
  mc.column_name
FROM missing_columns mc
ORDER BY issue_type, table_name, column_name;
```

### 5) Quick PASS/FAIL status query

```sql
WITH issues AS (
  WITH expected AS (
    SELECT *
    FROM (
      VALUES
        ('specs', ARRAY['spec_hash','identity','payload','received_at']::text[]),
        ('plans', ARRAY['plan_hash','identity','payload','domain','created_at']::text[]),
        ('compile_events', ARRAY['id','event_type','spec_hash','plan_hash','timestamp','metadata']::text[]),
        ('tasks', ARRAY[
          'task_id','ocgg_identity','domain','plan_hash','spec_hash','policy_version',
          'gate_outcome','reason_codes','execution_token_hash','approval_reference',
          'plan_json','audit_history','status','created_at','updated_at','execution_id',
          'trace_id','uato_decision','uato_reason_codes','uato_trust_level',
          'uato_authority_level','uato_decision_version','uato_input_hash','uato_evaluated_at',
          'invariant_e_decision','invariant_e_reason_codes','invariant_e_decision_version',
          'invariant_e_input_hash','invariant_e_evaluated_at','execution_envelope_hash',
          'requested_capabilities_json','allowed_capabilities_json','budget_limit_json',
          'dispatch_blocked','governance_outcome','approval_request_id','blocked_stage'
        ]::text[]),
        ('gate_decisions', ARRAY[
          'id','task_id','ocgg_identity','outcome','reason_codes','defect_list',
          'policy_version','spec_hash','plan_hash','approver_id','approval_reference',
          'execution_token_hash','created_at','trace_id','uato_decision','uato_reason_codes',
          'uato_trust_level','uato_authority_level','uato_decision_version','uato_input_hash',
          'uato_evaluated_at','invariant_e_decision','invariant_e_reason_codes',
          'invariant_e_decision_version','invariant_e_input_hash','invariant_e_evaluated_at',
          'execution_envelope_hash','requested_capabilities_json','allowed_capabilities_json',
          'budget_limit_json','dispatch_blocked'
        ]::text[]),
        ('audit_events', ARRAY['id','task_id','event_type','payload','timestamp']::text[]),
        ('used_execution_tokens', ARRAY['token_hash','task_id','used_at']::text[]),
        ('openai_vessel_events', ARRAY[
          'id','trace_id','ocgg_identity','intent','request_hash','candidate_plan_hash',
          'model','request_payload','raw_response','schema_valid','outcome','reason_codes','created_at'
        ]::text[]),
        ('invariant_c_decisions', ARRAY[
          'id','trace_id','ocgg_identity','intent','candidate_plan_hash','decision',
          'reason_codes','check_results','decision_version','created_at'
        ]::text[]),
        ('substrate_adapter_events', ARRAY[
          'id','trace_id','ocgg_identity','intent','candidate_plan_hash',
          'integration_plan_hash','outcome','reason_codes','payload','created_at'
        ]::text[]),
        ('approval_requests', ARRAY[
          'id','trace_id','task_id','source_layer','status','reason_code','approval_scope',
          'snapshot_hash','requested_by','approved_by','rejected_by','comment',
          'resume_from_stage','checkpoint_payload_json','created_at','decided_at','expires_at'
        ]::text[]),
        ('evaluation_records', ARRAY['evaluation_id','trace_id','state_hash','task_id','payload_json','created_at']::text[])
    ) v(table_name, column_names)
  ),
  expected_columns AS (
    SELECT e.table_name, unnest(e.column_names) AS column_name
    FROM expected e
  ),
  missing_tables AS (
    SELECT DISTINCT ec.table_name
    FROM expected_columns ec
    LEFT JOIN information_schema.tables t
      ON t.table_schema = 'public'
     AND t.table_name = ec.table_name
    WHERE t.table_name IS NULL
  ),
  missing_columns AS (
    SELECT ec.table_name, ec.column_name
    FROM expected_columns ec
    LEFT JOIN information_schema.columns c
      ON c.table_schema = 'public'
     AND c.table_name = ec.table_name
     AND c.column_name = ec.column_name
    WHERE c.column_name IS NULL
  )
  SELECT * FROM missing_tables
  UNION ALL
  SELECT table_name FROM missing_columns
)
SELECT CASE
  WHEN EXISTS (SELECT 1 FROM issues) THEN 'FAIL: missing tables/columns found'
  ELSE 'PASS: all required tables/columns exist'
END AS schema_check_result;
```

## Snapshot Note (2026-03-29 export)

Based on `/Users/braiebook/Downloads/nameless-unit-25749322_production_neondb_2026-03-29_01-17-25.json`:

- Missing table/columns: all `evaluation_records.*` columns
- Also verify `taskstatus` includes `execution_aborted`
