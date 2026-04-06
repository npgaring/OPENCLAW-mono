import { useGovernedFlow } from '../hooks/useGovernedFlow';
import { Layout } from '../components/Layout';
import { ControlsPanel } from '../components/ControlsPanel';
import { RuntimeState } from '../components/RuntimeState';
import { ArtifactsPanel } from '../components/ArtifactsPanel';
import { EventLog } from '../components/EventLog';
import { PreviewPanel } from '../components/PreviewPanel';
import { FileTree } from '../components/FileTree';
import { CodeEditor } from '../components/CodeEditor';
import { RefinementChat } from '../components/RefinementChat';
import { ProgressBar, type ProgressStep, type StepStatus } from '../components/ProgressBar';

export function ConsolePage() {
  const flow = useGovernedFlow();
  const hasFiles = flow.generatedFiles.length > 0;
  const hasDeployment = !!(flow.previewUrl || flow.repositoryUrl);

  return (
    <Layout>
      <section className="layout">
        <ControlsPanel
          dudexBase={flow.dudexBase}
          onDudexBaseChange={flow.setDudexBase}
          integrationBase={flow.integrationBase}
          onIntegrationBaseChange={flow.setIntegrationBase}
          apiToken={flow.apiToken}
          onApiTokenChange={flow.setApiToken}
          identity={flow.identity}
          onIdentityChange={flow.setIdentity}
          intent={flow.intent}
          onIntentChange={flow.setIntent}
          deployTarget={flow.deployTarget}
          onDeployTargetChange={flow.setDeployTarget}
          approverId={flow.approverId}
          onApproverIdChange={flow.setApproverId}
          idea={flow.idea}
          onIdeaChange={flow.setIdea}
          voice={flow.voice}
          onVoiceChange={flow.setVoice}
          projectName={flow.projectName}
          onProjectNameChange={flow.setProjectName}
          sitePurpose={flow.sitePurpose}
          onSitePurposeChange={flow.setSitePurpose}
          audience={flow.audience}
          onAudienceChange={flow.setAudience}
          tone={flow.tone}
          onToneChange={flow.setTone}
          pages={flow.pages}
          onPagesChange={flow.setPages}
          integrations={flow.integrations}
          onIntegrationsChange={flow.setIntegrations}
          busyAction={flow.busyAction}
          onRunCognitive={() => flow.runAction('cognitive', flow.onRunCognitiveMode)}
          onEvaluateSotLock={() => flow.runAction('sot-lock', flow.onEvaluateBuildSotLock)}
          onApprove={() => flow.runAction('approve', flow.onApproveBuildSot)}
          onCompile={() => flow.runAction('compile', flow.onCompileExecutionPlan)}
          onLockPlan={() => flow.runAction('plan-lock', flow.onLockExecutionPlan)}
          onSubmitTask={() => flow.runAction('task', flow.onSubmitTask)}
          onClear={flow.onClearSession}
        />

        <section className="stack">
          <RuntimeState
            traceId={flow.traceId}
            cognitiveOutcome={flow.cognitiveOutcome}
            sotLockOutcome={flow.sotLockOutcome}
            planLockOutcome={flow.planLockOutcome}
            taskStatus={flow.taskStatus}
            planChecks={flow.planChecks}
            stepRows={flow.stepRows}
          />

          <section className="deployment-results">
            <div className="deployment-header">
              <h3>Deployment Pipeline</h3>
              {hasDeployment ? (
                <span className={`deployment-badge ${flow.taskStatus === 'completed' ? 'success' : 'pending'}`}>
                  {flow.taskStatus === 'completed' ? 'Deployed' : flow.taskStatus}
                </span>
              ) : (
                <span className="deployment-badge idle">Waiting</span>
              )}
            </div>
            {(() => {
              const execResp = flow.taskResult?.execution_response ?? {};
              const respMap = execResp as Record<string, unknown>;
              const steps = respMap.steps_completed as string[] | undefined;
              const filesGen = respMap.files_generated as number | undefined;
              const readyState = (respMap.vercel_ready_state as string) || '';
              const reasonCodes = (flow.taskResult as Record<string, unknown> | null)?.reason_codes as string[] | undefined;
              const hasSteps = steps && steps.length > 0;
              const isBusy = flow.busyAction === 'task';
              const hasFailed = flow.taskStatus === 'needs_review' || (reasonCodes && reasonCodes.length > 0);

              function stepStatus(stepKey: string, prevDone: boolean): StepStatus {
                if (hasSteps && steps!.includes(stepKey)) return 'done';
                if (hasFailed && prevDone) return 'error';
                if (isBusy && prevDone) return 'active';
                return 'pending';
              }

              const cogDone = flow.cognitiveOutcome !== '-';
              const govDone = flow.sotLockOutcome !== '-';

              const progressSteps: ProgressStep[] = [
                {
                  label: 'Cognitive Mode',
                  status: cogDone ? 'done' : (flow.busyAction === 'cognitive' ? 'active' : 'pending'),
                },
                {
                  label: 'Governance',
                  status: govDone ? 'done' : (cogDone && (flow.busyAction === 'sot-lock' || flow.busyAction === 'approve' || flow.busyAction === 'compile' || flow.busyAction === 'plan-lock') ? 'active' : 'pending'),
                },
                {
                  label: 'Create Repo',
                  status: stepStatus('provision_repo', govDone && isBusy),
                },
                {
                  label: 'Generate Code',
                  status: stepStatus('generate_code', hasSteps ? steps!.includes('provision_repo') : false),
                  subLabel: filesGen ? `${filesGen} files — Architect / Builder / Inspector` : 'Architect / Builder / Inspector',
                },
                {
                  label: 'Commit Code',
                  status: stepStatus('write_files', hasSteps ? steps!.includes('generate_code') : false),
                },
                {
                  label: 'Deploy',
                  status: readyState === 'READY'
                    ? 'done'
                    : readyState === 'ERROR'
                      ? 'error'
                      : stepStatus('deploy', hasSteps ? steps!.includes('write_files') : false),
                  subLabel: readyState === 'READY'
                    ? 'Ready'
                    : readyState === 'ERROR'
                      ? 'Build Error'
                      : hasSteps && steps!.includes('deploy')
                        ? 'Building...'
                        : undefined,
                },
              ];

              return <ProgressBar steps={progressSteps} />;
            })()}
            {hasDeployment && (
              <div className="deployment-links">
                {flow.repositoryUrl && (
                  <a href={flow.repositoryUrl} target="_blank" rel="noopener noreferrer" className="deployment-link repo">
                    <span className="deployment-link-icon">&#x1F4E6;</span>
                    <span>
                      <span className="deployment-link-label">GitHub Repository</span>
                      <span className="deployment-link-url">{flow.repositoryUrl}</span>
                    </span>
                    <span className="deployment-link-arrow">&#x2197;</span>
                  </a>
                )}
                {flow.previewUrl && (
                  <a href={flow.previewUrl} target="_blank" rel="noopener noreferrer" className="deployment-link vercel">
                    <span className="deployment-link-icon">&#x25B2;</span>
                    <span>
                      <span className="deployment-link-label">Vercel Deployment</span>
                      <span className="deployment-link-url">{flow.previewUrl}</span>
                    </span>
                    <span className="deployment-link-arrow">&#x2197;</span>
                  </a>
                )}
              </div>
            )}
          </section>

          {hasFiles && (
            <div className="builder-tabs">
              <button
                className={`tab-btn${flow.activeTab === 'artifacts' ? ' active' : ''}`}
                onClick={() => flow.setActiveTab('artifacts')}
              >
                Artifacts
              </button>
              <button
                className={`tab-btn${flow.activeTab === 'preview' ? ' active' : ''}`}
                onClick={() => flow.setActiveTab('preview')}
              >
                Preview
              </button>
              <button
                className={`tab-btn${flow.activeTab === 'code' ? ' active' : ''}`}
                onClick={() => flow.setActiveTab('code')}
              >
                Code ({flow.generatedFiles.length} files)
              </button>
            </div>
          )}

          <div className="tab-content-container">
            {(!hasFiles || flow.activeTab === 'artifacts') && (
              <ArtifactsPanel
                displayBuildSot={flow.displayBuildSot}
                displayLocks={flow.displayLocks}
                executionPlan={flow.executionPlan}
                taskResult={flow.taskResult}
              />
            )}

            {hasFiles && flow.activeTab === 'preview' && (
              <PreviewPanel
                files={flow.generatedFiles}
                previewUrl={flow.previewUrl}
              />
            )}

            {hasFiles && flow.activeTab === 'code' && (
              <div className="builder-code-layout">
                <FileTree
                  files={flow.generatedFiles}
                  selectedPath={flow.selectedFilePath}
                  onSelect={flow.setSelectedFilePath}
                />
                <CodeEditor
                  files={flow.generatedFiles}
                  selectedPath={flow.selectedFilePath}
                  onContentChange={flow.onFileContentChange}
                />
              </div>
            )}
          </div>

          {hasFiles && (
            <RefinementChat
              disabled={!!flow.busyAction}
              onRefine={flow.onRefine}
              history={flow.refinementHistory}
            />
          )}

          <EventLog items={flow.eventLog} />
        </section>
      </section>
    </Layout>
  );
}
