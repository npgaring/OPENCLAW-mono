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

          {hasDeployment && (
            <section className="deployment-results">
              <div className="deployment-header">
                <h3>Deployment Pipeline</h3>
                <span className={`deployment-badge ${flow.taskStatus === 'completed' ? 'success' : 'pending'}`}>
                  {flow.taskStatus === 'completed' ? 'Deployed' : flow.taskStatus}
                </span>
              </div>
              {(() => {
                const execResp = flow.taskResult?.execution_response ?? {};
                const steps = (execResp as Record<string, unknown>).steps_completed as string[] | undefined;
                const filesGen = (execResp as Record<string, unknown>).files_generated as number | undefined;
                return steps && steps.length > 0 ? (
                  <div className="pipeline-phases">
                    <div className={`pipeline-phase ${steps.includes('provision_repo') ? 'done' : ''}`}>
                      <span className="phase-indicator">{steps.includes('provision_repo') ? '\u2713' : '\u2022'}</span>
                      <span>Create Repository</span>
                    </div>
                    <div className={`pipeline-phase ${steps.includes('generate_code') ? 'done' : ''}`}>
                      <span className="phase-indicator">{steps.includes('generate_code') ? '\u2713' : '\u2022'}</span>
                      <span>Generate Code{filesGen ? ` (${filesGen} files)` : ''}</span>
                    </div>
                    <div className={`pipeline-phase ${steps.includes('write_files') ? 'done' : ''}`}>
                      <span className="phase-indicator">{steps.includes('write_files') ? '\u2713' : '\u2022'}</span>
                      <span>Commit to GitHub</span>
                    </div>
                    <div className={`pipeline-phase ${steps.includes('deploy') ? 'done' : ''}`}>
                      <span className="phase-indicator">{steps.includes('deploy') ? '\u2713' : '\u2022'}</span>
                      <span>Deploy to Vercel</span>
                    </div>
                  </div>
                ) : null;
              })()}
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
            </section>
          )}

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
