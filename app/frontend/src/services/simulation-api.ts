const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export type ApiError = Error & { status?: number; detail?: unknown };

async function requireOk(res: Response): Promise<void> {
  if (res.ok) return;
  const body = await res.json().catch(() => ({}));
  const detail = body.detail;
  const error = new Error(
    typeof detail === 'string' ? detail : detail?.message || `Request failed (${res.status})`
  ) as ApiError;
  error.status = res.status;
  error.detail = detail;
  throw error;
}

export interface CacheItem {
  prices: { min: string; max: string; count: number } | null;
  metrics: { min: string; max: string; count: number } | null;
  earnings: { min: string; max: string; count: number } | null;
  filing_date_note?: string;
}

export interface CacheListResponse {
  cached: Record<string, CacheItem>;
}

export interface FetchCacheRequest {
  tickers: string[];
  benchmark?: string;
  start_date: string;
  end_date: string;
}

export interface FetchCacheResult {
  results: Record<string, { prices: number; metrics: number; earnings: number; error: string | null; warnings: string[] }>;
  benchmark: { ticker: string; prices: number; error: string | null } | null;
}

export interface SimRunRequest {
  tickers: string[];
  benchmark?: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  name?: string;
  confirm_cost?: boolean;
}

export interface SimPreflight {
  estimated_llm_calls: number;
  estimate_kind: 'cold_cache_upper_bound';
  provider: string;
  model: string;
  benchmark: string;
  trading_days: number;
  enabled_models: string[];
  warnings: string[];
}

export interface SimStatus {
  id: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  current_day: number;
  total_days: number;
  final_nav: number | null;
  error_message?: string | null;
  completed_at?: string | null;
  warnings?: string[];
  models?: string[];
}

export interface SimNavPoint {
  date: string;
  nav: number;
  cash: number;
  equity: number;
  benchmark_nav: number | null;
}

export interface SimTrade {
  id: number;
  date: string;
  ticker: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  total_amount: number;
}

export interface SimResult {
  id: number;
  name: string;
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  benchmark: string | null;
  final_nav: number;
  total_return_pct: number;
  benchmark_return_pct: number | null;
  excess_return_pct: number | null;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  nav_curve: SimNavPoint[];
  trades: SimTrade[];
  trade_count: number;
  buy_count: number;
  sell_count: number;
  total_days: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  error_message?: string | null;
  completed_at?: string | null;
  warnings?: string[];
  models?: string[];
}

export interface SimRunSummary {
  id: number;
  name: string;
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  benchmark: string | null;
  status: string;
  current_day: number;
  total_days: number;
  final_nav: number | null;
  created_at: string;
  completed_at?: string | null;
  error_message?: string | null;
  warnings?: string[];
  models?: string[];
}

export const simulationApi = {
  async fetchCache(req: FetchCacheRequest): Promise<FetchCacheResult> {
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/fetch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    await requireOk(res);
    return res.json();
  },

  async listCache(): Promise<CacheListResponse> {
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/list`);
    await requireOk(res);
    return res.json();
  },

  async deleteCache(ticker: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/${encodeURIComponent(ticker)}`, {
      method: 'DELETE',
    });
    await requireOk(res);
  },

  async preflightSim(req: SimRunRequest): Promise<SimPreflight> {
    const res = await fetch(`${API_BASE_URL}/dashboard/sim/preflight`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    await requireOk(res);
    return res.json();
  },

  async runSim(req: SimRunRequest): Promise<{ sim_id: number; status: string }> {
    const res = await fetch(`${API_BASE_URL}/dashboard/sim/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    await requireOk(res);
    return res.json();
  },

  async getSimStatus(simId: number): Promise<SimStatus> {
    const res = await fetch(`${API_BASE_URL}/dashboard/sim/status/${simId}`);
    await requireOk(res);
    return res.json();
  },

  async getSimResult(simId: number): Promise<SimResult> {
    const res = await fetch(`${API_BASE_URL}/dashboard/sim/result/${simId}`);
    await requireOk(res);
    return res.json();
  },

  async listSimRuns(): Promise<{ runs: SimRunSummary[] }> {
    const res = await fetch(`${API_BASE_URL}/dashboard/sim/runs`);
    await requireOk(res);
    return res.json();
  },
};
