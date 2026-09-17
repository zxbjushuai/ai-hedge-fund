import { useState } from 'react';
import { SimulationPanel } from './components/backtest/simulation-panel';
import { CachePanel } from './components/backtest/cache-panel';
import { LlmProvidersSettings } from './components/settings/llm-providers';
import { Button } from './components/ui/button';

export default function App() {
  const [page, setPage] = useState('simulation');
  return <div className="min-h-screen bg-background text-foreground">
    <header className="border-b px-6 py-4">
      <h1 className="mb-3 text-xl font-semibold">Research workspace</h1>
      <nav className="flex gap-2" aria-label="Main navigation">
        {Object.entries({ simulation: 'Simulation', data: 'Data', providers: 'Model providers' }).map(([id, label]) =>
          <Button key={id} variant={page === id ? 'default' : 'outline'} onClick={() => setPage(id)}>{label}</Button>)}
      </nav>
    </header>
    <main className="mx-auto max-w-screen-2xl p-6">
      <div hidden={page !== 'simulation'}><SimulationPanel /></div>
      <div hidden={page !== 'data'}><CachePanel /></div>
      <div hidden={page !== 'providers'}><LlmProvidersSettings /></div>
    </main>
  </div>;
}
