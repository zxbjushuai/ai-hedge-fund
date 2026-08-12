import { cn } from '@/lib/utils';
import { Database, Play } from 'lucide-react';
import { useState } from 'react';
import { CachePanel } from './cache-panel';
import { SimulationPanel } from './simulation-panel';

interface BacktestProps {
  className?: string;
}

interface NavItem {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

export function Backtest({ className }: BacktestProps) {
  const [selected, setSelected] = useState('cache');

  const navItems: NavItem[] = [
    { id: 'cache', label: 'Data Cache', icon: Database },
    { id: 'sim', label: 'Run Simulation', icon: Play },
  ];

  return (
    <div className={cn("flex justify-center h-full overflow-hidden bg-panel", className)}>
      <div className="flex w-full max-w-7xl mx-auto">
        <div className="w-60 bg-panel flex-shrink-0">
          <div className="p-4 border-b">
            <h1 className="text-lg font-semibold text-primary">Backtest</h1>
          </div>
          <nav className="p-2">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isSelected = selected === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setSelected(item.id)}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2 text-left rounded-md text-sm transition-colors",
                    isSelected
                      ? "active-bg text-blue-500"
                      : "text-primary hover-item"
                  )}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" />
                  <span className="truncate">{item.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="flex-1 overflow-auto bg-panel">
          <div className="p-8 max-w-4xl">
            {selected === 'cache' && <CachePanel />}
            {selected === 'sim' && <SimulationPanel />}
          </div>
        </div>
      </div>
    </div>
  );
}
