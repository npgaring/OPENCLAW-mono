import { useMemo, useState } from 'react';
import type {
  JsonMap,
  LogLevel,
  OcggIdentity,
  Intent,
  DeployTarget,
  BuildSoTEnvelope,
  BuildSoTGovernanceResult,
  BuildSoTApprovalEnvelope,
  ExecutionPlan,
  ExecutionPlanLockResult,
  TaskSubmitResult,
  EventLogItem,
  PlanChecks,
  StepRow,
} from '../types/governed';
import { asText, csvToArray } from '../utils/format';
import { hasProviderOperation, findBranchValue } from '../utils/plan-checks';
import * as dudex from '../services/dudex';
import * as integration from '../services/integration';

const initialDudexBase = `${window.location.origin}/dude-x`;
const initialIntegrationBase = `${window.location.origin}/openclaw-integration`;
const initialApiToken = (import.meta.env.VITE_INTEGRATION_API_KEY ?? '').trim();
const defaultIdea = [
  'Build a conversion-focused website for Conversion Interactive Agency with Home, Services, Case Studies, and Contact pages.',
  'Primary objective: generate qualified inbound leads.',
  'Secondary objective: establish agency credibility using concrete outcomes, trust signals, and clear process.',
  'The site should guide visitors from awareness to consultation booking with minimal friction.',
].join(' ');
const defaultVoice = [
  'Professional, clear, and modern tone.',
  'Prioritize lead capture and trust signals.',
  'Use strong above-the-fold value proposition and repeated CTA buttons.',
  'Include a contact form with light qualification fields (service needed, budget range, timeline).',
  'Keep copy scannable: concise sections, benefit-led headings, and evidence-backed claims.',
  'Avoid vague marketing language; emphasize measurable outcomes and practical execution.',
].join(' ');
const defaultProjectName = 'TEST CDMBR Launch Site';
const defaultSitePurpose = 'Generate qualified leads and present agency credibility with clear service positioning and measurable proof.';
const defaultAudience = 'founders, marketing managers, local business owners';
const defaultTone = 'professional';
const defaultPages = 'home, services, case studies, contact';
const defaultIntegrations = '';

