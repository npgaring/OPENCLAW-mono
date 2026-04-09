export type JsonMap = Record<string, unknown>;

export type LogLevel = 'info' | 'warn' | 'error';

export type OcggIdentity = 'W-OCGG' | 'R-OCGG';

export type Intent = 'web-build' | 'web-maintenance' | 'recruiting-update';

export type DeployTarget = 'preview' | 'production';

export interface StageLinkage {
  trace_id?: string;
  raw_intent_hash?: string;
  build_sot_hash?: string;
  execution_plan_hash?: string;
}

export interface BuildSoTEnvelope {
  stage_linkage?: StageLinkage;
  build_sot?: JsonMap;
  cognitive_outcome?: string;
}

export interface BuildSoTGovernanceResult {
  trace_id?: string;
  outcome?: string;
  reason_codes?: string[];
  governance_plan_hash?: string;
  state_hash?: string;
}

export interface BuildSoTApprovalEnvelope {
  stage_linkage?: StageLinkage;
  build_sot?: JsonMap;
}

export interface ExecutionPlan {
  stage_linkage?: StageLinkage;
  execution_mode?: string;
  operations?: JsonMap[];
  governance_projection?: JsonMap;
}

export interface ExecutionPlanLockResult {
  trace_id?: string;
  outcome?: string;
  continuity_id?: string;
  governance_evaluation_id?: string;
}

export interface TaskSubmitResult {
  task_id?: string;
  status?: string;
  execution_id?: string;
  deployment_url?: string;
  preview_url?: string;
  repository_url?: string;
  build_phase?: string;
  agent_phase?: string;
  agent_role?: string;
  verifier_report?: Record<string, unknown>;
  ownership_conflicts?: Record<string, unknown>[];
  execution_response?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface BuildPhaseResult {
  task_id: string;
  build_phase: string;
  status: string;
  agent_phase?: string;
  agent_role?: string;
  files_generated?: number;
  message?: string;
  deployment_url?: string;
  repository_url?: string;
  execution_response?: Record<string, unknown>;
  reason_codes?: string[];
  provider_error?: Record<string, unknown>;
  upstream_status_code?: number;
  upstream_error?: string;
  verifier_report?: Record<string, unknown>;
  ownership_conflicts?: Record<string, unknown>[];
}

export interface EventLogItem {
  at: string;
  level: LogLevel;
  message: string;
}

export interface PlanChecks {
  hasGitHub: boolean;
  hasVercel: boolean;
  branch: string;
}

export interface StepRow {
  name: string;
  ready: boolean;
  detail: string;
}
