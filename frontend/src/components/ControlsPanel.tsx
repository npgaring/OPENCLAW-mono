import type { OcggIdentity, Intent, DeployTarget } from '../types/governed';

interface ControlsPanelProps {
  dudexBase: string;
  onDudexBaseChange: (v: string) => void;
  integrationBase: string;
  onIntegrationBaseChange: (v: string) => void;
  apiToken: string;
  onApiTokenChange: (v: string) => void;

  identity: OcggIdentity;
  onIdentityChange: (v: OcggIdentity) => void;
  intent: Intent;
  onIntentChange: (v: Intent) => void;
  deployTarget: DeployTarget;
  onDeployTargetChange: (v: DeployTarget) => void;
  approverId: string;
  onApproverIdChange: (v: string) => void;

  idea: string;
  onIdeaChange: (v: string) => void;
  voice: string;
  onVoiceChange: (v: string) => void;
  projectName: string;
  onProjectNameChange: (v: string) => void;
  sitePurpose: string;
  onSitePurposeChange: (v: string) => void;
  audience: string;
  onAudienceChange: (v: string) => void;
  tone: string;
  onToneChange: (v: string) => void;
  pages: string;
  onPagesChange: (v: string) => void;
  integrations: string;
  onIntegrationsChange: (v: string) => void;

  busyAction: string;
  onRunCognitive: () => void;
  onEvaluateSotLock: () => void;
  onApprove: () => void;
  onCompile: () => void;
  onLockPlan: () => void;
  onSubmitTask: () => void;
  onClear: () => void;
}

export function ControlsPanel(props: ControlsPanelProps) {
  const busy = !!props.busyAction;

  return (
    <section className="panel">
      <div className="head">
        <h2>Controls</h2>
      </div>
      <div className="body">
        <div className="grid">
          <div>
            <label htmlFor="dudex-base">DUDE-X Base URL</label>
            <input id="dudex-base" value={props.dudexBase} onChange={(e) => props.onDudexBaseChange(e.target.value)} />
          </div>
          <div>
            <label htmlFor="integration-base">OpenClaw Integration Base URL</label>
            <input id="integration-base" value={props.integrationBase} onChange={(e) => props.onIntegrationBaseChange(e.target.value)} />
          </div>
          <div>
            <label htmlFor="api-token">Integration API Token (Bearer)</label>
            <input
              id="api-token"
              type="password"
              placeholder="INTEGRATION_API_KEY"
              value={props.apiToken}
              onChange={(e) => props.onApiTokenChange(e.target.value)}
            />
          </div>
        </div>

        <div className="divider" />

        <div className="grid two">
          <div>
            <label htmlFor="identity">OCGG Identity</label>
            <select id="identity" value={props.identity} onChange={(e) => props.onIdentityChange(e.target.value as OcggIdentity)}>
              <option value="W-OCGG">W-OCGG</option>
              <option value="R-OCGG">R-OCGG</option>
            </select>
          </div>
          <div>
            <label htmlFor="intent">Intent</label>
            <select id="intent" value={props.intent} onChange={(e) => props.onIntentChange(e.target.value as Intent)}>
              <option value="web-build">web-build</option>
              <option value="web-maintenance">web-maintenance</option>
              <option value="recruiting-update">recruiting-update</option>
            </select>
          </div>
          <div>
            <label htmlFor="deploy-target">Deployment Target</label>
            <select id="deploy-target" value={props.deployTarget} onChange={(e) => props.onDeployTargetChange(e.target.value as DeployTarget)}>
              <option value="preview">preview</option>
              <option value="production">production</option>
            </select>
          </div>
          <div>
            <label htmlFor="approver-id">Approver ID</label>
            <input id="approver-id" value={props.approverId} onChange={(e) => props.onApproverIdChange(e.target.value)} />
          </div>
        </div>

        <div>
          <label htmlFor="idea">Idea / Brief</label>
          <textarea
            id="idea"
            value={props.idea}
            onChange={(e) => props.onIdeaChange(e.target.value)}
            placeholder="Build a conversion-focused website with home, pricing, and contact pages."
          />
        </div>
        <div>
          <label htmlFor="voice">Voice Notes / Constraints</label>
          <textarea
            id="voice"
            value={props.voice}
            onChange={(e) => props.onVoiceChange(e.target.value)}
            placeholder="Professional tone, local patient audience, include analytics and contact form."
          />
        </div>

        <div className="grid two">
          <div>
            <label htmlFor="project-name">Project Name</label>
            <input id="project-name" value={props.projectName} onChange={(e) => props.onProjectNameChange(e.target.value)} />
          </div>
          <div>
            <label htmlFor="site-purpose">Site Purpose</label>
            <input id="site-purpose" value={props.sitePurpose} onChange={(e) => props.onSitePurposeChange(e.target.value)} />
          </div>
          <div>
            <label htmlFor="audience">Target Audience (comma-separated)</label>
            <input id="audience" value={props.audience} onChange={(e) => props.onAudienceChange(e.target.value)} />
          </div>
          <div>
            <label htmlFor="tone">Tone</label>
            <input id="tone" value={props.tone} onChange={(e) => props.onToneChange(e.target.value)} />
          </div>
          <div>
            <label htmlFor="pages">Pages (comma-separated)</label>
            <input id="pages" value={props.pages} onChange={(e) => props.onPagesChange(e.target.value)} />
          </div>
          <div>
            <label htmlFor="integrations">Integrations (comma-separated)</label>
            <input id="integrations" value={props.integrations} onChange={(e) => props.onIntegrationsChange(e.target.value)} />
          </div>
        </div>

        <div className="actions">
          <button className="primary" disabled={busy} onClick={props.onRunCognitive}>
            1) Run Cognitive Mode
          </button>
          <button className="secondary" disabled={busy} onClick={props.onEvaluateSotLock}>
            2) Evaluate Build SoT Lock
          </button>
          <button className="secondary" disabled={busy} onClick={props.onApprove}>
            3) Approve Build SoT
          </button>
          <button className="secondary" disabled={busy} onClick={props.onCompile}>
            4) Compile Execution Plan
          </button>
          <button className="secondary" disabled={busy} onClick={props.onLockPlan}>
            5) Lock Execution Plan
          </button>
          <button className="primary" disabled={busy} onClick={props.onSubmitTask}>
            6) Submit Task
          </button>
          <button className="danger" disabled={busy} onClick={props.onClear}>
            Clear Session
          </button>
        </div>
      </div>
    </section>
  );
}
