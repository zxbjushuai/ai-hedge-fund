import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { simulationApi } from '@/services/simulation-api';
import type { SavedUniverse, SecurityItem } from '@/services/simulation-api';
import { RefreshCw, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

const messageFor = (error: unknown) => error instanceof Error ? error.message : String(error);

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSecurityIdsChange?: (ids: number[]) => void;
  compact?: boolean;
}

export function SecuritySelector({ value, onChange, onSecurityIdsChange, compact = false }: Props) {
  const [items, setItems] = useState<SecurityItem[]>([]);
  const [selected, setSelected] = useState<Record<string, SecurityItem>>({});
  const [search, setSearch] = useState('');
  const [exchange, setExchange] = useState('');
  const [assetType, setAssetType] = useState('');
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [universes, setUniverses] = useState<SavedUniverse[]>([]);
  const [universeName, setUniverseName] = useState('');
  const [message, setMessage] = useState('');
  const pageSize = compact ? 10 : 20;

  const symbols = useMemo(() => value.split(',').map(item => item.trim().toUpperCase()).filter(Boolean), [value]);

  const publish = useCallback((next: Record<string, SecurityItem>, extraSymbols: string[] = []) => {
    setSelected(next);
    const merged = [...Object.keys(next), ...extraSymbols.filter(symbol => !next[symbol])];
    onChange(Array.from(new Set(merged)).join(','));
    onSecurityIdsChange?.(Object.values(next).map(item => item.id));
  }, [onChange, onSecurityIdsChange]);

  const load = useCallback(async () => {
    try {
      const response = await simulationApi.listSecurities({ search, exchange, asset_type: assetType, page, page_size: pageSize });
      setItems(response.items);
      setTotal(response.total);
    } catch (error) {
      setMessage('Catalog unavailable: ' + messageFor(error));
    }
  }, [assetType, exchange, page, pageSize, search]);

  const loadUniverses = useCallback(async () => {
    try { setUniverses((await simulationApi.listUniverses()).universes); } catch { /* catalog may not be initialized */ }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadUniverses(); }, [loadUniverses]);
  useEffect(() => {
    const known = Object.fromEntries(
      Object.entries(selected).filter(([symbol]) => symbols.includes(symbol)),
    );
    for (const item of items) if (symbols.includes(item.symbol)) known[item.symbol] = item;
    if (Object.keys(known).sort().join(',') !== Object.keys(selected).sort().join(',')) {
      setSelected(known);
      onSecurityIdsChange?.(Object.values(known).map(item => item.id));
    }
  }, [items, onSecurityIdsChange, selected, symbols]);

  const toggle = (item: SecurityItem) => {
    const next = { ...selected };
    if (next[item.symbol]) delete next[item.symbol]; else next[item.symbol] = item;
    const manual = symbols.filter(symbol => !selected[symbol] && symbol !== item.symbol);
    publish(next, manual);
  };

  const selectFiltered = async () => {
    const response = await simulationApi.listSecurities({ search, exchange, asset_type: assetType, page: 1, page_size: 1000 });
    const next = { ...selected };
    response.items.forEach(item => { next[item.symbol] = item; });
    publish(next, symbols.filter(symbol => !selected[symbol]));
  };

  const selectPage = () => {
    const next = { ...selected };
    items.forEach(item => { next[item.symbol] = item; });
    publish(next, symbols.filter(symbol => !selected[symbol]));
  };

  const synchronize = async () => {
    setMessage('Synchronizing US catalog...');
    try {
      const result = await simulationApi.syncSecurities();
      setMessage(`Catalog synchronized: ${result.total} active records.`);
      await load();
    } catch (error) { setMessage('Catalog sync failed: ' + messageFor(error)); }
  };

  const saveUniverse = async () => {
    const ids = Object.values(selected).map(item => item.id);
    if (!universeName.trim() || !ids.length) return;
    try {
      await simulationApi.createUniverse(universeName.trim(), ids);
      setUniverseName('');
      await loadUniverses();
      setMessage('Universe saved.');
    } catch (error) { setMessage('Save failed: ' + messageFor(error)); }
  };

  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-[180px] flex-1">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="Search US symbol or company" />
        </div>
        <Input className="w-36" value={exchange} onChange={event => { setExchange(event.target.value); setPage(1); }} placeholder="Exchange" />
        <select className="h-10 rounded-md border bg-background px-2 text-sm" value={assetType} onChange={event => { setAssetType(event.target.value); setPage(1); }}>
          <option value="">Equities & ETFs</option><option value="equity">Equity / ADR</option><option value="etf">ETF</option>
        </select>
        <Button variant="outline" onClick={synchronize}><RefreshCw className="mr-1 h-4 w-4" />Sync catalog</Button>
      </div>
      <div className="max-h-52 overflow-auto rounded border">
        {items.length ? items.map(item => (
          <label key={item.id} className="flex cursor-pointer items-center gap-2 border-b px-3 py-2 text-sm last:border-0">
            <Checkbox checked={Boolean(selected[item.symbol])} onCheckedChange={() => toggle(item)} />
            <span className="w-20 font-mono font-semibold">{item.symbol}</span>
            <span className="min-w-0 flex-1 truncate">{item.name}</span>
            <span className="text-xs text-muted-foreground">{item.exchange} · {item.asset_type}</span>
          </label>
        )) : <p className="p-3 text-sm text-muted-foreground">No catalog rows. Sync the US catalog or use manual tickers below.</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Button size="sm" variant="outline" onClick={selectPage}>Select page</Button>
        <Button size="sm" variant="outline" onClick={selectFiltered}>Select filtered ({total})</Button>
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>Previous</Button>
        <span>{page} / {Math.max(1, Math.ceil(total / pageSize))}</span>
        <Button size="sm" variant="ghost" disabled={page * pageSize >= total} onClick={() => setPage(value => value + 1)}>Next</Button>
        <span className="ml-auto">Selected: {symbols.length}</span>
      </div>
      <Input value={value} onChange={event => onChange(event.target.value.toUpperCase())} placeholder="Manual fallback: AAPL,MSFT" />
      <div className="flex gap-2">
        <select className="h-9 min-w-44 rounded-md border bg-background px-2 text-sm" defaultValue="" onChange={event => {
          const universe = universes.find(item => String(item.id) === event.target.value);
          if (!universe) return;
          const next = Object.fromEntries(universe.securities.map(item => [item.symbol, item]));
          publish(next);
        }}>
          <option value="">Load saved universe</option>
          {universes.map(item => <option key={item.id} value={item.id}>{item.name} ({item.securities.length})</option>)}
        </select>
        <Input className="max-w-56" value={universeName} onChange={event => setUniverseName(event.target.value)} placeholder="New universe name" />
        <Button size="sm" variant="outline" onClick={saveUniverse} disabled={!universeName.trim() || !Object.keys(selected).length}>Save universe</Button>
      </div>
      {message && <p className="text-xs text-muted-foreground">{message}</p>}
    </div>
  );
}
