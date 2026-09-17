import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { simulationApi } from '@/services/simulation-api';
import type { SavedUniverse, SecurityItem, SecuritySelectionItem } from '@/services/simulation-api';
import { ChevronDown, ChevronUp, RefreshCw, Search, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

const messageFor = (error: unknown) => error instanceof Error ? error.message : String(error);

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSecurityIdsChange?: (ids: number[]) => void;
  compact?: boolean;
}

export function SecurityBrowser({ value, onChange, onSecurityIdsChange, compact = false }: Props) {
  const [items, setItems] = useState<SecurityItem[]>([]);
  const [selected, setSelected] = useState<Record<string, SecuritySelectionItem>>({});
  const [search, setSearch] = useState('');
  const [exchange, setExchange] = useState('');
  const [exchanges, setExchanges] = useState<string[]>([]);
  const [assetType, setAssetType] = useState('');
  const [sortBy, setSortBy] = useState('symbol');
  const [sortDir, setSortDir] = useState('asc');
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(compact ? 10 : 20);
  const [pageInput, setPageInput] = useState('1');
  const [universes, setUniverses] = useState<SavedUniverse[]>([]);
  const [universeName, setUniverseName] = useState('');
  const [message, setMessage] = useState('');
  const [selectingAll, setSelectingAll] = useState(false);
  const [showSelected, setShowSelected] = useState(false);
  const [selectedSearch, setSelectedSearch] = useState('');
  const [manualInput, setManualInput] = useState('');

  const symbols = useMemo(
    () => Array.from(new Set(value.split(',').map(item => item.trim().toUpperCase()).filter(Boolean))),
    [value],
  );
  const symbolSet = useMemo(() => new Set(symbols), [symbols]);
  const manualSymbols = useMemo(() => symbols.filter(symbol => !selected[symbol]), [selected, symbols]);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const filteredSelected = useMemo(() => {
    const needle = selectedSearch.trim().toLowerCase();
    return Object.values(selected).filter(item => !needle
      || item.symbol.toLowerCase().includes(needle)
      || item.name.toLowerCase().includes(needle));
  }, [selected, selectedSearch]);
  const visibleSelected = filteredSelected.slice(0, 200);

  const publish = useCallback((next: Record<string, SecuritySelectionItem>, extras: string[] = []) => {
    setSelected(next);
    const merged = [...Object.keys(next), ...extras.filter(symbol => !next[symbol])];
    onChange(Array.from(new Set(merged)).join(','));
    onSecurityIdsChange?.(Object.values(next).map(item => item.id));
  }, [onChange, onSecurityIdsChange]);

  const load = useCallback(async () => {
    try {
      const response = await simulationApi.listSecurities({
        search, exchange, asset_type: assetType, page, page_size: pageSize,
        sort_by: sortBy, sort_dir: sortDir,
      });
      setItems(response.items);
      setTotal(response.total);
      setExchanges(response.exchanges);
    } catch (error) {
      setMessage('Catalog unavailable: ' + messageFor(error));
    }
  }, [assetType, exchange, page, pageSize, search, sortBy, sortDir]);

  const loadUniverses = useCallback(async () => {
    try { setUniverses((await simulationApi.listUniverses()).universes); } catch { /* optional until catalog exists */ }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, 250);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => { loadUniverses(); }, [loadUniverses]);
  useEffect(() => { setPageInput(String(page)); }, [page]);
  useEffect(() => {
    const additions = items.filter(item => symbolSet.has(item.symbol) && !selected[item.symbol]);
    if (!additions.length) return;
    const next = { ...selected };
    additions.forEach(item => { next[item.symbol] = item; });
    setSelected(next);
    onSecurityIdsChange?.(Object.values(next).map(item => item.id));
  }, [items, onSecurityIdsChange, selected, symbolSet]);

  const changeFilter = (setter: (next: string) => void, next: string) => {
    setter(next);
    setPage(1);
  };
  const extrasWithout = (removed: Set<string> = new Set()) => symbols.filter(
    symbol => !selected[symbol] && !removed.has(symbol),
  );
  const toggle = (item: SecurityItem) => {
    const next = { ...selected };
    if (symbolSet.has(item.symbol)) {
      delete next[item.symbol];
      publish(next, symbols.filter(symbol => symbol !== item.symbol && !next[symbol]));
    } else {
      next[item.symbol] = item;
      publish(next, manualSymbols);
    }
  };
  const selectPage = () => {
    const next = { ...selected };
    items.forEach(item => { next[item.symbol] = item; });
    publish(next, manualSymbols);
  };
  const deselectPage = () => {
    const removed = new Set(items.map(item => item.symbol));
    const next = Object.fromEntries(Object.entries(selected).filter(([symbol]) => !removed.has(symbol)));
    publish(next, extrasWithout(removed));
  };
  const updateFilteredSelection = async (remove: boolean) => {
    setSelectingAll(true);
    setMessage(`${remove ? 'Removing' : 'Selecting'} ${total.toLocaleString()} matching securities...`);
    try {
      const response = await simulationApi.listSecuritySelection({
        search, exchange, asset_type: assetType, sort_by: sortBy, sort_dir: sortDir,
      });
      const affected = new Set(response.items.map(item => item.symbol));
      const next = remove
        ? Object.fromEntries(Object.entries(selected).filter(([symbol]) => !affected.has(symbol)))
        : { ...selected, ...Object.fromEntries(response.items.map(item => [item.symbol, item])) };
      publish(next, remove ? extrasWithout(affected) : manualSymbols);
      setMessage(`${remove ? 'Removed' : 'Selected'} ${response.total.toLocaleString()} matching securities.`);
    } catch (error) {
      setMessage('Selection failed: ' + messageFor(error));
    } finally {
      setSelectingAll(false);
    }
  };
  const synchronize = async () => {
    setMessage('Refreshing the US security directory from Nasdaq Trader...');
    try {
      const result = await simulationApi.syncSecurities();
      setMessage(`US directory refreshed: ${result.total.toLocaleString()} active records.`);
      await load();
    } catch (error) { setMessage('Directory refresh failed: ' + messageFor(error)); }
  };
  const saveUniverse = async () => {
    const ids = Object.values(selected).map(item => item.id);
    if (!universeName.trim() || !ids.length) return;
    try {
      await simulationApi.createUniverse(universeName.trim(), ids);
      setUniverseName('');
      await loadUniverses();
      setMessage('Saved stock list created.');
    } catch (error) { setMessage('Save failed: ' + messageFor(error)); }
  };
  const applyManual = () => {
    const additions = manualInput.split(/[\s,;]+/).map(item => item.trim().toUpperCase()).filter(Boolean);
    publish(selected, [...manualSymbols, ...additions]);
    setManualInput('');
  };
  const removeSymbol = (symbol: string) => {
    const next = { ...selected };
    delete next[symbol];
    publish(next, symbols.filter(value => value !== symbol && !next[value]));
  };
  const jumpToPage = () => {
    setPage(Math.min(pageCount, Math.max(1, Number.parseInt(pageInput, 10) || 1)));
  };

  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" value={search} onChange={event => changeFilter(setSearch, event.target.value)} placeholder="Search the local US directory by symbol or company" />
        </div>
        <select className="h-10 min-w-40 rounded-md border bg-background px-2 text-sm" value={exchange} onChange={event => changeFilter(setExchange, event.target.value)}>
          <option value="">All exchanges</option>
          {exchanges.map(value => <option key={value} value={value}>{value}</option>)}
        </select>
        <select className="h-10 rounded-md border bg-background px-2 text-sm" value={assetType} onChange={event => changeFilter(setAssetType, event.target.value)}>
          <option value="">All supported</option><option value="equity">Stocks / ADRs</option><option value="etf">ETFs</option>
        </select>
        <select className="h-10 rounded-md border bg-background px-2 text-sm" value={`${sortBy}:${sortDir}`} onChange={event => {
          const [field, direction] = event.target.value.split(':'); setSortBy(field); setSortDir(direction); setPage(1);
        }}>
          <option value="symbol:asc">Symbol A–Z</option><option value="symbol:desc">Symbol Z–A</option>
          <option value="name:asc">Company A–Z</option><option value="name:desc">Company Z–A</option>
          <option value="exchange:asc">Exchange A–Z</option><option value="asset_type:asc">Asset type</option>
        </select>
        <Button variant="outline" onClick={synchronize}><RefreshCw className="mr-1 h-4 w-4" />Refresh US directory</Button>
      </div>

      <p className="text-xs text-muted-foreground">Search and filters use the local Nasdaq Trader directory. They do not call Yahoo Finance.</p>
      <div className="max-h-[52vh] min-h-72 overflow-auto rounded border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="sticky top-0 z-10 bg-background shadow-sm">
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="w-12 px-3 py-2">Select</th><th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">Company</th><th className="px-3 py-2">Exchange</th><th className="px-3 py-2">Type</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id} className="cursor-pointer border-b last:border-0 hover:bg-muted/40" onClick={() => toggle(item)}>
                <td className="px-3 py-2"><Checkbox checked={symbolSet.has(item.symbol)} onCheckedChange={() => toggle(item)} onClick={event => event.stopPropagation()} /></td>
                <td className="px-3 py-2 font-mono font-semibold">{item.symbol}</td>
                <td className="max-w-[360px] px-3 py-2" title={item.name}><div className="truncate">{item.name}</div></td>
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{item.exchange}</td>
                <td className="px-3 py-2 text-muted-foreground">{item.asset_type === 'etf' ? 'ETF' : 'Stock / ADR'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!items.length && <p className="p-4 text-sm text-muted-foreground">No matching directory records. Refresh the directory or add manual tickers below.</p>}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Button size="sm" variant="outline" onClick={selectPage}>Select page</Button>
        <Button size="sm" variant="outline" onClick={deselectPage}>Deselect page</Button>
        <Button size="sm" variant="outline" disabled={selectingAll || !total} onClick={() => updateFilteredSelection(false)}>Select filtered ({total.toLocaleString()})</Button>
        <Button size="sm" variant="outline" disabled={selectingAll || !total} onClick={() => updateFilteredSelection(true)}>Deselect filtered</Button>
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(1)}>First</Button>
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>Previous</Button>
        <span>{page} / {pageCount}</span>
        <Button size="sm" variant="ghost" disabled={page >= pageCount} onClick={() => setPage(value => value + 1)}>Next</Button>
        <Button size="sm" variant="ghost" disabled={page >= pageCount} onClick={() => setPage(pageCount)}>Last</Button>
        <span>Page size</span>
        <select className="h-8 rounded border bg-background px-2" value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setPage(1); }}>
          {[20, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}
        </select>
        <Input className="h-8 w-16" value={pageInput} onChange={event => setPageInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') jumpToPage(); }} aria-label="Page number" />
        <Button size="sm" variant="ghost" onClick={jumpToPage}>Go</Button>
      </div>

      <div className="rounded border">
        <button type="button" className="flex w-full items-center justify-between px-3 py-2 text-left text-sm" onClick={() => setShowSelected(value => !value)}>
          <span className="font-medium">Selected securities <span className="text-muted-foreground">({symbols.length.toLocaleString()})</span></span>
          {showSelected ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {!showSelected && symbols.length > 0 && <p className="truncate border-t px-3 py-2 text-xs text-muted-foreground">{symbols.slice(0, 12).join(', ')}{symbols.length > 12 ? `, +${(symbols.length - 12).toLocaleString()} more` : ''}</p>}
        {showSelected && (
          <div className="space-y-2 border-t p-3">
            <div className="flex gap-2"><Input value={selectedSearch} onChange={event => setSelectedSearch(event.target.value)} placeholder="Search selected securities" /><Button variant="outline" onClick={() => publish({}, [])}>Clear all</Button></div>
            <div className="max-h-40 overflow-auto"><div className="flex flex-wrap gap-1.5">
              {visibleSelected.map(item => <button type="button" key={item.id} onClick={() => removeSymbol(item.symbol)} className="flex items-center gap-1 rounded-full border px-2 py-1 text-xs hover:bg-muted" title={item.name}>{item.symbol}<X className="h-3 w-3" /></button>)}
              {manualSymbols.filter(symbol => !selectedSearch || symbol.toLowerCase().includes(selectedSearch.toLowerCase())).map(symbol => <button type="button" key={symbol} onClick={() => removeSymbol(symbol)} className="flex items-center gap-1 rounded-full border border-dashed px-2 py-1 text-xs">{symbol}<X className="h-3 w-3" /></button>)}
            </div></div>
            {filteredSelected.length > visibleSelected.length && <p className="text-xs text-muted-foreground">Showing the first 200 of {filteredSelected.length.toLocaleString()} matching selected securities. Search to narrow the list.</p>}
            <div className="flex gap-2"><Input value={manualInput} onChange={event => setManualInput(event.target.value.toUpperCase())} onKeyDown={event => { if (event.key === 'Enter') applyManual(); }} placeholder="Manual fallback: AAPL, MSFT" /><Button variant="outline" onClick={applyManual} disabled={!manualInput.trim()}>Add</Button></div>
          </div>
        )}
      </div>

      <div className="space-y-2 rounded border p-3">
        <p className="text-sm font-medium">Saved stock lists</p>
        <p className="text-xs text-muted-foreground">Reuse the same selection later on the cache or simulation page.</p>
        <div className="flex flex-wrap gap-2">
          <select className="h-9 min-w-52 rounded-md border bg-background px-2 text-sm" defaultValue="" onChange={event => {
            const universe = universes.find(item => String(item.id) === event.target.value);
            if (!universe) return;
            publish(Object.fromEntries(universe.securities.map(item => [item.symbol, item])));
          }}>
            <option value="">Choose a saved list to load</option>
            {universes.map(item => <option key={item.id} value={item.id}>{item.name} ({item.securities.length.toLocaleString()})</option>)}
          </select>
          <Input className="max-w-64" value={universeName} onChange={event => setUniverseName(event.target.value)} placeholder="Name current selection" />
          <Button size="sm" variant="outline" onClick={saveUniverse} disabled={!universeName.trim() || !Object.keys(selected).length}>Save as new list</Button>
        </div>
      </div>
      {message && <p className="text-xs text-muted-foreground">{message}</p>}
    </div>
  );
}
