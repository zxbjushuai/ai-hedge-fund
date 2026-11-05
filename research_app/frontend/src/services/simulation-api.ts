const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export type ApiError = Error & { status?: number; detail?: unknown };

async function requireOk(res: Response): Promise<void> {
  if (res.ok) return;
  const body = await res.json().catch(() => ({}));
  const detail = body.detail;
  const validationMessage = Array.isArray(detail)
    ? detail.map(item => {
      const location = Array.isArray(item?.loc) ? item.loc.filter((part: unknown) => part !== 'body').join('.') : '';
      return `${location ? `${location}: ` : ''}${item?.msg || 'invalid value'}`;
    }).join('; ')
    : null;
  const error = new Error(
    typeof detail === 'string' ? detail : validationMessage || detail?.message || `Request failed (${res.status})`
  ) as ApiError;
  error.status = res.status;
  error.detail = detail;
  throw error;
}

export interface CacheItem {
  prices: { min: string; max: string; count: number; price_modes?: string[] } | null;
  metrics: { min: string; max: string; count: number } | null;
  earnings: { min: string; max: string; count: number } | null;
  coverage?: { status: string; requested_start: string; requested_end: string; actual_start: string | null; actual_end: string | null; missing_sessions: number; fetched_at: string } | null;
  filing_date_note?: string;
}

export interface SecurityItem {
  id: number;
  market: 'US';
  symbol: string;
  data_symbol: string;
  name: string;
  exchange: string;
  asset_type: 'equity' | 'etf' | 'other';
  currency: 'USD';
  active: boolean;
  selectable: boolean;
  catalog_source: string;
  synced_at: string;
}

export interface SecurityListResponse {
  items: SecurityItem[];
  total: number;
  page: number;
  page_size: number;
  exchanges: string[];
}

export type SecuritySelectionItem = Pick<SecurityItem, 'id' | 'symbol' | 'name' | 'exchange' | 'asset_type'>;

export interface SecuritySelectionResponse {
  items: SecuritySelectionItem[];
  total: number;
}

export interface SavedUniverse {
  id: number;
  name: string;
  market: 'US';
  archived: boolean;
  securities: SecurityItem[];
}

export interface CacheJobItemResult {
  status: 'complete' | 'partial' | 'no_data' | 'failed' | 'skipped';
  count?: number;
  actual_start?: string | null;
  actual_end?: string | null;
  missing_sessions?: number;
  price_mode?: string;
  error_category?: string;
  error?: string;
  reason?: string;
}

export interface CacheJob {
  id: string;
  status: 'pending' | 'running' | 'cancelling' | 'completed' | 'partial' | 'failed' | 'cancelled';
  tickers: string[];
  benchmark: string;
  start_date: string;
  end_date: string;
  data_types: string[];
  progress: { total: number; completed: number; failed: number; cancelled: number };
  items: Record<string, {
    ticker: string;
    prices?: CacheJobItemResult | null;
    metrics?: CacheJobItemResult | null;
    earnings?: CacheJobItemResult | null;
    warnings?: string[];
  }>;
}

export interface CacheListResponse {
  cached: Record<string, CacheItem>;
}

export interface CachedSecurityItem extends CacheItem {
  ticker: string;
  name: string;
  exchange: string;
  asset_type: string;
  latest_close: number | null;
  latest_adjusted_close: number | null;
  latest_volume: number | null;
  latest_date: string | null;
}

