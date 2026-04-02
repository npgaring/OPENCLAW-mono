import type { JsonMap, ExecutionPlanLockResult, TaskSubmitResult } from '../types/governed';
import { request } from './api';

export function lockExecutionPlan(
  base: string,
  token: string,
  payload: JsonMap,
): Promise<ExecutionPlanLockResult> {
  return request<ExecutionPlanLockResult>(base, '/v2/execution-plan/lock', 'POST', token, payload);
}

export function submitTask(
  base: string,
  token: string,
  payload: JsonMap,
): Promise<TaskSubmitResult> {
  return request<TaskSubmitResult>(base, '/task', 'POST', token, payload);
}
