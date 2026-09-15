import { simulationApi } from '@/services/simulation-api';
import type { SimResult, SimRunSummary } from '@/services/simulation-api';
import type { LlmConnectionOption } from '@/services/simulation-api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { Play, RefreshCw } from 'lucide-react';
import { useEffect, useState, useCallback, useRef } from 'react';
import { SimResults } from './sim-results';

const dateDaysAgo = (days: number) =>
  new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : String(error);

export function SimulationPanel() {
  const [tickers, setTickers] = useState('AAPL,MSFT');
  const [benchmark, setBenchmark] = useState('SPY');
  const [startDate, setStartDate] = useState(() => dateDaysAgo(45));
  const [endDate, setEndDate] = useState(() => dateDaysAgo(1));
  const [capital, setCapital] = useState('100000');
  const [llmProviders, setLlmProviders] = useState<LlmConnectionOption[]>([]);
  const [llmConnectionId, setLlmConnectionId] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [running, setRunning] = useState(false);
  const [simId, setSimId] = useState<number | null>(null);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [message, setMessage] = useState('');
  const [results, setResults] = useState<SimResult | null>(null);
  const [runList, setRunList] = useState<SimRunSummary[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [viewingId, setViewingId] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadRunList = useCallback(async () => {
    setLoadingList(true);
    try {
      const data = await simulationApi.listSimRuns();
      setRunList(data.runs || []);
    } catch { /* ignore */ }
    finally { setLoadingList(false); }
  }, []);

  useEffect(() => { loadRunList(); }, [loadRunList]);

  useEffect(() => {
    simulationApi.listLlmOptions().then(data => {
      setLlmProviders(data.providers);
      const provider = data.providers.find(item => item.models.length);
      const model = provider?.models[0];
      if (provider && model) {
        setLlmConnectionId(String(provider.id));
        setLlmModel(model.model_id);
      }
    }).catch(error => setMessage('Failed to load configured LLM providers: ' + errorMessage(error)));
  }, []);

  const selectedProvider = llmProviders.find(provider => String(provider.id) === llmConnectionId);

  const handleRun = async () => {
    const list = tickers.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
    if (!list.length) return;
    if (!llmConnectionId || !llmModel) {
      setMessage('Failed: configure and synchronize an LLM Provider in Settings, then select a model.');
      return;
    }
    setRunning(true);
    setMessage('Starting simulation...');
    setResults(null);
    try {
      const request = {
        tickers: list,
        benchmark: benchmark.trim().toUpperCase() || 'SPY',
        start_date: startDate,
        end_date: endDate,
        initial_capital: parseFloat(capital) || 100000,
        llm_connection_id: Number(llmConnectionId),
        model: llmModel,
      };
      const preflight = await simulationApi.preflightSim(request);
      const warningText = preflight.warnings.length
        ? `\n\nWarnings:\n- ${preflight.warnings.join('\n- ')}`
        : '';
      const reasonSummary = Object.entries(preflight.event_reason_counts)
        .filter(([, count]) => count > 0)
        .map(([reason, count]) => `${reason}: ${count}`)
        .join(', ') || 'none';
      const accepted = window.confirm(
        `Simulation preflight\n\n` +
        `Estimated model API calls: ${preflight.estimated_llm_calls}\n` +
        `Scheduled ticker events: ${preflight.estimated_refresh_events}\n` +
        `Event reasons: ${reasonSummary}\n` +
        `Persona refresh: ${preflight.persona_refresh_policy.valuation_change_pct}% / ${preflight.persona_refresh_policy.max_age_days} days\n` +
        `Provider: ${preflight.provider}\n` +
        `Model: ${preflight.model}\n` +
        `Benchmark: ${preflight.benchmark}\n` +
        `Trading days: ${preflight.trading_days}\n` +
        `Strategies: ${preflight.enabled_models.join(', ') || 'none'}\n\n` +
        `This is an event-schedule upper bound; cached prompts reduce actual calls.` +
        warningText + `\n\nContinue?`
      );
      if (!accepted) {
        setMessage(`Cancelled. Estimated model API calls: ${preflight.estimated_llm_calls}.`);
        setRunning(false);
        return;
      }
      const res = await simulationApi.runSim({
        ...request,
        confirm_cost: true,
      });
      setSimId(res.sim_id);
      setMessage(`Simulation running (up to ${preflight.estimated_llm_calls} model API calls)...`);
    } catch (error: unknown) {
      setMessage('Failed: ' + errorMessage(error));
      setRunning(false);
    }
  };

  useEffect(() => {
    if (!simId || !running) return;
    pollRef.current = setInterval(async () => {
      try {
        const status = await simulationApi.getSimStatus(simId);
        setProgress({ current: status.current_day, total: status.total_days });
        if (status.status === 'completed' || status.status === 'failed') {
          setRunning(false);
          setSimId(null);
          if (pollRef.current) clearInterval(pollRef.current);
          if (status.status === 'completed') {
            setMessage('Simulation complete!');
            const result = await simulationApi.getSimResult(simId);
            setResults(result);
            setViewingId(simId);
            await loadRunList();
          } else {
            setMessage('Simulation failed: ' + (status.error_message || 'unknown error'));
          }
        }
      } catch { /* ignore poll errors */ }
    }, 2000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [simId, running, loadRunList]);

  const viewResult = async (id: number) => {
    setViewingId(id);
    try {
      const result = await simulationApi.getSimResult(id);
      setResults(result);
      setMessage('');
    } catch (error: unknown) {
      setMessage('Failed to load result: ' + errorMessage(error));
    }
  };

  const pct = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Run Simulation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Tickers (from cache)</label>
              <Input value={tickers} onChange={e => setTickers(e.target.value)} placeholder="AAPL,MSFT" />
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Benchmark</label>
              <Input value={benchmark} onChange={e => setBenchmark(e.target.value)} placeholder="SPY" />
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Start Date</label>
              <Input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">End Date</label>
              <Input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} />
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Initial Capital ($)</label>
              <Input type="number" value={capital} onChange={e => setCapital(e.target.value)} />
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">LLM Connection</label>
              <select
                value={llmConnectionId}
                onChange={event => {
                  const id = event.target.value;
                  const provider = llmProviders.find(item => String(item.id) === id);
                  setLlmConnectionId(id);
                  setLlmModel(provider?.models[0]?.model_id || '');
                }}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="">Select a configured connection</option>
                {llmProviders.map(provider => (
                  <option key={provider.id} value={provider.id}>{provider.name} ({provider.provider_type})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">LLM Model</label>
              <select
                value={llmModel}
                onChange={event => setLlmModel(event.target.value)}
                disabled={!selectedProvider}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="">Select a synchronized model</option>
                {selectedProvider?.models.map(model => (
                  <option key={model.model_id} value={model.model_id}>
                    {model.display_name} ({model.model_id})
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button onClick={handleRun} disabled={running || !llmConnectionId || !llmModel}>
              <Play className="h-4 w-4 mr-2" />
              {running ? 'Running...' : 'Run Simulation'}
            </Button>
            {running && (
              <div className="flex items-center gap-2 flex-1">
                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${pct}%` }} />
                </div>
                <span className="text-sm text-muted-foreground whitespace-nowrap">
                  {progress.current}/{progress.total} ({pct}%)
                </span>
              </div>
            )}
          </div>
          {message && (
            <p className={cn('text-sm', message.includes('Failed') || message.includes('failed') ? 'text-red-500' : 'text-green-600')}>
              {message}
            </p>
          )}
        </CardContent>
      </Card>

      {results && viewingId && <SimResults result={results} />}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Past Simulations</CardTitle>
          <Button variant="ghost" size="sm" onClick={loadRunList} disabled={loadingList}>
            <RefreshCw className={cn('h-3 w-3', loadingList && 'animate-spin')} />
          </Button>
        </CardHeader>
        <CardContent>
          {runList.length === 0 ? (
            <p className="text-muted-foreground text-sm">No simulations run yet.</p>
          ) : (
            <div className="space-y-2">
              {runList.map(run => (
                <div
                  key={run.id}
                  className={cn(
                    'flex items-center justify-between p-3 rounded-md border cursor-pointer transition-colors',
                    viewingId === run.id ? 'border-blue-500 bg-blue-500/5' : 'hover:bg-muted/50'
                  )}
                  onClick={() => viewResult(run.id)}
                >
                  <div>
                    <span className="font-semibold text-sm">
                      {run.name || `Sim #${run.id}`}
                      <span className={cn(
                        'ml-2 text-xs px-1.5 py-0.5 rounded',
                        run.status === 'completed' ? 'bg-green-500/10 text-green-600' :
                        run.status === 'running' ? 'bg-blue-500/10 text-blue-600' :
                        run.status === 'failed' ? 'bg-red-500/10 text-red-600' :
                        'bg-muted text-muted-foreground'
                      )}>
                        {run.status}
                      </span>
                    </span>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {run.tickers.join(', ')} | {run.start_date} ~ {run.end_date} |
                      {' '}Benchmark: {run.benchmark || 'N/A'} |
                      {' '}LLM: {run.model ? `${run.llm_connection_name || run.provider || 'N/A'}/${run.model}` : 'N/A'} |
                      Capital: ${run.initial_capital.toLocaleString()}
                      {run.final_nav != null && <> | Final NAV: ${run.final_nav.toLocaleString()}</>}
                    </div>
                    {run.error_message && <div className="text-xs text-red-500 mt-1">{run.error_message}</div>}
                    {run.warnings?.map((warning, index) => (
                      <div key={index} className="text-xs text-amber-600 mt-1">{warning}</div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