export interface CachedSecurityListResponse {
  items: CachedSecurityItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface CachedSecurityDetail {
  ticker: string;
  security: SecurityItem | null;
  prices: Array<{
    date: string; open: number; high: number; low: number; close: number;
    adjusted_close: number | null; volume: number; dividend: number;
    split_ratio: number; source: string; price_mode: string;
  }>;
  metrics: Array<{
    report_period: string; filing_date: string; filing_date_source: string;
    data: Record<string, unknown>;
  }>;
  earnings: Array<{
    report_period: string; announcement_date: string; actual_eps: number | null;
    estimated_eps: number | null; surprise_pct: number | null; source: string;
  }>;
  coverage_history: Array<{
    data_kind: string; requested_start: string; requested_end: string;
    actual_start: string | null; actual_end: string | null; row_count: number;
    missing_sessions: number; status: string; error_category: string | null;
    error_message: string | null; fetched_at: string;
  }>;
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
  llm_concurrency?: number;
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
  activity?: SimActivity;
  execution_config?: { llm_concurrency: number; preflight?: { estimated_llm_calls: number } } | null;
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

export interface SimActivity {
  available: boolean;
  stage?: string;
  signal_date?: string;
  execution_date?: string;
  concurrency?: number;
  queued?: number;
  updated_at?: string;
  error?: string | null;
  active?: { call_id: string; ticker: string; persona: string; stage?: string; elapsed_seconds: number }[];
  counts?: Record<string, number>;
  recent?: Record<string, unknown>[];
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
  valuation_date?: string | null;
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
  final_nav: number | null;
  total_return_pct: number | null;
  benchmark_return_pct: number | null;
  excess_return_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
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
  corporate_actions?: {
    ticker: string;
    action_type: 'split' | 'dividend';
    value: number;
    shares_before: number;
    shares_after: number;
    cash_amount: number;
  }[];
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
  async syncSecurities(): Promise<{ total: number; created: number; updated: number; deactivated: number }> {
    const res = await fetch(`${API_BASE_URL}/dashboard/securities/sync`, { method: 'POST' });
    await requireOk(res);
    return res.json();
  },

  async listSecurities(params: { search?: string; exchange?: string; asset_type?: string; page?: number; page_size?: number; sort_by?: string; sort_dir?: string } = {}): Promise<SecurityListResponse> {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
    const res = await fetch(`${API_BASE_URL}/dashboard/securities?${query}`);
    await requireOk(res);
    return res.json();
  },

  async listSecuritySelection(params: { search?: string; exchange?: string; asset_type?: string; sort_by?: string; sort_dir?: string } = {}): Promise<SecuritySelectionResponse> {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
    const res = await fetch(`${API_BASE_URL}/dashboard/securities/selection?${query}`);
    await requireOk(res);
    return res.json();
  },

  async listUniverses(): Promise<{ universes: SavedUniverse[] }> {
    const res = await fetch(`${API_BASE_URL}/dashboard/universes`);
    await requireOk(res);
    return res.json();
  },

  async createUniverse(name: string, securityIds: number[]): Promise<SavedUniverse> {
    const res = await fetch(`${API_BASE_URL}/dashboard/universes`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, security_ids: securityIds }),
    });
    await requireOk(res);
    return res.json();
  },

  async createCacheJob(req: {
    selection: { security_ids: number[] } | { universe_id: number } | { filter: Record<string, unknown> } | { tickers: string[] };
    benchmark: string; start_date: string; end_date: string;
    data_types: string[]; force?: boolean;
  }): Promise<CacheJob> {
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/jobs`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(req),
    });
    await requireOk(res);
    return res.json();
  },

  async getCacheJob(id: string): Promise<CacheJob> {
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/jobs/${id}`);
    await requireOk(res);
    return res.json();
  },

  async cancelCacheJob(id: string): Promise<CacheJob> {
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/jobs/${id}/cancel`, { method: 'POST' });
    await requireOk(res);
    return res.json();
  },

  async retryCacheJob(id: string): Promise<CacheJob> {
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/jobs/${id}/retry`, { method: 'POST' });
    await requireOk(res);
    return res.json();
  },

  async listCachedSecurities(params: {
    search?: string; status?: string; price_mode?: string; page?: number;
    page_size?: number; sort_by?: string; sort_dir?: string;
  } = {}): Promise<CachedSecurityListResponse> {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/securities?${query}`);
    await requireOk(res);
    return res.json();
  },

  async getCachedSecurity(ticker: string, params: { start_date?: string; end_date?: string } = {}): Promise<CachedSecurityDetail> {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value) query.set(key, value); });
    const suffix = query.size ? `?${query}` : '';
    const res = await fetch(`${API_BASE_URL}/dashboard/cache/securities/${encodeURIComponent(ticker)}${suffix}`);
    await requireOk(res);
    return res.json();
  },
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
