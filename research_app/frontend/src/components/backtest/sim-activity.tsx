import type { SimStatus } from '@/services/simulation-api';

export function SimActivityView({ status }: { status?: SimStatus }) {
  const activity = status?.activity;
  if (!activity?.available) return <p className="quiet">Live activity unavailable. After a service restart, a saved running status does not mean requests are still active. This view does not resume the simulation.</p>;
  return <div>
    <p>Stage: {activity.stage} · Signal date: {activity.signal_date || '—'} · Execution date: {activity.execution_date || '—'}</p>
    <p>Concurrency: {activity.concurrency} · Pending tasks: {activity.queued} · Last update: {activity.updated_at ? new Date(activity.updated_at).toLocaleTimeString() : '—'}</p>
    {activity.error && <p role="alert">{activity.error}</p>}
    <div className="table-scroll"><table className="research-table"><thead><tr><th>Ticker</th><th>Analyst</th><th>Stage</th><th>Elapsed</th></tr></thead><tbody>
      {activity.active?.map(call => <tr key={call.call_id}><td>{call.ticker}</td><td>{call.persona}</td><td>{call.stage?.replace(/_/g, ' ') || 'Preparing'}</td><td>{call.elapsed_seconds}s</td></tr>)}
    </tbody></table></div>
    <p className="quiet">Long elapsed time means a request or capacity wait is ongoing, not necessarily a failed simulation.</p>
    <dl className="review-metrics">{['refresh_success', 'refresh_failure', 'opinion_reused', 'insufficient_data', 'cache_hit', 'http_attempt', 'http_retries'].map(key => <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd>{activity.counts?.[key] || 0}</dd></div>)}</dl>
    <details><summary>Recent activity</summary><ul>{activity.recent?.slice().reverse().map((event, index) => <li key={index}>{String(event.timestamp)} · {String(event.event)} {String(event.ticker || '')} {String(event.persona || '')} {String(event.category || '')}</li>)}</ul></details>
  </div>;
}
