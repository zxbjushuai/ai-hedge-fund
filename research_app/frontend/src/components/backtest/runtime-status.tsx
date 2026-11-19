import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { simulationApi, type SystemStatus } from '@/services/simulation-api';

function plural(count: number, singular: string, pluralForm = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function timestamp(value: string | null) {
  if (!value) return 'No startup recovery recorded';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? `Last startup check ${value}` : `Last startup check ${parsed.toLocaleString()}`;
}

export function RuntimeStatusPanel({ active, refreshKey }: { active: boolean; refreshKey: number }) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!active) return;
    let current = true;
    setLoading(true);
    setError('');
    simulationApi.getSystemStatus()
      .then(next => { if (current) setStatus(next); })
      .catch(err => { if (current) setError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [active, refreshKey, revision]);

  if (!active) return null;
  const activeSimulations = status ? status.simulations.pending + status.simulations.running + status.simulations.cancelling : 0;
  const recovery = status?.startup_recovery;

  return <section className="runtime-status" aria-labelledby="runtime-status-heading" aria-busy={loading}>
    <div className="runtime-status-heading">
      <div><h2 id="runtime-status-heading">Runtime status</h2><p className="quiet">Startup recovery, simulation counts, and process-local cache jobs.</p></div>
      <Button variant="outline" disabled={loading} onClick={() => setRevision(value => value + 1)}>{loading ? 'Refreshing…' : 'Refresh runtime status'}</Button>
    </div>
    {loading && !status && <p role="status">Loading runtime status…</p>}
    {error && <p role="alert" className="notice error">Runtime status unavailable: {error}<Button variant="ghost" onClick={() => setRevision(value => value + 1)}>Retry runtime status</Button></p>}
    {status && recovery && <dl className="runtime-status-grid">
      <div>
        <dt>Startup recovery</dt>
        <dd>{plural(recovery.orphaned_simulations_recovered, 'simulation')} recovered</dd>
        <p>{recovery.orphaned_simulations_failed} failed · {recovery.orphaned_simulations_cancelled} cancelled · {plural(recovery.orphaned_cache_jobs_failed, 'cache job')} failed</p>
        <p className="quiet">{timestamp(recovery.completed_at)}</p>
      </div>
      <div>
        <dt>Simulation work</dt>
        <dd>{activeSimulations} active · {status.simulations.failed} failed</dd>
        <p>{status.simulations.pending} pending · {status.simulations.running} running · {status.simulations.cancelling} cancelling</p>
        <p className="quiet">{status.simulations.completed} completed · {status.simulations.cancelled} cancelled</p>
      </div>
      <div>
        <dt>Cache jobs</dt>
        <dd>{status.cache_jobs.active} active</dd>
        <p>{status.cache_jobs.total} tracked this process</p>
        <p className="quiet">{status.cache_jobs.by_status.failed} failed · {status.cache_jobs.by_status.partial} partial</p>
      </div>
    </dl>}
  </section>;
}
