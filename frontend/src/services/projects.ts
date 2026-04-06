import { request } from './api';

export interface ProjectDeployment {
  id: string;
  trace_id: string;
  task_id: string | null;
  project_name: string;
  github_owner: string | null;
  github_repo_name: string | null;
  github_repo_url: string | null;
  vercel_deployment_url: string | null;
  vercel_preview_url: string | null;
  vercel_ready_state: string | null;
  status: string;
  error_message: string | null;
  build_logs: string | null;
  fix_attempts: number;
  created_at: string;
  updated_at: string;
}

export interface RetriggerResult {
  status: string;
  message: string;
  new_deployment_id: string | null;
  deployment_url: string | null;
}

export function fetchProjects(
  base: string,
  token: string,
  limit = 50,
  offset = 0,
): Promise<ProjectDeployment[]> {
  return request<ProjectDeployment[]>(
    base,
    `/v2/projects?limit=${limit}&offset=${offset}`,
    'GET',
    token,
  );
}

export function retriggerDeployment(
  base: string,
  token: string,
  deploymentId: string,
): Promise<RetriggerResult> {
  return request<RetriggerResult>(
    base,
    `/v2/deployments/${deploymentId}/retrigger`,
    'POST',
    token,
  );
}
