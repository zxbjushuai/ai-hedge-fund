import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import {
  simulationApi,
  type CycleAuditDetail,
  type CycleAuditSummary,
} from '@/services/simulation-api';

interface Props {
  simId: number;
  auditAvailable: boolean;
}

export function DecisionAudit({ simId, auditAvailable }: Props) {
  const [cycles, setCycles] = useState<CycleAuditSummary[]>([]);
  const [selected, setSelected] = useState<CycleAuditDetail | null>(null);
  const [date, setDate] = useState('');
  const [ticker, setTicker] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const selectCycle = useCallback(async (cycleId: number) => {
    try {
      setSelected(await simulationApi.getCycleAudit(simId, cycleId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load cycle detail');
    }
  }, [simId]);

  const loadCycles = useCallback(async (filters: { date?: string; ticker?: string } = {}) => {
    setLoading(true);
    setError('');
    try {
      const response = await simulationApi.listCycleAudits(simId, filters);
      setCycles(response.items);
      if (response.items.length) {
        await selectCycle(response.items[0].id);
      } else {
        setSelected(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load decision audit');
    } finally {
      setLoading(false);
    }
  }, [selectCycle, simId]);

  useEffect(() => {
    if (auditAvailable) void loadCycles();
  }, [auditAvailable, loadCycles]);

  const signals = useMemo(() => {
    const all = selected?.record?.strategies.flatMap(strategy =>
      strategy.signals.map(signal => ({ ...signal, strategy: strategy.name }))) || [];
    const filter = ticker.trim().toUpperCase();
    return filter ? all.filter(signal => signal.ticker === filter) : all;
  }, [selected, ticker]);

  if (!auditAvailable) {
    return (
      <Card>
        <CardHeader><CardTitle>Decision Audit</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          This historical run predates cycle auditing. NAV and trades remain available above.
        </CardContent>
      </Card>
    );
  }

  const record = selected?.record;
  const weightTickers = record
    ? [...new Set([...Object.keys(record.target_weights), ...Object.keys(record.final_weights)])].sort()
    : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Decision Audit</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-[180px_180px_auto]">
          <Input type="date" value={date} onChange={event => setDate(event.target.value)} aria-label="Audit date" />
          <Input value={ticker} onChange={event => setTicker(event.target.value.toUpperCase())}
            placeholder="Ticker, e.g. AAPL" aria-label="Audit ticker" />
          <Button variant="outline" disabled={loading}
            onClick={() => void loadCycles({ date: date || undefined, ticker: ticker || undefined })}>
            {loading ? 'Loading…' : 'Filter cycles'}
          </Button>
        </div>
        {error && <p className="text-sm text-red-500">{error}</p>}
        <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
          <div className="space-y-2 max-h-[560px] overflow-y-auto">
            {cycles.map(cycle => (
              <button key={cycle.id} type="button" onClick={() => void selectCycle(cycle.id)}
                className={cn(
                  'w-full rounded-md border p-3 text-left text-sm hover:bg-accent',
                  selected?.id === cycle.id && 'border-primary bg-accent',
                )}>
                <div className="font-medium">Cycle {cycle.cycle_number}</div>
                <div className="font-mono text-xs text-muted-foreground">
                  {cycle.signal_date} → {cycle.execution_date}
                </div>
                <div className={cn('mt-1 text-xs', cycle.status === 'failed' && 'text-red-500')}>
                  {cycle.status}{cycle.nav != null ? ` · NAV $${cycle.nav.toLocaleString()}` : ''}
                </div>
              </button>
            ))}
            {!loading && !cycles.length && (
              <p className="text-sm text-muted-foreground">No cycles match these filters.</p>
            )}
          </div>

          {selected && (
            <div className="space-y-5 min-w-0">
              <div>
                <p className="font-medium">Signal {selected.signal_date} → execution {selected.execution_date}</p>
                <p className="text-sm text-muted-foreground">Universe: {selected.universe.join(', ')}</p>
              </div>
              {selected.status === 'failed' && (
                <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm">
                  <p className="font-medium text-red-500">{selected.error_category || 'cycle failure'}</p>
                  <p>{selected.error_message}</p>
                </div>
              )}

              {record && (
                <>
                  <AuditSection title="Signals">
                    <div className="space-y-2">
                      {signals.map((signal, index) => (
                        <div key={`${signal.strategy}-${signal.model_name}-${signal.ticker}-${index}`}
                          className="rounded-md border p-3 text-sm">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono font-medium">{signal.ticker}</span>
                            <span>{signal.strategy}/{signal.model_name}</span>
                            <StatusBadge status={signal.status} />
                            <span>conviction {signal.value.toFixed(3)}</span>
                          </div>
                          {(() => {
                            const event = record.persona_events?.find(item =>
                              item.ticker === signal.ticker && item.persona === signal.model_name
                            );
                            if (!event) return null;
                            return (
                              <div className="mt-1 text-xs text-muted-foreground">
                                <span className="font-medium">{event.provenance}</span>
                                {event.trigger_reasons.length > 0 && (
                                  <span> · triggers: {event.trigger_reasons.join(', ')}</span>
                                )}
                                {event.source_signal_date && <span> · source: {event.source_signal_date}</span>}
                                {event.age_days != null && <span> · age: {event.age_days}d</span>}
                                <span> · attempt: {event.attempt_status}</span>
                                {event.next_retry_cycle != null && <span> · retry cycle: {event.next_retry_cycle}</span>}
                              </div>
                            );
                          })()}
                          {signal.failure && (
                            <p className="mt-1 text-red-500">
                              {signal.failure.category}: {signal.failure.message}
                            </p>
                          )}
                          {signal.reasoning && <p className="mt-1 text-muted-foreground">{signal.reasoning}</p>}
                        </div>
                      ))}
                      {!signals.length && <p className="text-sm text-muted-foreground">No signals for this filter.</p>}
                    </div>
                  </AuditSection>

                  <AuditSection title="Portfolio construction">
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead><tr className="border-b text-left text-muted-foreground">
                          <th className="py-2">Ticker</th><th className="text-right">Signal mark</th>
                          <th className="text-right">Execution</th><th className="text-right">Valuation</th>
                          <th className="text-right">Target</th><th className="text-right">Final</th>
                          <th className="text-right">Shares</th>
                        </tr></thead>
                        <tbody>{weightTickers.map(name => (
                          <tr key={name} className="border-b">
                            <td className="py-1.5 font-mono">{name}</td>
                            <td className="text-right">{formatPrice(record.marks[name])}</td>
                            <td className="text-right">{formatPrice(record.execution_prices[name])}</td>
                            <td className="text-right">{formatPrice(record.valuation_prices[name])}</td>
                            <td className="text-right">{formatWeight(record.target_weights[name])}</td>
                            <td className="text-right">{formatWeight(record.final_weights[name])}</td>
                            <td className="text-right">{record.positions[name] || 0}</td>
                          </tr>
                        ))}</tbody>
                      </table>
                    </div>
                    {record.clamps.map((clamp, index) => (
                      <p key={`${clamp.limit}-${clamp.ticker}-${index}`} className="mt-2 text-sm text-amber-600">
                        Clamp {clamp.limit}{clamp.ticker ? ` (${clamp.ticker})` : ''}: {clamp.before.toFixed(4)} → {clamp.after.toFixed(4)}
                      </p>
                    ))}
                  </AuditSection>

                  <AuditSection title="Execution and ending book">
                    <p className="text-sm">
                      Equity before ${record.equity_before.toLocaleString()} · cash before ${record.cash_before.toLocaleString()}
                      {' · '}ending cash ${record.cash.toLocaleString()} · NAV ${record.nav.toLocaleString()}
                    </p>
                    <div className="mt-2 space-y-1 text-sm">
                      {record.corporate_actions?.map((action, index) => (
                        <p key={`action-${index}`} className="text-blue-600">
                          Corporate action: {action.ticker} {action.action_type} {action.value} · shares {action.shares_before} → {action.shares_after} · cash {action.cash_amount.toFixed(2)}
                        </p>
                      ))}
                      {record.orders.map((order, index) => (
                        <p key={`order-${index}`}>Order: {order.side.toUpperCase()} {order.quantity} {order.ticker} @ ${order.price.toFixed(2)}</p>
                      ))}
                      {record.fills.map((fill, index) => (
                        <p key={`fill-${index}`}>Fill: {fill.side.toUpperCase()} {fill.quantity} {fill.ticker} @ ${fill.price.toFixed(2)} · fee ${fill.fee.toFixed(2)}</p>
                      ))}
                      {!record.orders.length && <p className="text-muted-foreground">No orders in this cycle.</p>}
                      {record.skipped.map((skip, index) => (
                        <p key={`skip-${index}`} className="text-amber-600">Skipped {skip.ticker}: {skip.reason}</p>
                      ))}
                    </div>
                  </AuditSection>
                </>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AuditSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h4 className="mb-2 font-semibold">{title}</h4>{children}</section>;
}

function StatusBadge({ status }: { status: 'produced' | 'abstained' | 'failed' }) {
  return (
    <span className={cn(
      'rounded px-1.5 py-0.5 text-xs font-medium',
      status === 'produced' && 'bg-green-500/10 text-green-600',
      status === 'abstained' && 'bg-amber-500/10 text-amber-600',
      status === 'failed' && 'bg-red-500/10 text-red-500',
    )}>{status}</span>
  );
}

function formatWeight(value: number | undefined) {
  return value == null ? 'N/A' : `${(value * 100).toFixed(2)}%`;
}

function formatPrice(value: number | undefined) {
  return value == null ? 'N/A' : `$${value.toFixed(2)}`;
}
