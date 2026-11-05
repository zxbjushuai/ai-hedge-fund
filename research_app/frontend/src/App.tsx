import { useCallback, useState } from 'react';
import { useTheme } from 'next-themes';
import { Activity, Database, PanelsTopLeft, Plug, Sun, Moon } from 'lucide-react';
import { SimulationWorkspace, type DataIntent } from './components/backtest/simulation-workspace';
import { CachePanel } from './components/backtest/cache-panel';
import { LlmProvidersSettings } from './components/settings/llm-providers';
import { cacheDetails } from './lib/cache-details';

export default function App() {
  const [page, setPage] = useState('simulation');
  const [visited, setVisited] = useState(new Set(['simulation']));
  const [revision, setRevision] = useState(0);
  const [intent, setIntent] = useState<DataIntent>();
  const { resolvedTheme, setTheme } = useTheme();
  const refresh = useCallback(() => { cacheDetails.invalidate(); setRevision(value => value + 1); }, []);
  const navigate = (next: string) => {
    if (next === 'simulation' && page === 'data') refresh();
    setVisited(old => new Set([...old, next]));
    setPage(next);
  };
  return <div className="research-shell">
    <a className="skip-link" href="#workspace-main">Skip to content</a>
    <aside className="workspace-nav">
      <div className="brand"><PanelsTopLeft size={24} /><div>Research<span>Investment workspace</span></div></div>
      <nav aria-label="Main navigation">{[
        { id: 'simulation', label: 'Simulation', icon: Activity, detail: 'Run an experiment' },
        { id: 'data', label: 'Data', icon: Database, detail: 'Prepare your inputs' },
        { id: 'providers', label: 'Providers', icon: Plug, detail: 'Connect your models' },
      ].map(({ id, label, icon: Icon, detail }) => <button key={id} aria-current={page === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon size={19} /><span>{label}<small>{detail}</small></span></button>)}</nav>
      <div className="nav-footer"><p>Local data. Explicit runs.</p><button onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}>{resolvedTheme === 'dark' ? <Sun size={17} /> : <Moon size={17} />} {resolvedTheme === 'dark' ? 'Light appearance' : 'Dark appearance'}</button></div>
    </aside>
    <main id="workspace-main" tabIndex={-1}>
      <div hidden={page !== 'simulation'}><SimulationWorkspace active={page === 'simulation'} revision={revision} onRefresh={refresh} onProviders={() => navigate('providers')} onData={value => { setIntent(value); navigate('data'); }} /></div>
      {visited.has('data') && <div hidden={page !== 'data'}><header className="page-heading"><div><h1>Data</h1><p>Acquire market history, then inspect what is ready to use.</p></div></header><CachePanel intent={intent} onChanged={refresh} /></div>}
      {visited.has('providers') && <div hidden={page !== 'providers'}><header className="page-heading"><div><h1>Providers</h1><p>Manage independent connections and the models available to your runs.</p></div></header><LlmProvidersSettings /></div>}
    </main>
  </div>;
}
