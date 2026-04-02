import type { PlanChecks, StepRow } from '../types/governed';
import { StatusPill } from './StatusPill';

function outcomeVariant(value: string, passValues: string[], warnValues: string[], badValues: string[]) {
  if (passValues.includes(value)) return 'good' as const;
  if (warnValues.includes(value)) return 'warn' as const;
  if (badValues.includes(value)) return 'bad' as const;
  return 'default' as const;
}

interface RuntimeStateProps {
  traceId: string | null;
  cognitiveOutcome: string;
  sotLockOutcome: string;
  planLockOutcome: string;
  taskStatus: string;
  planChecks: PlanChecks;
  stepRows: StepRow[];
}

export function RuntimeState({
  traceId,
  cognitiveOutcome,
  sotLockOutcome,
  planLockOutcome,
  taskStatus,
  planChecks,
  stepRows,
}: RuntimeStateProps) {
  return (
    <article className="panel">
      <div className="head">
        <h2>Runtime State</h2>
      </div>
      <div className="body">
        <div className="statusline">
          <StatusPill>trace_id={traceId ?? 'n/a'}</StatusPill>
          <StatusPill variant={outcomeVariant(cognitiveOutcome, ['PASS'], ['CLARIFY'], ['BLOCK'])}>
            cognitive={cognitiveOutcome}
          </StatusPill>
          <StatusPill variant={outcomeVariant(sotLockOutcome, ['PASS'], ['CLARIFY', 'REFORM'], ['BLOCK'])}>
            sot_lock={sotLockOutcome}
          </StatusPill>
          <StatusPill variant={outcomeVariant(planLockOutcome, ['PASS'], ['CLARIFY'], ['BLOCK'])}>
            plan_lock={planLockOutcome}
          </StatusPill>
          <StatusPill variant={outcomeVariant(taskStatus, ['completed'], ['pending_approval'], [])}>
            task={taskStatus}
          </StatusPill>
        </div>

        <ul className="steps">
          {stepRows.map((step) => (
            <li key={step.name}>
              <StatusPill variant={step.ready ? 'good' : 'default'}>{step.ready ? 'READY' : 'PENDING'}</StatusPill>
              <strong>{step.name}</strong>
              <small>{step.detail}</small>
            </li>
          ))}
        </ul>

        <div className="mini">
          GitHub provisioning op: {planChecks.hasGitHub ? 'YES' : 'NO'} | Vercel provisioning op:{' '}
          {planChecks.hasVercel ? 'YES' : 'NO'} | Deployment branch: {planChecks.branch}
        </div>
      </div>
    </article>
  );
}
