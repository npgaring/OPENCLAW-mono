import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchProjects, retriggerDeployment, type ProjectDeployment } from '../services/projects';

function getBase() {
  return localStorage.getItem('oc_integration_base')
    || (import.meta.env.VITE_INTEGRATION_BASE_URL ?? `${window.location.origin}/openclaw-integration`).toString().trim();
}
function getToken() {
  return localStorage.getItem('oc_api_token')
    || (import.meta.env.VITE_INTEGRATION_API_KEY ?? '').toString().trim();
}

function statusBadge(status: string, readyState: string | null) {
  const effective = readyState || status;
  const lower = effective.toLowerCase();
  if (lower === 'ready' || lower === 'success') return <span className="badge badge-success">Ready</span>;
  if (lower === 'error' || lower === 'needs_review') return <span className="badge badge-error">Error</span>;
  if (lower === 'building' || lower === 'pending') return <span className="badge badge-building">Building</span>;
  return <span className="badge badge-unknown">{effective}</span>;
}

export function ProjectsPage() {
  const [deployments, setDeployments] = useState<ProjectDeployment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expandedLogs, setExpandedLogs] = useState<Set<string>>(new Set());
  const [retriggering, setRetriggering] = useState<Set<string>>(new Set());
  const [showConfig, setShowConfig] = useState(false);
  const [cfgBase, setCfgBase] = useState(getBase);
  const [cfgToken, setCfgToken] = useState(getToken);

  const saveConfig = () => {
    localStorage.setItem('oc_integration_base', cfgBase);
    localStorage.setItem('oc_api_token', cfgToken);
    setShowConfig(false);
    load();
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchProjects(getBase(), getToken(), 100, 0);
      setDeployments(data);
    } catch (e: any) {
      setError(e.message || 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleLogs = (id: string) => {
    setExpandedLogs(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleRetrigger = async (id: string) => {
    setRetriggering(prev => new Set(prev).add(id));
    try {
      await retriggerDeployment(getBase(), getToken(), id);
      await load();
    } catch (e: any) {
      alert(`Retrigger failed: ${e.message}`);
    } finally {
      setRetriggering(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  return (
    <main className="page">
      <section className="hero">
        <div className="eyebrow">OpenClaw Dual Engine</div>
        <h1>Project History</h1>
        <p>View all past deployments, inspect build logs, and retrigger failed builds.</p>
      </section>

      <section className="projects-container">
        <div className="projects-toolbar">
          <Link to="/" className="btn-back">&larr; Console</Link>
          <div className="toolbar-right">
            <button className="btn-action" onClick={() => setShowConfig(s => !s)}>
              {showConfig ? 'Hide Settings' : 'Settings'}
            </button>
            <button className="btn-refresh" onClick={load} disabled={loading}>
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>

        {showConfig && (
          <div className="projects-config">
            <label className="config-field">
              <span>Integration Base URL</span>
              <input value={cfgBase} onChange={e => setCfgBase(e.target.value)} placeholder="http://localhost:8012/openclaw-integration" />
            </label>
            <label className="config-field">
              <span>API Token</span>
              <input value={cfgToken} onChange={e => setCfgToken(e.target.value)} type="password" placeholder="Bearer token" />
            </label>
            <button className="btn-refresh" onClick={saveConfig}>Save &amp; Reload</button>
          </div>
        )}

        {error && <div className="projects-error">{error}
          {!getToken() && <span> — No API token configured. Click <strong>Settings</strong> above to set your integration URL and token.</span>}
        </div>}

        {!loading && deployments.length === 0 && !error && (
          <div className="projects-empty">No deployments found. Build your first project from the console.</div>
        )}

        <div className="projects-table-wrap">
          <table className="projects-table">
            <thead>
              <tr>
                <th>Project</th>
                <th>Status</th>
                <th>Deploy URL</th>
                <th>Repository</th>
                <th>Created</th>
                <th>Fixes</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {deployments.map(d => (
                <tr key={d.id} className={expandedLogs.has(d.id) ? 'row-expanded' : ''}>
                  <td className="project-name-cell">{d.project_name}</td>
                  <td>{statusBadge(d.status, d.vercel_ready_state)}</td>
                  <td>
                    {d.vercel_deployment_url ? (
                      <a href={d.vercel_deployment_url} target="_blank" rel="noopener noreferrer" className="table-link">
                        Open ↗
                      </a>
                    ) : '—'}
                  </td>
                  <td>
                    {d.github_repo_url ? (
                      <a href={d.github_repo_url} target="_blank" rel="noopener noreferrer" className="table-link">
                        Repo ↗
                      </a>
                    ) : '—'}
                  </td>
                  <td className="date-cell">{d.created_at ? new Date(d.created_at).toLocaleString() : '—'}</td>
                  <td className="fixes-cell">{d.fix_attempts || 0}</td>
                  <td className="actions-cell">
                    {d.build_logs && (
                      <button className="btn-action btn-logs" onClick={() => toggleLogs(d.id)}>
                        {expandedLogs.has(d.id) ? 'Hide Logs' : 'View Logs'}
                      </button>
                    )}
                    <button
                      className="btn-action btn-retrigger"
                      onClick={() => handleRetrigger(d.id)}
                      disabled={retriggering.has(d.id)}
                    >
                      {retriggering.has(d.id) ? 'Triggering...' : 'Retrigger'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {deployments.filter(d => expandedLogs.has(d.id) && d.build_logs).map(d => (
          <div key={`logs-${d.id}`} className="build-logs-panel">
            <div className="build-logs-header">
              <span>Build Logs — {d.project_name}</span>
              <button className="btn-close-logs" onClick={() => toggleLogs(d.id)}>&times;</button>
            </div>
            <pre className="build-logs-content">{d.build_logs}</pre>
          </div>
        ))}
      </section>
    </main>
  );
}
