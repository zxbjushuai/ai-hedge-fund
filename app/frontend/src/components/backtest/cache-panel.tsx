import { simulationApi } from '@/services/simulation-api';
import type { CacheItem } from '@/services/simulation-api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { RefreshCw, Trash2 } from 'lucide-react';
import { useEffect, useState, useCallback } from 'react';

const dateDaysAgo = (days: number) =>
  new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);

export function CachePanel() {
  const [cache, setCache] = useState<Record<string, CacheItem>>({});
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [tickers, setTickers] = useState('AAPL,MSFT');
  const [startDate, setStartDate] = useState(() => dateDaysAgo(365));
  const [endDate, setEndDate] = useState(() => dateDaysAgo(1));
  const [message, setMessage] = useState('');

  const loadCache = useCallback(async () => {
    setLoading(true);
    try {
      const data = await simulationApi.listCache();
      setCache(data.cached || {});
    } catch (e: any) {
      setMessage('Failed to load cache: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadCache(); }, [loadCache]);

  const handleFetch = async () => {
    const list = tickers.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
    if (!list.length) return;
    setFetching(true);
    setMessage('Fetching...');
    try {
      const res = await simulationApi.fetchCache({
        tickers: list,
        start_date: startDate,
        end_date: endDate,
      });
      const msgs: string[] = [];
      for (const [t, r] of Object.entries(res.results)) {
        const parts = [];
        if (r.prices > 0) parts.push(`${r.prices} prices`);
        if (r.metrics > 0) parts.push(`${r.metrics} metrics`);
        if (r.earnings > 0) parts.push(`${r.earnings} earnings events`);
        if (r.error) parts.push(`error: ${r.error}`);
        msgs.push(`${t}: ${parts.join(', ') || 'no data'}`);
      }
      setMessage(msgs.join(' | '));
      await loadCache();
    } catch (e: any) {
      setMessage('Fetch failed: ' + e.message);
    } finally {
      setFetching(false);
    }
  };

  const handleDelete = async (ticker: string) => {
    try {
      await simulationApi.deleteCache(ticker);
      setMessage(`Deleted ${ticker}`);
      await loadCache();
    } catch (e: any) {
      setMessage('Delete failed: ' + e.message);
    }
  };

  const entries = Object.entries(cache);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Fetch Historical Data</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Tickers</label>
              <Input
                value={tickers}
                onChange={e => setTickers(e.target.value)}
                placeholder="AAPL,MSFT,TSLA"
              />
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
          <CardTitle>Cached Data ({entries.length})</CardTitle>
          <Button variant="ghost" size="sm" onClick={loadCache} disabled={loading}>
            <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
          </Button>
        </CardHeader>
        <CardContent>
          {loading && entries.length === 0 ? (
            <p className="text-muted-foreground text-sm">Loading...</p>
          ) : entries.length === 0 ? (
            <p className="text-muted-foreground text-sm">No data cached. Fetch some tickers first.</p>
          ) : (
            <div className="space-y-2">
              {entries.map(([ticker, item]) => (
                <div key={ticker} className="flex items-center justify-between p-3 rounded-md border">
                  <div>
                    <span className="font-mono font-semibold">{ticker}</span>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {item.prices
                        ? `Prices: ${item.prices.count} rows (${item.prices.min} ~ ${item.prices.max})`
                        : 'No prices'}
                      {' | '}
                      {item.metrics
                        ? `Metrics: ${item.metrics.count} periods (${item.metrics.min} ~ ${item.metrics.max})`
                        : 'No metrics'}
                      {' | '}
                      {item.earnings
                        ? `Earnings: ${item.earnings.count} events (${item.earnings.min} ~ ${item.earnings.max})`
                        : 'No earnings'}
                    </div>
                    {item.filing_date_note && (
                      <div className="text-xs text-amber-600 mt-1">{item.filing_date_note}</div>
                    )}
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(ticker)}>
                    <Trash2 className="h-4 w-4 text-red-500" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
