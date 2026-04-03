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
