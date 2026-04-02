import type {
  JsonMap,
  BuildSoTEnvelope,
  BuildSoTGovernanceResult,
  BuildSoTApprovalEnvelope,
  ExecutionPlan,
} from '../types/governed';
import { request } from './api';

export function submitRawIntent(
  base: string,
  token: string,
  payload: JsonMap,
): Promise<BuildSoTEnvelope> {
  return request<BuildSoTEnvelope>(base, '/v2/raw-intents', 'POST', token, payload);
}

export function evaluateGovernance(
  base: string,
  token: string,
  buildSotHash: string,
  payload: JsonMap,
): Promise<BuildSoTGovernanceResult> {
  return request<BuildSoTGovernanceResult>(
    base,
    `/v2/build-sot/${encodeURIComponent(buildSotHash)}/governance/evaluate`,
    'POST',
    token,
    payload,
  );
}

export function approveBuildSot(
  base: string,
  token: string,
  buildSotHash: string,
  payload: JsonMap,
): Promise<BuildSoTApprovalEnvelope> {
  return request<BuildSoTApprovalEnvelope>(
    base,
    `/v2/build-sot/${encodeURIComponent(buildSotHash)}/approval/decide`,
    'POST',
    token,
    payload,
  );
}

export function compileExecutionPlan(
  base: string,
  token: string,
  buildSotHash: string,
): Promise<ExecutionPlan> {
  return request<ExecutionPlan>(
    base,
    `/v2/build-sot/${encodeURIComponent(buildSotHash)}/compile`,
    'POST',
    token,
  );
}
