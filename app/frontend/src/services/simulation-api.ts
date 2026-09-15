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
  provider?: string;
  model?: string;
  llm_connection_id?: number;
}

export interface LlmModelOption {
  display_name: string;
  model: string;
}

export interface LlmProviderOption {
  id: string;
  display_name: string;
  credential_configured: boolean;
  models: LlmModelOption[];
}

export interface LlmConnectionOption {
  id: number;
  name: string;
  provider_type: string;
  vendor: 'openai' | 'anthropic' | 'opencode_go' | 'modelscope' | 'custom';
  protocol: 'openai_chat_completions' | 'openai_responses' | 'anthropic_messages';
  models: { model_id: string; display_name: string }[];
}

export interface SimPreflight {
  estimated_llm_calls: number;
  estimate_kind: 'cold_cache_upper_bound' | 'event_schedule_upper_bound';
  estimated_refresh_events: number;
  persona_count: number;
  event_reason_counts: Record<string, number>;
  persona_refresh_policy: PersonaRefreshPolicy;
  provider: string;
  model: string;
  benchmark: string;
  trading_days: number;
  enabled_models: string[];
  warnings: string[];
}

export interface PersonaRefreshPolicy {
  valuation_change_pct: number;
  max_age_days: number;
  retry_backoff_trading_days: number[];
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
  provider: string | null;
  protocol: string | null;
  model: string | null;
  llm_connection_id: number | null;
  llm_connection_name: string | null;
  llm_base_url: string | null;
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
  provider: string | null;
  protocol: string | null;
  model: string | null;
  llm_connection_id: number | null;
  llm_connection_name: string | null;
  llm_base_url: string | null;
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
  audit_available: boolean;
  persona_refresh_policy: PersonaRefreshPolicy | null;
}

export interface CycleTickerAudit {
  ticker: string;
  produced_count: number;
  neutral_count: number;
  abstained_count: number;
  failed_count: number;
  refresh_failed_count: number;
  target_weight: number | null;
  final_weight: number | null;
  order_count: number;
  fill_count: number;
}

export interface CycleAuditSummary {
  id: number;
  sim_run_id: number;
  cycle_number: number;
  signal_date: string;
  execution_date: string;
  status: 'completed' | 'failed';
  universe: string[];
  error_category: string | null;
  error_message: string | null;
  cash: number | null;
  nav: number | null;
  tickers: CycleTickerAudit[];
}

export interface AuditedSignal {
  model_name: string;
  ticker: string;
  date: string;
  value: number;
  status: 'produced' | 'abstained' | 'failed';
  failure: { category: string; message: string; retryable: boolean } | null;
  reasoning: string | null;
  metadata: Record<string, unknown>;
}

export interface CycleRecordAudit {
  fund: string;
  as_of: string;
  execution_date: string | null;
  universe: string[];
  marks: Record<string, number>;
  execution_prices: Record<string, number>;
  valuation_prices: Record<string, number>;
  skipped: { ticker: string; reason: string }[];
  strategies: {
    name: string;
    slice: number;
    signals: AuditedSignal[];
    convictions: Record<string, number>;
    weights: Record<string, number>;
  }[];
  persona_events?: PersonaEventAudit[];
  target_weights: Record<string, number>;
  clamps: { limit: string; ticker: string | null; before: number; after: number }[];
  final_weights: Record<string, number>;
  equity_before: number;
  cash_before: number;
  orders: { ticker: string; side: string; quantity: number; price: number }[];
  fills: { ticker: string; side: string; quantity: number; price: number; fee: number; total_amount: number | null }[];
  positions: Record<string, number>;
  cash: number;
  nav: number;
}

export interface PersonaEventAudit {
  ticker: string;
  persona: string;
  model_identity: string;
  prompt_identity: string;
  provenance: 'refreshed' | 'reused' | 'expired' | 'unavailable';
  trigger_reasons: string[];
  source_signal_date: string | null;
  age_days: number | null;
  attempt_status: 'not_attempted' | 'produced' | 'failed' | 'abstained';
  failure: { category: string; message: string; retryable: boolean } | null;
  prompt_key: string | null;
  snapshot_hash: string | null;
  failure_count: number;
  next_retry_cycle: number | null;
}

export interface CycleAuditDetail extends CycleAuditSummary {
  record: CycleRecordAudit | null;
}

export interface CycleAuditList {
  sim_run_id: number;
  audit_available: boolean;
  items: CycleAuditSummary[];
  limit: number;
  offset: number;
}

export interface SimRunSummary {
  id: number;
  name: string;
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  benchmark: string | null;
  provider: string | null;
  protocol: string | null;
  model: string | null;
  llm_connection_id: number | null;
  llm_connection_name: string | null;
  llm_base_url: string | null;
  status: string;
  current_day: number;
  total_days: number;
  final_nav: number | null;
  created_at: string;
  completed_at?: string | null;
  error_message?: string | null;
  warnings?: string[];
  models?: string[];
  persona_refresh_policy: PersonaRefreshPolicy | null;
}

export const simulationApi = {
  async listLlmModels(): Promise<{ providers: LlmProviderOption[] }> {
    const res = await fetch(`${API_BASE_URL}/dashboard/llm/models`);
    await requireOk(res);
    return res.json();
  },

  async listLlmOptions(): Promise<{ providers: LlmConnectionOption[] }> {
    const res = await fetch(`${API_BASE_URL}/dashboard/llm/options`);
    await requireOk(res);
    return res.json();
  },

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

  async listCycleAudits(
    simId: number,
    filters: { date?: string; ticker?: string } = {},
  ): Promise<CycleAuditList> {
    const params = new URLSearchParams();
    if (filters.date) params.set('date', filters.date);
    if (filters.ticker) params.set('ticker', filters.ticker);
    const query = params.toString();
    const res = await fetch(`${API_BASE_URL}/dashboard/sim/${simId}/cycles${query ? `?${query}` : ''}`);
    await requireOk(res);
    return res.json();
  },

  async getCycleAudit(simId: number, cycleId: number): Promise<CycleAuditDetail> {
    const res = await fetch(`${API_BASE_URL}/dashboard/sim/${simId}/cycles/${cycleId}`);
    await requireOk(res);
    return res.json();
  },

  async listSimRuns(): Promise<{ runs: SimRunSummary[] }> {
    const res = await fetch(`${API_BASE_URL}/dashboard/sim/runs`);
    await requireOk(res);
    return res.json();
  },
};
