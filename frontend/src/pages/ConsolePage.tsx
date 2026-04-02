import { useGovernedFlow } from '../hooks/useGovernedFlow';
import { Layout } from '../components/Layout';
import { ControlsPanel } from '../components/ControlsPanel';
import { RuntimeState } from '../components/RuntimeState';
import { ArtifactsPanel } from '../components/ArtifactsPanel';
import { EventLog } from '../components/EventLog';

export function ConsolePage() {
  const flow = useGovernedFlow();

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
          <ArtifactsPanel
            displayBuildSot={flow.displayBuildSot}
            displayLocks={flow.displayLocks}
            executionPlan={flow.executionPlan}
            taskResult={flow.taskResult}
          />
          <EventLog items={flow.eventLog} />
        </section>
      </section>
    </Layout>
  );
}
