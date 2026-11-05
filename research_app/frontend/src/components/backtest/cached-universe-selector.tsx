import { useEffect, useMemo, useState } from 'react';
import { simulationApi, type CachedSecurityItem, type CacheItem, type SavedUniverse } from '@/services/simulation-api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface Props {
  selected: string[]; onChange: (tickers: string[]) => void;
  inventory: Record<string, CacheItem>; revision: number;
  disabled: boolean; onData: () => void;
}
export function CachedUniverseSelector({ selected, onChange, inventory, revision, disabled, onData }: Props) {
  const [items, setItems] = useState<CachedSecurityItem[]>([]);
  const [universes, setUniverses] = useState<SavedUniverse[]>([]);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [size, setSize] = useState(10);
  const [showAll, setShowAll] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [universeError, setUniverseError] = useState('');
  useEffect(() => {
    let current = true;
    setLoading(true); setError('');
    const timer = window.setTimeout(() => {
      simulationApi.listCachedSecurities({ search, page, page_size: size }).then(data => {
        if (current) { setItems(data.items); setTotal(data.total); }
      }).catch(err => { if (current) setError(String(err)); }).finally(() => { if (current) setLoading(false); });
    }, 180);
    return () => { current = false; clearTimeout(timer); };
  }, [search, page, size, revision, retry]);
  useEffect(() => {
    let current = true;
    simulationApi.listUniverses().then(data => { if (current) { setUniverses(data.universes); setUniverseError(''); } })
      .catch(err => { if (current) setUniverseError(`Saved universes: ${String(err)}`); });
    return () => { current = false; };
  }, [revision, retry]);
  const visible = useMemo(() => items.filter(item => showAll || !!item.prices?.count), [items, showAll]);
  const eligible = visible.filter(item => item.prices?.count).map(item => item.ticker);
  const unavailable = selected.filter(ticker => !inventory[ticker]?.prices?.count);
  return <section className="work-section" aria-labelledby="cached-heading">
    <div className="section-heading"><div><h2 id="cached-heading">Choose cached securities</h2><p>Use data already on disk. Acquire or refresh prices in Data.</p></div><Button variant="outline" onClick={onData}>Open Data</Button></div>
    <div className="toolbar">
      <Input aria-label="Search cached securities" placeholder="Search ticker or company" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} />
      <select aria-label="Load saved universe" value="" disabled={disabled} onChange={e => { const universe = universes.find(item => item.id === Number(e.target.value)); if (universe) onChange([...new Set(universe.securities.map(item => item.symbol))]); }}>
        <option value="">Load saved universe</option>{universes.filter(item => !item.archived).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </div>
    <label className="check-label"><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} /> Show entries without price data</label>
    {(error || universeError) && <div role="alert" className="notice error">{error || universeError} <Button variant="outline" onClick={() => setRetry(value => value + 1)}>Retry</Button></div>}
    <div className="table-scroll cached-picker-table" aria-busy={loading}><table className="research-table"><thead><tr><th><span className="sr-only">Select</span></th><th>Security</th><th>Price coverage</th><th>Rows / mode</th><th>Financials</th><th>Earnings</th></tr></thead><tbody>
      {!loading && !visible.length && <tr><td colSpan={6}>No matching price cache on this page. {items.length > 0 ? 'Show entries without prices or try another page.' : 'Prepare data in Data to begin.'}</td></tr>}
      {loading ? <tr><td colSpan={6}>Loading cached securities…</td></tr> : visible.map(item => <tr key={item.ticker} data-selected={selected.includes(item.ticker)}>
        <td><input aria-label={`Select ${item.ticker}`} type="checkbox" disabled={disabled || !item.prices?.count} checked={selected.includes(item.ticker)} onChange={e => onChange(e.target.checked ? [...selected, item.ticker] : selected.filter(ticker => ticker !== item.ticker))} /></td>
        <td><strong>{item.ticker}</strong><span className="cell-secondary" title={item.name}>{item.name || 'Not in current catalog'}</span></td>
        <td>{item.prices ? <>{item.prices.min}<br />{item.prices.max}</> : 'No prices'}</td><td>{item.prices?.count.toLocaleString() ?? '—'}<span className="cell-secondary">{item.prices?.price_modes?.join(', ') || 'Unknown'}</span></td><td>{item.metrics?.count ?? 0} records</td><td>{item.earnings?.count ?? 0} events</td>
      </tr>)}
    </tbody></table></div>
    <div className="toolbar pagination"><Button variant="outline" disabled={disabled || loading || !eligible.length} onClick={() => onChange([...new Set([...selected, ...eligible])])}>Select page</Button><Button variant="ghost" disabled={disabled || loading} onClick={() => onChange(selected.filter(ticker => !eligible.includes(ticker)))}>Deselect page</Button>
      <select aria-label="Cached page size" value={size} onChange={e => { setSize(Number(e.target.value)); setPage(1); }}>{[10, 20, 50].map(n => <option key={n} value={n}>{n} / page</option>)}</select>
      <Button variant="ghost" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>Previous</Button><span>{page} / {Math.max(1, Math.ceil(total / size))}</span><Button variant="ghost" disabled={page * size >= total || loading} onClick={() => setPage(page + 1)}>Next</Button>
    </div>
    <p className="quiet">{total.toLocaleString()} cached entries. Pagination includes entries without prices.</p>
    <details className="selected-list" open={selected.length <= 12}><summary>{selected.length} selected securities</summary><div className="chips">{selected.map(ticker => <button type="button" disabled={disabled} key={ticker} aria-label={`Remove ${ticker}`} onClick={() => onChange(selected.filter(value => value !== ticker))}>{ticker} <span aria-hidden="true">×</span></button>)}</div></details>
    {unavailable.length > 0 && <div className="notice warning">No cached prices for: {unavailable.join(', ')}. These universe members remain selected; remove them or prepare data before review.</div>}
  </section>;
}
