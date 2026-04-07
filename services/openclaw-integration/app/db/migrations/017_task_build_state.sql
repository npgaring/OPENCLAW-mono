-- 017: Intermediate build state for multi-phase deterministic code generation
CREATE TABLE IF NOT EXISTS task_build_state (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    phase VARCHAR(32) NOT NULL DEFAULT 'pending',
    blueprint_json JSONB,
    repo_info_json JSONB,
    template_reference_json JSONB,
    generated_files_json JSONB,
    config_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_task_build_state_phase ON task_build_state(phase);