export function useGovernedFlow() {
  const [dudexBase, setDudexBase] = useState(
    () => localStorage.getItem('oc_dudex_base') || initialDudexBase,
  );
  const [integrationBase, _setIntegrationBase] = useState(
    () => localStorage.getItem('oc_integration_base') || initialIntegrationBase,
  );
  const [apiToken, _setApiToken] = useState(
    () => localStorage.getItem('oc_api_token') || initialApiToken,
  );

  const setIntegrationBase = (v: string) => { localStorage.setItem('oc_integration_base', v); _setIntegrationBase(v); };
  const setApiToken = (v: string) => { localStorage.setItem('oc_api_token', v); _setApiToken(v); };
  const setDudexBaseWrapped = (v: string) => { localStorage.setItem('oc_dudex_base', v); setDudexBase(v); };

  const [identity, setIdentity] = useState<OcggIdentity>('W-OCGG');
  const [intent, setIntent] = useState<Intent>('web-build');
  const [deployTarget, setDeployTarget] = useState<DeployTarget>('preview');
  const [approverId, setApproverId] = useState('ops-01');

  const [idea, setIdea] = useState(defaultIdea);
  const [voice, setVoice] = useState(defaultVoice);
  const [projectName, setProjectName] = useState(defaultProjectName);
  const [sitePurpose, setSitePurpose] = useState(defaultSitePurpose);
  const [audience, setAudience] = useState(defaultAudience);
  const [tone, setTone] = useState(defaultTone);
  const [pages, setPages] = useState(defaultPages);
  const [integrations, setIntegrations] = useState(defaultIntegrations);

  const [traceId, setTraceId] = useState<string | null>(null);
  const [buildSotHash, setBuildSotHash] = useState<string | null>(null);

  const [buildSotEnvelope, setBuildSotEnvelope] = useState<BuildSoTEnvelope | null>(null);
  const [buildSotGovernance, setBuildSotGovernance] = useState<BuildSoTGovernanceResult | null>(null);
  const [buildSotApproval, setBuildSotApproval] = useState<BuildSoTApprovalEnvelope | null>(null);
  const [executionPlan, setExecutionPlan] = useState<ExecutionPlan | null>(null);
  const [executionPlanHash, setExecutionPlanHash] = useState<string | null>(null);
  const [executionLock, setExecutionLock] = useState<ExecutionPlanLockResult | null>(null);
  const [taskResult, setTaskResult] = useState<TaskSubmitResult | null>(null);

  const [eventLog, setEventLog] = useState<EventLogItem[]>([
    { at: new Date().toLocaleTimeString(), level: 'info', message: 'Console ready. Start with "Run Cognitive Mode".' },
  ]);
  const [busyAction, setBusyAction] = useState('');

  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'artifacts' | 'preview' | 'code'>('artifacts');
  const [refinementHistory, setRefinementHistory] = useState<{ role: 'user' | 'system'; text: string }[]>([]);

  const operations = executionPlan?.operations ?? [];

  const planChecks: PlanChecks = useMemo(() => {
    const hasGitHub = hasProviderOperation(operations, 'github') || operations.some((op) => op.type === 'provision_repo');
    const hasVercel = hasProviderOperation(operations, 'vercel') || operations.some((op) => op.type === 'provision_hosting');
    const branch = findBranchValue(operations);
    return { hasGitHub, hasVercel, branch: branch ?? 'n/a' };
  }, [operations]);

  const cognitiveOutcome = buildSotEnvelope?.cognitive_outcome ?? '-';
  const sotLockOutcome = buildSotGovernance?.outcome ?? '-';
  const planLockOutcome = executionLock?.outcome ?? '-';
  const taskStatus = taskResult?.status ?? '-';

  function addLog(message: string, level: LogLevel = 'info') {
    setEventLog((prev) => [{ at: new Date().toLocaleTimeString(), level, message }, ...prev]);
  }

  function buildBriefPayload(): JsonMap {
    return {
      project_name: asText(projectName),
      site_purpose: asText(sitePurpose),
      target_audience: csvToArray(audience),
      desired_tone: asText(tone),
      page_list: csvToArray(pages),
      integrations: csvToArray(integrations),
      deployment_target: deployTarget,
    };
  }

  async function runAction(name: string, fn: () => Promise<void>) {
    try {
      setBusyAction(name);
      await fn();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      addLog(message, 'error');
    } finally {
      setBusyAction('');
    }
  }

  async function onRunCognitiveMode() {
    const payload: JsonMap = {
      idea: asText(idea),
      voice: asText(voice),
      brief: buildBriefPayload(),
      ocgg_identity: identity,
      intent,
      deployment_target: deployTarget,
      trace_id: traceId ?? undefined,
    };
    const data = await dudex.submitRawIntent(dudexBase, apiToken, payload);
    const nextTrace = data.stage_linkage?.trace_id ?? traceId;
    const nextSotHash = data.stage_linkage?.build_sot_hash ?? null;

    setBuildSotEnvelope(data);
    setBuildSotGovernance(null);
    setBuildSotApproval(null);
    setExecutionPlan(null);
    setExecutionPlanHash(null);
    setExecutionLock(null);
    setTaskResult(null);
    setTraceId(nextTrace ?? null);
    setBuildSotHash(nextSotHash);

    addLog(`Build SoT generated. outcome=${data.cognitive_outcome ?? 'n/a'} hash=${nextSotHash ?? 'n/a'}`);
  }

  async function onEvaluateBuildSotLock() {
    if (!buildSotHash) throw new Error('Build SoT hash missing. Run cognitive mode first.');

    const payload: JsonMap = {
      ocgg_identity: identity,
      intent,
      trace_id: traceId ?? undefined,
    };
    const data = await dudex.evaluateGovernance(dudexBase, apiToken, buildSotHash, payload);
    setBuildSotGovernance(data);
    if (data.trace_id) setTraceId(data.trace_id);
    addLog(`Build SoT lock evaluated. outcome=${data.outcome ?? 'n/a'}`);
  }

  async function onApproveBuildSot() {
    if (!buildSotHash) throw new Error('Build SoT hash missing.');

    const payload: JsonMap = {
      decision: 'APPROVE',
      approver_id: asText(approverId) ?? 'ops-01',
      comment: 'Approved from Governed Builder Console (React/TS)',
    };
    const data = await dudex.approveBuildSot(dudexBase, apiToken, buildSotHash, payload);
    setBuildSotApproval(data);
    addLog(`Build SoT approved by ${payload.approver_id as string}`);
  }

  async function onCompileExecutionPlan() {
    if (!buildSotHash) throw new Error('Build SoT hash missing.');

    const data = await dudex.compileExecutionPlan(dudexBase, apiToken, buildSotHash);
    const nextPlanHash = data.stage_linkage?.execution_plan_hash ?? null;
    setExecutionPlan(data);
    setExecutionPlanHash(nextPlanHash);
    setExecutionLock(null);
    setTaskResult(null);
    addLog(`Execution plan compiled. hash=${nextPlanHash ?? 'n/a'}`);
  }

  async function onLockExecutionPlan() {
    if (!executionPlan || !executionPlanHash || !buildSotHash) {
      throw new Error('Execution plan missing. Compile first.');
    }
    const gp = executionPlan.governance_projection ?? {};
    const payload: JsonMap = {
      trace_id: traceId ?? undefined,
      ocgg_identity: identity,
      build_sot_hash: buildSotHash,
      execution_plan_hash: executionPlanHash,
      plan_hash: gp.plan_hash,
      operations,
      deployment_target: deployTarget,
      goal: gp.goal,
      context: gp.context ?? 'Governed Builder Console (React/TS)',
      acceptance_criteria: gp.acceptance_criteria,
    };
    const data = await integration.lockExecutionPlan(integrationBase, apiToken, payload);
    setExecutionLock(data);
    if (data.trace_id) setTraceId(data.trace_id);
    addLog(`Execution plan lock evaluated. outcome=${data.outcome ?? 'n/a'}`);
  }

  async function onSubmitTask() {
    if (!executionPlan || !executionPlanHash || !executionLock?.continuity_id || !buildSotHash) {
      throw new Error('Execution lock continuity id missing. Run execution-plan lock first.');
    }

    const gp = executionPlan.governance_projection ?? {};
    const payload: JsonMap = {
      ocgg_identity: identity,
      trace_id: traceId ?? undefined,
      plan_hash: gp.plan_hash,
      operations,
      deployment_target: deployTarget,
      goal: gp.goal ?? 'Governed website build and deploy',
      context: gp.context ?? 'Governed Builder Console task submission',
      acceptance_criteria: gp.acceptance_criteria,
      build_sot_hash: buildSotHash,
      execution_plan_hash: executionPlanHash,
      v2_continuity_id: executionLock.continuity_id,
      governance_evaluation_id: executionLock.governance_evaluation_id,
      executor_contract: executionPlan.execution_mode ?? 'deterministic_web_v1',
      execution_plan_v2: executionPlan,
    };

    addLog('Pipeline starting: creating repository, generating code, deploying...');
    const data = await integration.submitTask(integrationBase, apiToken, payload);
    setTaskResult(data);

    const execResponse = data.execution_response ?? {};
    const stepsCompleted = (execResponse.steps_completed as string[]) ?? [];
    const filesGenerated = (execResponse.files_generated as number) ?? 0;

    if (stepsCompleted.includes('provision_repo')) addLog('Phase 1 complete: GitHub repository created.');
    if (stepsCompleted.includes('generate_code')) addLog(`Phase 2 complete: ${filesGenerated} files generated via AI.`);
    if (stepsCompleted.includes('write_files')) addLog('Phase 3 complete: code committed to GitHub.');
    if (stepsCompleted.includes('deploy')) addLog('Phase 4 complete: Vercel deployment triggered.');

    addLog(`Task submitted. status=${data.status ?? 'n/a'} execution_id=${data.execution_id ?? 'n/a'}`);
    if (data.deployment_url) addLog(`Deployment URL: ${data.deployment_url}`);
    if (data.repository_url) addLog(`Repository URL: ${data.repository_url}`);
    if (data.deployment_url) {
      setActiveTab('preview');
    }
  }

  function onClearSession() {
    setTraceId(null);
    setBuildSotHash(null);
    setBuildSotEnvelope(null);
    setBuildSotGovernance(null);
    setBuildSotApproval(null);
    setExecutionPlan(null);
    setExecutionPlanHash(null);
    setExecutionLock(null);
    setTaskResult(null);
    setEventLog([{ at: new Date().toLocaleTimeString(), level: 'info', message: 'Session cleared.' }]);
  }

  const generatedFiles = useMemo(() => {
    if (!executionPlan?.operations) return [];
    return (executionPlan.operations as JsonMap[])
      .filter((op) => op.type === 'create_file' || op.type === 'write_config')
      .map((op) => {
        const inputs = (op.inputs ?? {}) as Record<string, string>;
        return { path: inputs.path ?? '', content: inputs.content ?? '' };
      })
      .filter((f) => f.path);
  }, [executionPlan]);

  const execResp = taskResult?.execution_response ?? {};
  const previewUrl = taskResult?.deployment_url
    ?? taskResult?.preview_url
    ?? (execResp.deployment_url as string | undefined)
    ?? (execResp.preview_url as string | undefined)
    ?? null;

  const repositoryUrl = taskResult?.repository_url
    ?? (execResp.repository_url as string | undefined)
    ?? null;

  function onFileContentChange(path: string, newContent: string) {
    if (!executionPlan?.operations) return;
    const ops = [...(executionPlan.operations as JsonMap[])];
    const idx = ops.findIndex(
      (op) => (op.type === 'create_file' || op.type === 'write_config') && ((op.inputs as Record<string, string>)?.path === path),
    );
    if (idx >= 0) {
      const updated = { ...ops[idx], inputs: { ...(ops[idx].inputs as Record<string, string>), content: newContent } };
      ops[idx] = updated;
      setExecutionPlan({ ...executionPlan, operations: ops });
    }
  }

  async function onRefineAsync(message: string) {
    setRefinementHistory((prev) => [...prev, { role: 'user', text: message }]);

    if (!buildSotHash) {
      setRefinementHistory((prev) => [...prev, { role: 'system', text: 'Run cognitive mode first to generate a Build SoT.' }]);
      return;
    }

    try {
      const payload: JsonMap = {
        feedback: message,
        trace_id: traceId ?? undefined,
      };
      const data = await dudex.refineBuildSot(dudexBase, apiToken, buildSotHash, payload);
      const nextHash = data.stage_linkage?.build_sot_hash ?? buildSotHash;

      setBuildSotEnvelope(data);
      setBuildSotHash(nextHash);
      setBuildSotGovernance(null);
      setBuildSotApproval(null);
      setExecutionPlan(null);
      setExecutionPlanHash(null);
      setExecutionLock(null);
      setTaskResult(null);

      setRefinementHistory((prev) => [
        ...prev,
        { role: 'system', text: `Refinement applied. New SoT hash: ${nextHash?.slice(0, 12)}... Re-run steps 2-6 to proceed.` },
      ]);
      addLog(`Refinement applied. hash=${nextHash ?? 'n/a'}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setRefinementHistory((prev) => [...prev, { role: 'system', text: `Error: ${msg}` }]);
      addLog(msg, 'error');
    }
  }

  function onRefine(message: string) {
    runAction('refine', () => onRefineAsync(message));
  }

  const displayBuildSot = buildSotEnvelope?.build_sot ?? buildSotApproval?.build_sot ?? {};
  const displayLocks = {
    build_sot_governance: buildSotGovernance ?? {},
    execution_plan_lock: executionLock ?? {},
  };

  const stepRows: StepRow[] = [
    { name: 'Raw Intent', ready: !!buildSotEnvelope, detail: buildSotHash ?? 'awaiting input' },
    { name: 'Build SoT Lock #1', ready: !!buildSotGovernance, detail: buildSotGovernance?.outcome ?? 'not evaluated' },
    {
      name: 'Build SoT Approval',
      ready: !!buildSotApproval,
      detail:
        typeof buildSotApproval?.build_sot?.approval_status === 'string'
          ? (buildSotApproval.build_sot.approval_status as string)
          : 'not decided',
    },
    { name: 'Compiler Mode', ready: !!executionPlan, detail: executionPlanHash ?? 'not compiled' },
    { name: 'Execution Lock #2', ready: !!executionLock, detail: executionLock?.continuity_id ?? 'not locked' },
    { name: 'Task Dispatch', ready: !!taskResult, detail: taskResult?.execution_id ?? 'not submitted' },
  ];

  return {
    // Connection config
    dudexBase, setDudexBase: setDudexBaseWrapped,
    integrationBase, setIntegrationBase,
    apiToken, setApiToken,

    // Flow parameters
    identity, setIdentity,
    intent, setIntent,
    deployTarget, setDeployTarget,
    approverId, setApproverId,

    // Brief fields
    idea, setIdea,
    voice, setVoice,
    projectName, setProjectName,
    sitePurpose, setSitePurpose,
    audience, setAudience,
    tone, setTone,
    pages, setPages,
    integrations, setIntegrations,

    // Runtime state
    traceId,
    buildSotHash,
    cognitiveOutcome,
    sotLockOutcome,
    planLockOutcome,
    taskStatus,
    planChecks,
    stepRows,
    eventLog,
    busyAction,

    // Artifacts for display
    displayBuildSot,
    displayLocks,
    executionPlan,
    taskResult,

    // Actions
    runAction,
    onRunCognitiveMode,
    onEvaluateBuildSotLock,
    onApproveBuildSot,
    onCompileExecutionPlan,
    onLockExecutionPlan,
    onSubmitTask,
    onClearSession,

    // Builder UI state
    generatedFiles,
    previewUrl,
    repositoryUrl,
    selectedFilePath,
    setSelectedFilePath,
    activeTab,
    setActiveTab,
    onFileContentChange,
    refinementHistory,
    onRefine,
  };
}
