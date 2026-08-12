import type { SimResult } from '@/services/simulation-api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { useMemo } from 'react';

interface Props {
  result: SimResult;
}

export function SimResults({ result }: Props) {
  const chart = useMemo(() => {
    if (!result.nav_curve.length) return null;
    const values = result.nav_curve.map(p => p.nav);
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const rawRange = rawMax - rawMin;
    const padding = rawRange > 0 ? rawRange * 0.08 : Math.max(Math.abs(rawMax) * 0.01, 1);
    const min = rawMin - padding;
    const max = rawMax + padding;
    const range = max - min;
    const w = 720;
    const h = 280;
    const margin = { top: 16, right: 20, bottom: 48, left: 76 };
    const plotWidth = w - margin.left - margin.right;
    const plotHeight = h - margin.top - margin.bottom;
    const xScale = (i: number) => margin.left + (i / Math.max(result.nav_curve.length - 1, 1)) * plotWidth;
    const yScale = (v: number) => margin.top + ((max - v) / range) * plotHeight;
    const points = result.nav_curve.map((p, i) => `${xScale(i)},${yScale(p.nav)}`).join(' ');
    const baselineY = yScale(result.initial_capital);
    const yTicks = Array.from({ length: 5 }, (_, i) => {
      const value = max - (i / 4) * range;
      return { value, y: yScale(value) };
    });
    const xTickCount = Math.min(5, result.nav_curve.length);
    const xTickIndices = Array.from({ length: xTickCount }, (_, i) =>
      Math.round((i / Math.max(xTickCount - 1, 1)) * (result.nav_curve.length - 1))
    );
    const xTicks = [...new Set(xTickIndices)].map(index => ({
      date: result.nav_curve[index].date,
      x: xScale(index),
    }));

    return { w, h, points, baselineY, yTicks, xTicks, margin };
  }, [result]);

  return (
    <div className="space-y-4">
      {(result.models?.length || result.warnings?.length) && (
        <Card>
          <CardContent className="p-4 text-sm space-y-1">
            {result.models?.length ? (
              <p className="text-muted-foreground">Models used: {result.models.join(', ')}</p>
            ) : null}
            {result.warnings?.map((warning, index) => (
              <p key={index} className="text-amber-600">Data warning: {warning}</p>
            ))}
          </CardContent>
        </Card>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard label="Final NAV" value={`$${result.final_nav.toLocaleString()}`} />
        <MetricCard
          label="Total Return"
          value={`${result.total_return_pct.toFixed(2)}%`}
          positive={result.total_return_pct >= 0}
        />
        <MetricCard label="Max Drawdown" value={`${result.max_drawdown_pct.toFixed(2)}%`} />
        <MetricCard label="Sharpe Ratio" value={result.sharpe_ratio.toFixed(2)} />
      </div>

      {chart && (
        <Card>
          <CardHeader>
            <CardTitle>NAV Curve</CardTitle>
          </CardHeader>
          <CardContent>
            <svg viewBox={`0 0 ${chart.w} ${chart.h}`} className="w-full h-auto">
              {chart.yTicks.map(tick => (
                <g key={tick.value}>
                  <line x1={chart.margin.left} y1={tick.y} x2={chart.w - chart.margin.right} y2={tick.y}
                    stroke="currentColor" strokeOpacity={0.08} />
                  <text x={chart.margin.left - 10} y={tick.y + 4} textAnchor="end"
                    className="fill-muted-foreground text-[11px]">
                    ${tick.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </text>
                </g>
              ))}
              <line x1={chart.margin.left} y1={chart.margin.top}
                x2={chart.margin.left} y2={chart.h - chart.margin.bottom}
                stroke="currentColor" strokeOpacity={0.25} />
              <line x1={chart.margin.left} y1={chart.h - chart.margin.bottom}
                x2={chart.w - chart.margin.right} y2={chart.h - chart.margin.bottom}
                stroke="currentColor" strokeOpacity={0.25} />
              {chart.xTicks.map(tick => (
                <g key={tick.date}>
                  <line x1={tick.x} y1={chart.h - chart.margin.bottom}
                    x2={tick.x} y2={chart.h - chart.margin.bottom + 5}
                    stroke="currentColor" strokeOpacity={0.3} />
                  <text x={tick.x} y={chart.h - 18} textAnchor="middle"
                    className="fill-muted-foreground text-[11px]">
                    {tick.date}
                  </text>
                </g>
              ))}
              <line x1={chart.margin.left} y1={chart.baselineY} x2={chart.w - chart.margin.right} y2={chart.baselineY}
                stroke="currentColor" strokeOpacity={0.15} strokeDasharray="4 2" />
              <polyline points={chart.points} fill="none" stroke="#3b82f6" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Trade Log ({result.trade_count} trades)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground text-left">
                  <th className="py-2 pr-4">Date</th>
                  <th className="py-2 pr-4">Ticker</th>
                  <th className="py-2 pr-4 text-right">Side</th>
                  <th className="py-2 pr-4 text-right">Qty</th>
                  <th className="py-2 pr-4 text-right">Price</th>
                  <th className="py-2 pr-4 text-right">Fee</th>
                  <th className="py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody>
                {result.trades.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-4 text-center text-muted-foreground">No trades</td>
                  </tr>
                ) : (
                  result.trades.map(t => (
                    <tr key={t.id} className="border-b border-muted">
                      <td className="py-1.5 pr-4 font-mono text-xs">{t.date}</td>
                      <td className="py-1.5 pr-4 font-mono">{t.ticker}</td>
                      <td className={cn(
                        'py-1.5 pr-4 text-right font-semibold',
                        t.side === 'BUY' ? 'text-green-600' : 'text-red-500'
                      )}>
                        {t.side}
                      </td>
                      <td className="py-1.5 pr-4 text-right">{t.quantity}</td>
                      <td className="py-1.5 pr-4 text-right">${t.price.toFixed(2)}</td>
                      <td className="py-1.5 pr-4 text-right">${t.fee.toFixed(2)}</td>
                      <td className="py-1.5 text-right">${t.total_amount.toFixed(2)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn(
          'text-lg font-bold mt-0.5',
          positive === true && 'text-green-600',
          positive === false && 'text-red-500',
        )}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
