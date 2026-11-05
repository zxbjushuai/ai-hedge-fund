import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { simulationApi, type CacheItem, type LlmConnectionOption, type SimPreflight, type SimResult, type SimRunRequest, type SimRunSummary, type SimStatus } from '@/services/simulation-api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cacheDetails } from '@/lib/cache-details';
import { analyzeCoverage, benchmarkDates, commonCoverage, type DetailMap } from '@/lib/simulation-coverage';
import { CachedUniverseSelector } from './cached-universe-selector';
import { CoverageTimeline } from './coverage-timeline';
import { SimResults } from './sim-results';
import { SimActivityView } from './sim-activity';
import { isVisibleLlmConnection } from '@/lib/llm-connection-policy';

export type DataIntent = { tickers: string[]; benchmark: string; start: string; end: string; id: number };
function message(error: unknown) {
  const detail = (error as { detail?: { errors?: string[] } })?.detail;
  return detail?.errors?.join('\n') || (error instanceof Error ? error.message : String(error));
}

export function SimulationWorkspace({ revision, onRefresh, onData, onProviders, active }: {
  revision: number; onRefresh: () => void; onData: (intent: DataIntent) => void; onProviders: () => void; active: boolean;
}) {
  const [tab, setTab] = useState<'new' | 'running' | 'history'>('new');
  const [tickers, setTickers] = useState<string[]>([]);
  const [benchmark, setBenchmark] = useState('SPY');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [capital, setCapital] = useState('100000');
  const [concurrency, setConcurrency] = useState(4);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const runningHeading = useRef<HTMLHeadingElement>(null);
  const [inventory, setInventory] = useState<Record<string, CacheItem>>({});
  const [inventoryError, setInventoryError] = useState('');
  const [inventoryLoading, setInventoryLoading] = useState(true);
  const [providers, setProviders] = useState<LlmConnectionOption[]>([]);
  const [connection, setConnection] = useState('');
  const [model, setModel] = useState('');
  const [providerError, setProviderError] = useState('');
  const [providerRevision, setProviderRevision] = useState(0);
  const [details, setDetails] = useState<DetailMap>({});
  const [detailErrors, setDetailErrors] = useState<string[]>([]);
  const [loaded, setLoaded] = useState({ key: '', count: 0 });
  const [review, setReview] = useState<{ key: string; result: SimPreflight; request: SimRunRequest } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [run, setRun] = useState<{ id: number; status?: SimStatus } | null>(() => {
    try { const id = Number(localStorage.getItem('simulation.activeRun')); return Number.isInteger(id) && id > 0 ? { id } : null; } catch { return null; }
  });
  const [pollError, setPollError] = useState('');
  const [pollRevision, setPollRevision] = useState(0);
  const [runs, setRuns] = useState<SimRunSummary[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [historyRevision, setHistoryRevision] = useState(0);
  const [result, setResult] = useState<SimResult | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [resultError, setResultError] = useState('');
  const [resultLoading, setResultLoading] = useState(false);
  const resultSequence = useRef(0);
  const dateTouched = useRef(false);
  const initializedDates = useRef(false);
  const requestLock = useRef(false);
  const selection = JSON.stringify([...new Set([...tickers, benchmark].filter(Boolean))]);
  const detailKey = `${revision}:${selection}`;
  const detailsReady = loaded.key === detailKey && loaded.count === JSON.parse(selection).length && !detailErrors.length;
  const request = useMemo<SimRunRequest>(() => ({ tickers, benchmark, start_date: start, end_date: end, initial_capital: Number(capital), llm_connection_id: Number(connection), model }), [tickers, benchmark, start, end, capital, connection, model]);
  const configKey = JSON.stringify([request, revision, providers]);
  const latestKey = useRef(configKey);
  latestKey.current = configKey;
  const analysis = useMemo(() => analyzeCoverage(tickers, benchmark, details, { start, end }), [tickers, benchmark, details, start, end]);
  const running = !!run && (!run.status || ['pending', 'running'].includes(run.status.status));
  const locked = running || busy;

  useEffect(() => { setReview(null); setAcknowledged(false); setError(''); }, [configKey]);
  useEffect(() => {
    let current = true;
    setInventoryLoading(true); setInventoryError('');
    simulationApi.listCache().then(data => { if (current) setInventory(data.cached); }).catch(err => { if (current) setInventoryError(message(err)); }).finally(() => { if (current) setInventoryLoading(false); });
    return () => { current = false; };
  }, [revision]);
  useEffect(() => {
    if (!active) return;
    let current = true;
    setProviderError('');
    simulationApi.listLlmOptions().then(data => { if (current) setProviders(data.providers.filter(isVisibleLlmConnection)); }).catch(err => { if (current) { setProviders([]); setProviderError(message(err)); } });
    return () => { current = false; };
  }, [active, providerRevision]);
  useEffect(() => {
    let current = true;
    const symbols: string[] = JSON.parse(selection);
    setDetails({}); setDetailErrors([]); setLoaded({ key: detailKey, count: 0 });
    symbols.forEach(ticker => { cacheDetails.get(ticker).then(detail => {
      if (current) setDetails(old => ({ ...old, [ticker]: detail }));
    }).catch(err => { if (current) setDetailErrors(old => [...old, `${ticker}: ${message(err)}`]); }).finally(() => {
      if (current) setLoaded(old => ({ key: detailKey, count: old.count + 1 }));
    }); });
    return () => { current = false; };
  }, [selection, detailKey]);
  useEffect(() => {
    if (!detailsReady || initializedDates.current || dateTouched.current) return;
    const common = commonCoverage(tickers, benchmark, details);
    if (common) { setStart(common.start); setEnd(common.end); initializedDates.current = true; }
  }, [detailsReady, tickers, benchmark, details]);
  useEffect(() => {
    let current = true;
    simulationApi.listSimRuns().then(data => { if (current) { setRuns(data.runs); setHistoryError(''); } }).catch(err => { if (current) setHistoryError(message(err)); });
    return () => { current = false; };
  }, [historyRevision]);
  const viewResult = useCallback(async (id: number) => {
    const sequence = ++resultSequence.current;
    setViewing(id); setResult(null); setResultError(''); setResultLoading(true);
    try { const next = await simulationApi.getSimResult(id); if (sequence === resultSequence.current) setResult(next); }
    catch (err) { if (sequence === resultSequence.current) setResultError(message(err)); }
    finally { if (sequence === resultSequence.current) setResultLoading(false); }
  }, []);
  const runId = run?.id;
  useEffect(() => {
    if (!runId || !running) return;
    let current = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const status = await simulationApi.getSimStatus(runId!);
        if (!current) return;
        setRun({ id: runId!, status }); setPollError('');
        if (status.status === 'completed' || status.status === 'failed') { setHistoryRevision(value => value + 1); return; }
        timer = setTimeout(poll, 2000);
      } catch (err) { if (current) setPollError(message(err)); }
    }
    void poll();
    return () => { current = false; clearTimeout(timer); };
  }, [runId, running, pollRevision]);

  const selectedProvider = providers.find(item => String(item.id) === connection);
  const availableModel = selectedProvider?.models.some(item => item.model_id === model);
  const missing = tickers.filter(ticker => !inventory[ticker]?.prices?.count);
  const formErrors = [
    ...analysis.errors,
    ...(!Number.isFinite(Number(capital)) || Number(capital) <= 0 ? ['Initial capital must be a positive number.'] : []),
    ...(!availableModel ? ['Select an available connection and model.'] : []),
    ...(missing.length ? [`Missing price cache: ${missing.join(', ')}.`] : []),
  ];
  const canReview = detailsReady && !inventoryLoading && !inventoryError && !formErrors.length && !locked;
  const openData = () => onData({ tickers, benchmark, start, end, id: Date.now() });
  async function prepare() {
    if (!canReview || requestLock.current) return;
    requestLock.current = true; setBusy(true); setReview(null); setError('');
    const key = configKey;
    try { const checked = await simulationApi.preflightSim(request); if (latestKey.current === key) { setReview({ key, result: checked, request }); setAcknowledged(false); } }
    catch (err) { if (latestKey.current === key) setError(message(err)); }
    finally { requestLock.current = false; setBusy(false); }
  }
  const warnings = [...new Set([...analysis.warnings, ...(review?.result.warnings ?? [])])];
  async function confirm() {
    if (!review || review.key !== configKey || requestLock.current || running || !validConcurrency || (warnings.length > 0 && !acknowledged)) return;
    requestLock.current = true; setBusy(true); setError('');
    try { const response = await simulationApi.runSim({ ...review.request, llm_concurrency: concurrency, confirm_cost: true }); setRun({ id: response.sim_id }); setTab('running'); setReview(null); setHistoryRevision(value => value + 1); }
    catch (err) { setError(`${message(err)} If the connection was lost, check History before submitting again; the server may have accepted the run.`); setReview(null); setHistoryRevision(value => value + 1); }
    finally { requestLock.current = false; setBusy(false); }
  }
  useEffect(() => {
    const heading = tab === 'running' ? runningHeading.current : review ? reviewHeading.current : null;
    if (heading) {
      heading.focus({ preventScroll: true });
      heading.scrollIntoView?.({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    }
  }, [review, tab]);
  useEffect(() => {
    if (runId) { try { localStorage.setItem('simulation.activeRun', String(runId)); } catch { /* Storage may be disabled. */ } }
  }, [runId]);
  const validConcurrency = Number.isInteger(concurrency) && concurrency >= 1 && concurrency <= 8;
  const benchmarkDays = benchmarkDates(details[benchmark]);
  return <div className="simulation-workspace">
    <div className="page-heading"><div><h1>Simulation</h1><p>Build an experiment from the data you have.</p></div><div className="segmented" aria-label="Simulation views"><button aria-pressed={tab === 'new'} onClick={() => setTab('new')}>New simulation</button><button aria-pressed={tab === 'running'} onClick={() => setTab('running')}>Running</button><button aria-pressed={tab === 'history'} onClick={() => { setTab('history'); setHistoryRevision(value => value + 1); }}>History</button></div></div>
    <section hidden={tab !== 'running'}><h2 ref={runningHeading} tabIndex={-1}>Running simulation</h2>{!run && <p>No simulation selected. Start a simulation or track one from History.</p>}{run && <section className="run-banner" aria-live="polite"><div><strong>Simulation #{run.id}: {run.status?.status ?? 'starting'}</strong><p>{run.status ? `${run.status.current_day} / ${run.status.total_days} days` : 'Waiting for status…'}</p>{run.status?.error_message && <p role="alert">{run.status.error_message}</p>}</div>{running && <progress aria-label="Simulation progress" value={run.status?.current_day ?? 0} max={run.status?.total_days || 1} />}{run.status && <Button onClick={() => { setTab('history'); void viewResult(run.id); }}>View result</Button>}{pollError && <div role="alert">Status unavailable: {pollError}<Button variant="outline" onClick={() => setPollRevision(value => value + 1)}>Retry status</Button></div>}</section>}{run && <><p>Estimated model calls: {run.status?.execution_config?.preflight?.estimated_llm_calls ?? 'Not recorded'}. Retries can exceed this estimate.</p><SimActivityView status={run.status} /></>}</section>
    <div hidden={tab !== 'new'}>
      <div className="simulation-grid"><div className="simulation-main">
        {inventoryError && <p role="alert" className="notice error">{inventoryError}</p>}
        <CachedUniverseSelector selected={tickers} onChange={setTickers} inventory={inventory} revision={revision} disabled={locked} onData={openData} />
        <div className="coverage-status"><span>{detailsReady ? 'Coverage loaded' : `Checking coverage: ${loaded.key === detailKey ? loaded.count : 0} / ${JSON.parse(selection).length}`}</span><Button variant="ghost" disabled={locked} onClick={onRefresh}>Refresh cached data</Button></div>
        {detailErrors.length > 0 && <div role="alert" className="notice error">{detailErrors.map(item => <p key={item}>{item}</p>)}<Button variant="outline" disabled={locked} onClick={onRefresh}>Retry coverage</Button><Button variant="ghost" onClick={openData}>Prepare data</Button></div>}
        {detailsReady && <CoverageTimeline tickers={tickers} benchmark={benchmark} details={details} range={{ start, end }} disabled={locked} onCommon={() => { if (analysis.common) { dateTouched.current = true; setStart(analysis.common.start); setEnd(analysis.common.end); } }} />}
      </div><aside className="configuration-panel"><h2>Run configuration</h2><p className="quiet">{tickers.length} securities selected</p>
        <fieldset disabled={locked} className="config-fields"><label>Benchmark<input list="cached-benchmarks" value={benchmark} onChange={e => setBenchmark(e.target.value.trim().toUpperCase())} /></label><datalist id="cached-benchmarks">{Object.entries(inventory).filter(([, item]) => item.prices?.count).map(([ticker]) => <option key={ticker} value={ticker} />)}</datalist><p className="quiet">Trading calendar and total-return comparison. Not traded unless selected.</p>
          <label>Start date<Input type="date" min={benchmarkDays[0]} max={benchmarkDays.at(-1)} value={start} onChange={e => { dateTouched.current = true; setStart(e.target.value); }} /></label>
          <label>End date<Input type="date" min={benchmarkDays[0]} max={benchmarkDays.at(-1)} value={end} onChange={e => { dateTouched.current = true; setEnd(e.target.value); }} /></label>
          <label>Initial capital (USD)<Input type="number" min="0.01" step="any" value={capital} onChange={e => setCapital(e.target.value)} /></label>
          <label>Connection<select value={connection} onChange={e => { setConnection(e.target.value); setModel(''); }}><option value="">Choose a connection</option>{providers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Model<select value={model} disabled={!selectedProvider || locked} onChange={e => setModel(e.target.value)}><option value="">Choose a model</option>{selectedProvider?.models.map(item => <option key={item.model_id} value={item.model_id}>{item.display_name} ({item.model_id})</option>)}</select></label>
        </fieldset>
        {providerError && <p className="notice error" role="alert">{providerError}<Button variant="ghost" onClick={() => setProviderRevision(value => value + 1)}>Retry connections</Button></p>}
        {!availableModel && <Button variant="ghost" onClick={onProviders}>Manage providers</Button>}
        {detailsReady && tickers.length > 0 && formErrors.length > 0 && <ul className="notice warning">{formErrors.map(item => <li key={item}>{item}</li>)}</ul>}
        <Button className="w-full" disabled={!canReview} onClick={() => void prepare()}>{busy ? 'Checking…' : 'Review simulation'}</Button><p className="quiet">Review does not start model inference. Confirm on the next panel to run.</p>
      </aside></div>
      {error && <p className="notice error whitespace-pre-wrap" role="alert">{error}</p>}
      {review && review.key === configKey && <section className="review-panel" aria-labelledby="review-heading"><h2 id="review-heading" ref={reviewHeading} tabIndex={-1}>Review simulation</h2><p>{review.request.tickers.join(', ')} · {start} – {end} · ${Number(capital).toLocaleString()}</p><dl className="review-metrics"><div><dt>Estimated model calls</dt><dd>{review.result.estimated_llm_calls}</dd></div><div><dt>Refresh events</dt><dd>{review.result.estimated_refresh_events}</dd></div><div><dt>Trading days</dt><dd>{review.result.trading_days}</dd></div></dl><p>{selectedProvider?.name} / {review.result.model} · Benchmark {review.result.benchmark}</p><p>Strategies: {review.result.enabled_models.join(', ') || 'None'}</p><p>Refresh policy: {review.result.persona_refresh_policy.valuation_change_pct}% price change / {review.result.persona_refresh_policy.max_age_days} days.</p><p>Events: {Object.entries(review.result.event_reason_counts).map(([name, count]) => `${name}: ${count}`).join(', ')}</p><p className="quiet">Event-schedule upper bound; prompt cache may reduce actual calls. Preflight is not a guarantee of completion.</p>
        {warnings.length > 0 && <><ul className="notice warning">{warnings.map(item => <li key={item}>{item}</li>)}</ul><label className="check-label"><input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)} /> I understand the data and strategy warnings, including possible valuation failure.</label></>}
        <label>Model concurrency<Input type="number" min={1} max={8} step={1} value={concurrency} disabled={busy} onChange={event => setConcurrency(Number(event.target.value))} /></label><p className="quiet">1–8 simultaneous requests. Higher concurrency may trigger provider rate limits. Pending submission is bounded to twice this setting; the server also limits total in-flight requests to 8.</p>{!validConcurrency && <p role="alert">Enter an integer from 1 to 8.</p>}
        <div className="toolbar"><Button disabled={busy || running || !validConcurrency || (warnings.length > 0 && !acknowledged)} onClick={() => void confirm()}>Confirm and run</Button><Button variant="ghost" disabled={busy} onClick={() => setReview(null)}>Back to configuration</Button></div>
      </section>}
    </div>
    <section hidden={tab !== 'history'} className="history-section"><div className="section-heading"><h2>Simulation history</h2><Button variant="outline" onClick={() => setHistoryRevision(value => value + 1)}>Refresh history</Button></div>{historyError && <p role="alert" className="notice error">{historyError}</p>}
      <div className="table-scroll"><table className="research-table"><thead><tr><th>Run</th><th>Status</th><th>Period / securities</th><th>Connection / model</th><th>Benchmark</th><th>Final NAV</th></tr></thead><tbody>{!runs.length && <tr><td colSpan={6}>No saved simulations yet.</td></tr>}{runs.map(item => <tr key={item.id} data-selected={viewing === item.id}><td><button className="text-link" onClick={() => void viewResult(item.id)}>{item.name || `Sim #${item.id}`}</button></td><td>{item.status}{['running', 'pending'].includes(item.status) && !running && <Button variant="ghost" onClick={() => { setRun({ id: item.id }); setTab('running'); setPollRevision(value => value + 1); }}>Track</Button>}{item.error_message && <p className="notice error">{item.error_message}</p>}</td><td>{item.start_date} – {item.end_date}<span className="cell-secondary">{item.tickers.join(', ')}</span></td><td>{item.llm_connection_name || item.provider || 'N/A'}<span className="cell-secondary">{item.model || 'N/A'}</span></td><td>{item.benchmark || 'N/A'}</td><td>{item.final_nav == null ? '—' : item.final_nav.toLocaleString(undefined, { style: 'currency', currency: 'USD' })}</td></tr>)}</tbody></table></div>
      {resultLoading && <p role="status">Loading result #{viewing}…</p>}{resultError && <p role="alert" className="notice error">{resultError}<Button variant="outline" onClick={() => viewing && void viewResult(viewing)}>Retry result</Button></p>}{result && <div className="result-panel"><h2>Simulation #{viewing}</h2><SimResults result={result} /></div>}
    </section>
  </div>;
}
