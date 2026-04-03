-- 015: Deployments tracking table for GitHub repos and Vercel deployments
CREATE TABLE IF NOT EXISTS deployments (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    trace_id VARCHAR(36) NOT NULL,
    task_id TEXT REFERENCES tasks(task_id),
    build_sot_hash VARCHAR(255),
    execution_plan_hash VARCHAR(255),
    project_name VARCHAR(255) NOT NULL,

    -- GitHub
    github_owner VARCHAR(255),
    github_repo_name VARCHAR(255),
    github_repo_url VARCHAR(1024),
    github_branch VARCHAR(128),
    github_commit_sha VARCHAR(64),

    -- Vercel
    vercel_project_id VARCHAR(255),
    vercel_project_name VARCHAR(255),
    vercel_deployment_id VARCHAR(255),
    vercel_deployment_url VARCHAR(1024),
    vercel_preview_url VARCHAR(1024),
    vercel_deploy_target VARCHAR(32),

    -- Status
    status VARCHAR(64) NOT NULL DEFAULT 'pending',
    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_deployments_trace_id ON deployments(trace_id);
CREATE INDEX IF NOT EXISTS idx_deployments_task_id ON deployments(task_id);
CREATE INDEX IF NOT EXISTS idx_deployments_project_name ON deployments(project_name);
CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status);
