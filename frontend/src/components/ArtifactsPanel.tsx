import type { ExecutionPlan, TaskSubmitResult } from '../types/governed';
import { JsonViewer } from './JsonViewer';

interface ArtifactsPanelProps {
  displayBuildSot: unknown;
  displayLocks: unknown;
  executionPlan: ExecutionPlan | null;
  taskResult: TaskSubmitResult | null;
}

export function ArtifactsPanel({ displayBuildSot, displayLocks, executionPlan, taskResult }: ArtifactsPanelProps) {
  return (
    <article className="panel artifacts-panel">
      <div className="head">
        <h2>Artifacts</h2>
      </div>
      <div className="body">
        <JsonViewer label="Build SoT" value={displayBuildSot} />
        <JsonViewer label="Governance / Lock Results" value={displayLocks} />
        <JsonViewer label="Execution Plan" value={executionPlan} />
        <JsonViewer label="Task Response" value={taskResult} />
      </div>
    </article>
  );
}
