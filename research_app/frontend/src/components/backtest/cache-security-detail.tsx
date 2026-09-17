import { Button } from '@/components/ui/button';
import { simulationApi } from '@/services/simulation-api';
import type { CachedSecurityDetail } from '@/services/simulation-api';
import { cn } from '@/lib/utils';
import { useEffect, useMemo, useState } from 'react';

const messageFor = (error: unknown) => error instanceof Error ? error.message : String(error);

export function CacheSecurityDetail({ ticker }: { ticker: string }) {
  const [detail, setDetail] = useState<CachedSecurityDetail | null>(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'prices' | 'financials' | 'earnings' | 'quality'>('prices');
  const [pricePage, setPricePage] = useState(1);
  const pricePageSize = 50;

  useEffect(() => {
    let active = true;
    setDetail(null);
    setError('');
    simulationApi.getCachedSecurity(ticker).then(value => {
      if (active) setDetail(value);
    }).catch(reason => {
      if (active) setError(messageFor(reason));
    });
    return () => { active = false; };
  }, [ticker]);

  const chart = useMemo(() => {
    if (!detail?.prices.length) return null;
    const source = detail.prices;
    const stride = Math.max(1, Math.ceil(source.length / 700));
    const rows = source.filter((_, index) => index % stride === 0 || index === source.length - 1);
    const values = rows.flatMap(row => [row.close, row.adjusted_close ?? row.close]);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, Math.abs(max) * 0.01, 1);
    const w = 900; const h = 300;
    const margin = { left: 65, right: 18, top: 18, bottom: 42 };
    const plotWidth = w - margin.left - margin.right;
    const plotHeight = h - margin.top - margin.bottom;
    const x = (index: number) => margin.left + index / Math.max(rows.length - 1, 1) * plotWidth;
    const y = (value: number) => margin.top + (max - value) / range * plotHeight;
    const close = rows.map((row, index) => `${x(index)},${y(row.close)}`).join(' ');
    const adjusted = rows.map((row, index) => `${x(index)},${y(row.adjusted_close ?? row.close)}`).join(' ');
    const yTicks = Array.from({ length: 5 }, (_, index) => {
      const value = max - index / 4 * range;
      return { value, y: y(value) };
    });
    const tickIndexes = Array.from(new Set(Array.from({ length: Math.min(5, rows.length) }, (_, index) =>
      Math.round(index / Math.max(Math.min(5, rows.length) - 1, 1) * (rows.length - 1)))));
    return { w, h, margin, close, adjusted, yTicks, xTicks: tickIndexes.map(index => ({ x: x(index), date: rows[index].date })) };
  }, [detail]);

  if (error) return <p className="p-4 text-sm text-red-500">Failed to load cached detail: {error}</p>;
  if (!detail) return <p className="p-4 text-sm text-muted-foreground">Loading cached data…</p>;

  const pricePages = Math.max(1, Math.ceil(detail.prices.length / pricePageSize));
  const visiblePrices = detail.prices.slice((pricePage - 1) * pricePageSize, pricePage * pricePageSize);

  return (
    <div className="space-y-3 bg-muted/20 p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold">All effective local cache for {ticker}</span>
        <span className="text-muted-foreground">{detail.prices.length.toLocaleString()} prices · {detail.metrics.length} financial periods · {detail.earnings.length} earnings events</span>
      </div>
      <div className="flex flex-wrap gap-1">
        {(['prices', 'financials', 'earnings', 'quality'] as const).map(value => (
          <Button key={value} size="sm" variant={tab === value ? 'default' : 'outline'} onClick={() => setTab(value)} className="capitalize">{value}</Button>
        ))}
      </div>

      {tab === 'prices' && <div className="space-y-3">
        {chart && <div className="rounded border bg-background p-3">
          <div className="mb-2 flex gap-4 text-xs"><span className="text-blue-500">Raw close</span><span className="text-cyan-500">Adjusted close</span></div>
          <svg viewBox={`0 0 ${chart.w} ${chart.h}`} className="h-auto w-full">
            {chart.yTicks.map(tick => <g key={tick.value}>
              <line x1={chart.margin.left} y1={tick.y} x2={chart.w - chart.margin.right} y2={tick.y} stroke="currentColor" strokeOpacity={0.08} />
              <text x={chart.margin.left - 8} y={tick.y + 4} textAnchor="end" className="fill-muted-foreground text-[11px]">${tick.value.toFixed(2)}</text>
            </g>)}
            {chart.xTicks.map(tick => <text key={tick.date} x={tick.x} y={chart.h - 12} textAnchor="middle" className="fill-muted-foreground text-[11px]">{tick.date}</text>)}
            <polyline points={chart.close} fill="none" stroke="#3b82f6" strokeWidth="2" />
            <polyline points={chart.adjusted} fill="none" stroke="#06b6d4" strokeWidth="2" />
          </svg>
        </div>}
        <div className="overflow-auto rounded border bg-background">
          <table className="w-full min-w-[900px] text-xs">
            <thead className="sticky top-0 bg-background"><tr className="border-b text-left text-muted-foreground">
              {['Date', 'Open', 'High', 'Low', 'Close', 'Adjusted', 'Volume', 'Dividend', 'Split', 'Mode'].map(value => <th key={value} className="px-2 py-2">{value}</th>)}
            </tr></thead>
            <tbody>{visiblePrices.map(row => <tr key={row.date} className="border-b last:border-0">
              <td className="px-2 py-1.5">{row.date}</td><td className="px-2">{row.open.toFixed(2)}</td><td className="px-2">{row.high.toFixed(2)}</td>
              <td className="px-2">{row.low.toFixed(2)}</td><td className="px-2">{row.close.toFixed(2)}</td><td className="px-2">{row.adjusted_close?.toFixed(2) ?? 'N/A'}</td>
              <td className="px-2">{row.volume.toLocaleString()}</td><td className="px-2">{row.dividend}</td><td className="px-2">{row.split_ratio || '—'}</td><td className="px-2">{row.price_mode}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="flex items-center justify-end gap-2 text-xs"><Button size="sm" variant="ghost" disabled={pricePage === 1} onClick={() => setPricePage(value => value - 1)}>Previous</Button><span>{pricePage} / {pricePages}</span><Button size="sm" variant="ghost" disabled={pricePage === pricePages} onClick={() => setPricePage(value => value + 1)}>Next</Button></div>
      </div>}

      {tab === 'financials' && <div className="max-h-96 space-y-2 overflow-auto">
        {detail.metrics.length ? detail.metrics.map(row => <details key={row.report_period} className="rounded border bg-background p-2 text-xs">
          <summary className="cursor-pointer font-medium">{row.report_period} · visible {row.filing_date || 'unknown'} · {row.filing_date_source}</summary>
          <pre className="mt-2 overflow-auto whitespace-pre-wrap text-[11px] text-muted-foreground">{JSON.stringify(row.data, null, 2)}</pre>
        </details>) : <p className="text-sm text-muted-foreground">No financial metrics cached.</p>}
      </div>}

      {tab === 'earnings' && <div className="overflow-auto rounded border bg-background">
        <table className="w-full min-w-[650px] text-xs"><thead><tr className="border-b text-left text-muted-foreground">
          {['Announcement', 'Report period', 'Actual EPS', 'Estimated EPS', 'Surprise', 'Source'].map(value => <th key={value} className="px-2 py-2">{value}</th>)}
        </tr></thead><tbody>{detail.earnings.map(row => <tr key={`${row.announcement_date}-${row.report_period}`} className="border-b last:border-0">
          <td className="px-2 py-1.5">{row.announcement_date}</td><td className="px-2">{row.report_period}</td><td className="px-2">{row.actual_eps ?? 'N/A'}</td>
          <td className="px-2">{row.estimated_eps ?? 'N/A'}</td><td className="px-2">{row.surprise_pct == null ? 'N/A' : `${row.surprise_pct.toFixed(2)}%`}</td><td className="px-2">{row.source}</td>
        </tr>)}</tbody></table>
        {!detail.earnings.length && <p className="p-3 text-sm text-muted-foreground">No earnings surprises cached.</p>}
      </div>}

      {tab === 'quality' && <div className="overflow-auto rounded border bg-background">
        <table className="w-full min-w-[850px] text-xs"><thead><tr className="border-b text-left text-muted-foreground">
          {['Fetched', 'Kind', 'Requested', 'Actual', 'Rows', 'Missing sessions', 'Status', 'Error'].map(value => <th key={value} className="px-2 py-2">{value}</th>)}
        </tr></thead><tbody>{detail.coverage_history.map((row, index) => <tr key={`${row.fetched_at}-${index}`} className="border-b last:border-0">
          <td className="whitespace-nowrap px-2 py-1.5">{row.fetched_at}</td><td className="px-2">{row.data_kind}</td><td className="whitespace-nowrap px-2">{row.requested_start}–{row.requested_end}</td>
          <td className="whitespace-nowrap px-2">{row.actual_start || 'N/A'}–{row.actual_end || 'N/A'}</td><td className="px-2">{row.row_count}</td><td className="px-2">{row.missing_sessions}</td>
          <td className={cn('px-2', row.status === 'complete' ? 'text-green-600' : 'text-amber-600')}>{row.status}</td><td className="px-2">{row.error_category || row.error_message || '—'}</td>
        </tr>)}</tbody></table>
      </div>}
    </div>
  );
}
