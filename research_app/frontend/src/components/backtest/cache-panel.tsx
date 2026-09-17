import { simulationApi } from '@/services/simulation-api';
import type { CachedSecurityItem, CacheJob } from '@/services/simulation-api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { RefreshCw, Trash2 } from 'lucide-react';
import { Fragment, useEffect, useState, useCallback } from 'react';
import { SecurityBrowser } from './security-browser';
import { CacheSecurityDetail } from './cache-security-detail';

const dateDaysAgo = (days: number) =>
  new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : String(error);

export function CachePanel() {
  const [cacheItems, setCacheItems] = useState<CachedSecurityItem[]>([]);
  const [cacheTotal, setCacheTotal] = useState(0);
  const [cacheSearch, setCacheSearch] = useState('');
  const [cacheStatus, setCacheStatus] = useState('');
  const [cacheMode, setCacheMode] = useState('');
  const [cachePage, setCachePage] = useState(1);
  const [cachePageSize, setCachePageSize] = useState(20);
  const [cacheSort, setCacheSort] = useState('symbol:asc');
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [tickers, setTickers] = useState('AAPL,MSFT');
  const [securityIds, setSecurityIds] = useState<number[]>([]);
  const [benchmark, setBenchmark] = useState('SPY');
  const [startDate, setStartDate] = useState(() => dateDaysAgo(365));
  const [endDate, setEndDate] = useState(() => dateDaysAgo(1));
  const [message, setMessage] = useState('');
  const [includeMetrics, setIncludeMetrics] = useState(false);
  const [includeEarnings, setIncludeEarnings] = useState(false);
  const [job, setJob] = useState<CacheJob | null>(null);

  const loadCache = useCallback(async () => {
    setLoading(true);
    try {
      const [sortBy, sortDir] = cacheSort.split(':');
      const data = await simulationApi.listCachedSecurities({
        search: cacheSearch, status: cacheStatus, price_mode: cacheMode,
        page: cachePage, page_size: cachePageSize, sort_by: sortBy, sort_dir: sortDir,
      });
      setCacheItems(data.items);
      setCacheTotal(data.total);
    } catch (error: unknown) {
      setMessage('Failed to load cache: ' + errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [cacheMode, cachePage, cachePageSize, cacheSearch, cacheSort, cacheStatus]);

  useEffect(() => { loadCache(); }, [loadCache]);

  useEffect(() => {
    if (!job || !['pending', 'running', 'cancelling'].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await simulationApi.getCacheJob(job.id);
        setJob(next);
        if (!['pending', 'running', 'cancelling'].includes(next.status)) {
          setFetching(false);
          setMessage(`Cache job ${next.status}: ${next.progress.completed} completed, ${next.progress.failed} failed.`);
          await loadCache();
        }
      } catch (error) {
        setFetching(false);
        setMessage('Cache job polling failed: ' + errorMessage(error));
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job, loadCache]);

  const handleFetch = async () => {
    const list = tickers.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
    if (!list.length) return;
    setFetching(true);
    setMessage('Fetching...');
    let backgroundStarted = false;
    try {
      const dataTypes = ['prices'];
      if (includeMetrics) dataTypes.push('metrics');
      if (includeEarnings) dataTypes.push('earnings');
      const created = await simulationApi.createCacheJob({
        selection: securityIds.length === list.length ? { security_ids: securityIds } : { tickers: list },
        benchmark: benchmark.trim().toUpperCase() || 'SPY',
        start_date: startDate,
        end_date: endDate,
        data_types: dataTypes,
      });
      setJob(created);
      backgroundStarted = true;
      setMessage(`Cache job started for ${created.progress.total} symbols.`);
    } catch (error: unknown) {
      setMessage('Fetch failed: ' + errorMessage(error));
    } finally {
      if (!backgroundStarted) setFetching(false);
    }
  };

  const handleDelete = async (ticker: string) => {
    try {
      await simulationApi.deleteCache(ticker);
      if (expandedTicker === ticker) setExpandedTicker(null);
      setMessage(`Deleted ${ticker}`);
      await loadCache();
    } catch (error: unknown) {
      setMessage('Delete failed: ' + errorMessage(error));
    }
  };
  const cachePageCount = Math.max(1, Math.ceil(cacheTotal / cachePageSize));

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Fetch Historical Data</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <SecurityBrowser value={tickers} onChange={setTickers} onSecurityIdsChange={setSecurityIds} />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Benchmark</label>
              <Input
                value={benchmark}
                onChange={e => setBenchmark(e.target.value)}
                placeholder="SPY"
              />
              <p className="mt-1 text-xs text-muted-foreground">Trading-day grid and performance baseline; not traded unless selected above.</p>
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Start Date</label>
              <Input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">End Date</label>
              <Input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} />
            </div>
            <div className="flex items-end">
              <Button onClick={handleFetch} disabled={fetching} className="w-full">
                <RefreshCw className={cn('h-4 w-4 mr-2', fetching && 'animate-spin')} />
                {fetching ? 'Fetching...' : 'Fetch Data'}
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-5 text-sm">
            <label className="flex items-center gap-2"><Checkbox checked disabled />Prices (raw OHLC + corporate actions)</label>
            <label className="flex items-center gap-2"><Checkbox checked={includeMetrics} onCheckedChange={value => setIncludeMetrics(Boolean(value))} />Financial metrics</label>
            <label className="flex items-center gap-2"><Checkbox checked={includeEarnings} onCheckedChange={value => setIncludeEarnings(Boolean(value))} />Earnings surprises</label>
          </div>
          {job && (
            <div className="space-y-2 rounded-md border p-3 text-sm">
              <div className="flex items-center gap-3">
                <span className="font-semibold">Job {job.status}</span>
                <span>{job.progress.completed + job.progress.failed}/{job.progress.total}</span>
                {['pending', 'running'].includes(job.status) && <Button size="sm" variant="outline" onClick={() => simulationApi.cancelCacheJob(job.id).then(setJob)}>Cancel</Button>}
                {['partial', 'failed'].includes(job.status) && <Button size="sm" variant="outline" onClick={() => simulationApi.retryCacheJob(job.id).then(next => { setJob(next); setFetching(true); })}>Retry failed</Button>}
              </div>
              <div className="max-h-40 overflow-auto text-xs text-muted-foreground">
                {Object.entries(job.items).map(([ticker, item]) => (
                  <div key={ticker}>{ticker}: {['prices', 'metrics', 'earnings'].map(kind => {
                    const result = item[kind as keyof typeof item];
                    return result && typeof result === 'object' && 'status' in result ? `${kind}=${result.status}` : null;
                  }).filter(Boolean).join(', ')}</div>
                ))}
              </div>
            </div>
          )}
          {message && (
            <p className={cn('text-sm', message.includes('Failed') || message.includes('failed')
              ? 'text-red-500' : 'text-muted-foreground')}>
              {message}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Cached Data ({cacheTotal.toLocaleString()})</CardTitle>
          <Button variant="ghost" size="sm" onClick={loadCache} disabled={loading}>
            <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Input className="min-w-52 flex-1" value={cacheSearch} onChange={event => { setCacheSearch(event.target.value); setCachePage(1); }} placeholder="Search cached symbol or company" />
            <select className="h-10 rounded border bg-background px-2 text-sm" value={cacheStatus} onChange={event => { setCacheStatus(event.target.value); setCachePage(1); }}>
              <option value="">All coverage</option><option value="complete">Complete</option><option value="partial">Partial</option><option value="no_data">No data</option><option value="failed">Failed</option>
            </select>
            <select className="h-10 rounded border bg-background px-2 text-sm" value={cacheMode} onChange={event => { setCacheMode(event.target.value); setCachePage(1); }}>
              <option value="">All price modes</option><option value="raw">Raw</option><option value="legacy_unknown">Legacy unknown</option>
            </select>
            <select className="h-10 rounded border bg-background px-2 text-sm" value={cacheSort} onChange={event => { setCacheSort(event.target.value); setCachePage(1); }}>
              <option value="symbol:asc">Symbol A–Z</option><option value="symbol:desc">Symbol Z–A</option>
              <option value="actual_end:desc">Latest coverage</option><option value="rows:desc">Most price rows</option>
              <option value="latest_close:desc">Highest latest close</option><option value="latest_volume:desc">Highest latest volume</option>
              <option value="updated_at:desc">Recently fetched</option>
            </select>
          </div>
          {loading && cacheItems.length === 0 ? (
            <p className="text-muted-foreground text-sm">Loading...</p>
          ) : cacheItems.length === 0 ? (
            <p className="text-muted-foreground text-sm">No data cached. Fetch some tickers first.</p>
          ) : (
            <div className="overflow-auto rounded border">
              <table className="w-full min-w-[1080px] text-sm">
                <thead className="sticky top-0 bg-background"><tr className="border-b text-left text-xs text-muted-foreground">
                  {['Symbol', 'Company', 'Exchange', 'Price coverage', 'Rows', 'Mode', 'Latest close', 'Volume', 'Metrics', 'Earnings', 'Quality', ''].map(value => <th key={value} className="px-2 py-2">{value}</th>)}
                </tr></thead>
                <tbody>{cacheItems.map(item => (
                  <Fragment key={item.ticker}>
                    <tr className="cursor-pointer border-b hover:bg-muted/40" onClick={() => setExpandedTicker(value => value === item.ticker ? null : item.ticker)}>
                      <td className="px-2 py-2 font-mono font-semibold">{item.ticker}</td><td className="max-w-56 px-2"><div className="truncate" title={item.name}>{item.name || '—'}</div></td>
                      <td className="whitespace-nowrap px-2">{item.exchange || '—'}</td><td className="whitespace-nowrap px-2">{item.prices ? `${item.prices.min}–${item.prices.max}` : 'No prices'}</td>
                      <td className="px-2">{item.prices?.count ?? 0}</td><td className="px-2">{(item.prices?.price_modes || []).join('/') || '—'}</td>
                      <td className="px-2">{item.latest_close == null ? '—' : `$${item.latest_close.toFixed(2)}`}</td><td className="px-2">{item.latest_volume?.toLocaleString() ?? '—'}</td>
                      <td className="px-2">{item.metrics?.count ?? 0}</td><td className="px-2">{item.earnings?.count ?? 0}</td>
                      <td className={cn('px-2', item.coverage?.status === 'complete' ? 'text-green-600' : 'text-amber-600')}>{item.coverage?.status || 'unknown'}{item.coverage?.missing_sessions ? ` (${item.coverage.missing_sessions} missing)` : ''}</td>
                      <td className="px-2"><Button variant="ghost" size="sm" aria-label={`Delete ${item.ticker} cache`} onClick={event => { event.stopPropagation(); handleDelete(item.ticker); }}><Trash2 className="h-4 w-4 text-red-500" /></Button></td>
                    </tr>
                    {expandedTicker === item.ticker && <tr><td colSpan={12}><CacheSecurityDetail ticker={item.ticker} /></td></tr>}
                  </Fragment>
                ))}</tbody>
              </table>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-2 text-xs">
            <span>Page size</span><select className="h-8 rounded border bg-background px-2" value={cachePageSize} onChange={event => { setCachePageSize(Number(event.target.value)); setCachePage(1); }}>{[10, 20, 50, 100].map(value => <option key={value} value={value}>{value}</option>)}</select>
            <Button size="sm" variant="ghost" disabled={cachePage <= 1} onClick={() => setCachePage(value => value - 1)}>Previous</Button><span>{cachePage} / {cachePageCount}</span><Button size="sm" variant="ghost" disabled={cachePage >= cachePageCount} onClick={() => setCachePage(value => value + 1)}>Next</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
