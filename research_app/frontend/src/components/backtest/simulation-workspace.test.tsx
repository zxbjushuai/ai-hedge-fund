import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SimulationWorkspace } from './simulation-workspace';
import { simulationApi, type CachedSecurityDetail, type CachedSecurityItem, type SimResult } from '@/services/simulation-api';
import { cacheDetails } from '@/lib/cache-details';

const days = ['2024-01-05', '2024-01-08', '2024-01-09', '2024-01-10'];
const details = (ticker: string, dates = days): CachedSecurityDetail => ({ ticker, security: null,
  prices: dates.map(date => ({ date, open: 10, high: 10, low: 10, close: 10, adjusted_close: 10, volume: 1, dividend: 0, split_ratio: 0, source: 'test', price_mode: 'raw' })),
  metrics: Array.from({ length: 4 }, (_, i) => ({ report_period: `2023-0${i + 1}-01`, filing_date: `2023-0${i + 1}-15`, filing_date_source: 'test', data: {} })),
  earnings: [{ report_period: '2023-09-30', announcement_date: '2023-11-01', actual_eps: 2, estimated_eps: 1, surprise_pct: 100, source: 'test' }], coverage_history: [] });
const item = (ticker: string): CachedSecurityItem => ({ ticker, name: `${ticker} company`, exchange: 'NYSE', asset_type: 'equity', latest_close: 10, latest_adjusted_close: 10, latest_volume: 1, latest_date: days[3], prices: { min: days[0], max: days[3], count: 4, price_modes: ['raw'] }, metrics: { min: '2023-01-01', max: '2023-04-01', count: 4 }, earnings: { min: '2023-11-01', max: '2023-11-01', count: 1 } });
const props = () => ({ active: true, revision: 0, onRefresh: vi.fn(), onData: vi.fn(), onProviders: vi.fn() });
const preflight = { estimated_llm_calls: 3, estimate_kind: 'event_schedule_upper_bound' as const, estimated_refresh_events: 1, persona_count: 3, event_reason_counts: { bootstrap: 1 }, persona_refresh_policy: { valuation_change_pct: 20, max_age_days: 90, retry_backoff_trading_days: [1, 2, 4, 5] }, provider: 'test', model: 'small', benchmark: 'SPY', trading_days: 4, enabled_models: ['buffett'], warnings: [] };

beforeEach(() => {
  localStorage.clear();
  cacheDetails.invalidate();
  vi.spyOn(simulationApi, 'listCache').mockResolvedValue({ cached: { AAPL: item('AAPL'), MSFT: item('MSFT'), SPY: item('SPY') } });
  vi.spyOn(simulationApi, 'listCachedSecurities').mockResolvedValue({ items: [item('AAPL'), item('MSFT')], total: 2, page: 1, page_size: 10 });
  vi.spyOn(simulationApi, 'getCachedSecurity').mockImplementation(async ticker => details(ticker));
  vi.spyOn(simulationApi, 'listUniverses').mockResolvedValue({ universes: [] });
  vi.spyOn(simulationApi, 'listSimRuns').mockResolvedValue({ runs: [] });
  vi.spyOn(simulationApi, 'listLlmOptions').mockResolvedValue({ providers: [{ id: 12, name: 'Test connection', provider_type: 'openai', vendor: 'openai', protocol: 'openai_chat_completions', models: [{ model_id: 'small', display_name: 'Small' }] }] });
  vi.spyOn(simulationApi, 'preflightSim').mockResolvedValue(preflight);
  vi.spyOn(simulationApi, 'runSim').mockResolvedValue({ sim_id: 42, status: 'running' });
  vi.spyOn(simulationApi, 'getSimStatus').mockResolvedValue({ id: 42, status: 'completed', current_day: 3, total_days: 3, final_nav: 100000, provider: 'test', protocol: null, model: 'small', llm_connection_id: 12, llm_connection_name: 'Test connection', llm_base_url: null });
});
afterEach(cleanup);

it('does not offer legacy direct Go connections for a new Web simulation', async () => {
  vi.mocked(simulationApi.listLlmOptions).mockResolvedValue({ providers: [
    { id: 1, name: 'Legacy direct Go', provider_type: 'opencode_go', vendor: 'opencode_go',
      protocol: 'openai_chat_completions', models: [{ model_id: 'old', display_name: 'Old' }] },
    { id: 12, name: 'Relay connection', provider_type: 'custom', vendor: 'custom',
      protocol: 'openai_responses', models: [{ model_id: 'small', display_name: 'Small' }] },
  ] });
  render(<SimulationWorkspace {...props()} />);
  await screen.findByRole('option', { name: 'Relay connection' });
  expect(screen.queryByRole('option', { name: 'Legacy direct Go' })).toBeNull();
  expect(simulationApi.runSim).not.toHaveBeenCalled();
});

it('restores a saved run without submitting and shows concurrent tasks', async () => {
  localStorage.setItem('simulation.activeRun', '42');
  vi.mocked(simulationApi.getSimStatus).mockResolvedValue({
    id: 42, status: 'running', current_day: 1, total_days: 10, final_nav: null,
    provider: 'test', protocol: null, model: 'small', llm_connection_id: 12,
    llm_connection_name: 'Test', llm_base_url: null,
    activity: { available: true, stage: 'signals', concurrency: 4, queued: 2,
      active: [{ call_id: 'a', ticker: 'AAA', persona: 'buffett', elapsed_seconds: 5 },
               { call_id: 'b', ticker: 'BBB', persona: 'graham', elapsed_seconds: 3 }],
      counts: { http_attempt: 2 } },
  });
  render(<SimulationWorkspace {...props()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Running' }));
  await screen.findByText('buffett');
  expect(screen.getByText('graham')).toBeTruthy();
  expect(simulationApi.getSimStatus).toHaveBeenCalledWith(42);
  expect(simulationApi.runSim).not.toHaveBeenCalled();
});
async function configure() {
  fireEvent.click(await screen.findByLabelText('Select AAPL'));
  await waitFor(() => expect((screen.getByLabelText('Start date') as HTMLInputElement).value).toBe(days[0]));
  fireEvent.change(screen.getByLabelText('Connection'), { target: { value: '12' } });
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'small' } });
  await waitFor(() => expect((screen.getByRole('button', { name: 'Review simulation' }) as HTMLButtonElement).disabled).toBe(false));
}

it('starts empty, never fetches catalog, and submits only once after explicit review', async () => {
  const catalog = vi.spyOn(simulationApi, 'listSecurities');
  const fetch = vi.spyOn(simulationApi, 'createCacheJob');
  render(<SimulationWorkspace {...props()} />);
  expect((screen.getByLabelText('Start date') as HTMLInputElement).value).toBe('');
  await configure();
  fireEvent.click(screen.getByRole('button', { name: 'Review simulation' }));
  await screen.findByRole('button', { name: 'Confirm and run' });
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Review simulation' }));
  fireEvent.change(screen.getByLabelText('Model concurrency'), { target: { value: '9' } });
  expect((screen.getByRole('button', { name: 'Confirm and run' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Model concurrency'), { target: { value: '4' } });
  expect(simulationApi.runSim).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm and run' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm and run' }));
  await waitFor(() => expect(simulationApi.runSim).toHaveBeenCalledTimes(1));
  expect(simulationApi.runSim).toHaveBeenCalledWith(expect.objectContaining({ tickers: ['AAPL'], llm_connection_id: 12, model: 'small', confirm_cost: true, llm_concurrency: 4 }));
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Running simulation' }));
  expect(localStorage.getItem('simulation.activeRun')).toBe('42');
  expect(catalog).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
});

it('preserves manually edited dates when adding securities and invalidates review', async () => {
  render(<SimulationWorkspace {...props()} />); await configure();
  fireEvent.click(screen.getByRole('button', { name: 'Review simulation' })); await screen.findByRole('button', { name: 'Confirm and run' });
  fireEvent.change(screen.getByLabelText('Start date'), { target: { value: days[1] } });
  expect(screen.queryByRole('button', { name: 'Confirm and run' })).toBeNull();
  fireEvent.click(screen.getByLabelText('Select MSFT'));
  await waitFor(() => expect(screen.getByText('Coverage loaded')).toBeTruthy());
  expect((screen.getByLabelText('Start date') as HTMLInputElement).value).toBe(days[1]);
});

it('keeps uncached saved-universe members visible and blocks review', async () => {
  vi.mocked(simulationApi.listUniverses).mockResolvedValue({ universes: [{ id: 1, name: 'Missing member', market: 'US', archived: false, securities: [{ id: 9, symbol: 'NEW', name: 'New', market: 'US', data_symbol: 'NEW', exchange: 'NYSE', asset_type: 'equity', currency: 'USD', active: true, selectable: true, catalog_source: 'test', synced_at: '' }] }] });
  render(<SimulationWorkspace {...props()} />);
  await screen.findByRole('option', { name: 'Missing member' });
  fireEvent.change(screen.getByLabelText('Load saved universe'), { target: { value: '1' } });
  expect(screen.getByText(/No cached prices for: NEW/)).toBeTruthy();
  expect((screen.getByRole('button', { name: 'Review simulation' }) as HTMLButtonElement).disabled).toBe(true);
});

it('shows backend preflight errors and never launches on failure', async () => {
  vi.mocked(simulationApi.preflightSim).mockRejectedValue(Object.assign(new Error('preflight failed'), { detail: { errors: ['SPY: refresh prices'] } }));
  render(<SimulationWorkspace {...props()} />); await configure();
  fireEvent.click(screen.getByRole('button', { name: 'Review simulation' }));
  await screen.findByText('SPY: refresh prices'); expect(simulationApi.runSim).not.toHaveBeenCalled();
});

it('requires warning acknowledgement and exposes polling failures without resubmitting', async () => {
  vi.mocked(simulationApi.preflightSim).mockResolvedValue({ ...preflight, warnings: ['Financial history is incomplete'] });
  vi.mocked(simulationApi.getSimStatus).mockRejectedValueOnce(new Error('offline'));
  render(<SimulationWorkspace {...props()} />); await configure();
  fireEvent.click(screen.getByRole('button', { name: 'Review simulation' }));
  const confirm = await screen.findByRole('button', { name: 'Confirm and run' });
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByLabelText(/I understand the data/)); fireEvent.click(confirm);
  const retry = await screen.findByRole('button', { name: 'Retry status' });
  fireEvent.click(retry); await screen.findByText('Simulation #42: completed');
  expect(simulationApi.runSim).toHaveBeenCalledTimes(1);
});

it('ignores late deselected responses and invalidates review after data changes', async () => {
  let release!: (value: CachedSecurityDetail) => void;
  vi.mocked(simulationApi.getCachedSecurity).mockImplementation(ticker => ticker === 'MSFT' ? new Promise(resolve => { release = resolve; }) : Promise.resolve(details(ticker)));
  const initial = props(); const view = render(<SimulationWorkspace {...initial} />); await configure();
  fireEvent.click(screen.getByLabelText('Select MSFT'));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  fireEvent.click(screen.getByLabelText('Select MSFT'));
  release(details('MSFT', ['2026-01-01']));
  await waitFor(() => expect(screen.getByText('Coverage loaded')).toBeTruthy());
  expect((screen.getByLabelText('Start date') as HTMLInputElement).value).toBe(days[0]);
  fireEvent.click(screen.getByRole('button', { name: 'Review simulation' })); await screen.findByRole('button', { name: 'Confirm and run' });
  view.rerender(<SimulationWorkspace {...initial} revision={1} />);
  expect(screen.queryByRole('button', { name: 'Confirm and run' })).toBeNull();
});

it('keeps an active run when hidden and does not resubmit on return', async () => {
  let release!: (value: Awaited<ReturnType<typeof simulationApi.getSimStatus>>) => void;
  vi.mocked(simulationApi.getSimStatus).mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const initial = props(); const view = render(<SimulationWorkspace {...initial} />); await configure();
  fireEvent.click(screen.getByRole('button', { name: 'Review simulation' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm and run' }));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  view.rerender(<SimulationWorkspace {...initial} active={false} />);
  release({ id: 42, status: 'completed', current_day: 3, total_days: 3, final_nav: 100000, provider: 'test', protocol: null, model: 'small', llm_connection_id: 12, llm_connection_name: 'Test connection', llm_base_url: null });
  await screen.findByText('Simulation #42: completed');
  view.rerender(<SimulationWorkspace {...initial} active />);
  expect(simulationApi.runSim).toHaveBeenCalledTimes(1);
});

it('passes selected tickers and user dates to Data without fetching', async () => {
  const initial = props(); render(<SimulationWorkspace {...initial} />); await configure();
  fireEvent.change(screen.getByLabelText('Start date'), { target: { value: days[1] } });
  fireEvent.click(screen.getByRole('button', { name: 'Open Data' }));
  expect(initial.onData).toHaveBeenCalledWith(expect.objectContaining({ tickers: ['AAPL'], benchmark: 'SPY', start: days[1], end: days[3] }));
  expect(simulationApi.preflightSim).not.toHaveBeenCalled();
});

it('renders old history/results with null benchmark, provider and audit data', async () => {
  vi.mocked(simulationApi.listSimRuns).mockResolvedValue({ runs: [{ id: 1, name: '', tickers: ['AAPL'], start_date: days[0], end_date: days[3], initial_capital: 100000, status: 'completed', final_nav: 100000, benchmark: null, provider: null, protocol: null, model: null, llm_connection_id: null, llm_connection_name: null, llm_base_url: null, created_at: '', current_day: 3, total_days: 3, persona_refresh_policy: null }] });
  const old = { id: 1, name: '', tickers: ['AAPL'], start_date: days[0], end_date: days[3], initial_capital: 100000, status: 'completed', final_nav: 100000, benchmark: null, provider: null, protocol: null, model: null, llm_connection_id: null, llm_connection_name: null, llm_base_url: null, total_return_pct: 0, benchmark_return_pct: null, excess_return_pct: null, max_drawdown_pct: 0, sharpe_ratio: 0, nav_curve: [{ date: days[0], nav: 100000, cash: 100000, equity: 0, benchmark_nav: null }], trades: [], trade_count: 0, buy_count: 0, sell_count: 0, total_days: 1, audit_available: false, persona_refresh_policy: null } as SimResult;
  vi.spyOn(simulationApi, 'getSimResult').mockResolvedValue(old);
  render(<SimulationWorkspace {...props()} />);
  fireEvent.click(screen.getByRole('button', { name: 'History' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Sim #1' }));
  await screen.findByRole('heading', { name: 'Simulation #1' });
  expect(screen.queryByText(/Failed to load result/)).toBeNull();
});

it('discards a preflight response when data changed while it was pending', async () => {
  let release!: (value: typeof preflight) => void;
  vi.mocked(simulationApi.preflightSim).mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const initial = props(); const view = render(<SimulationWorkspace {...initial} />); await configure();
  fireEvent.click(screen.getByRole('button', { name: 'Review simulation' }));
  view.rerender(<SimulationWorkspace {...initial} revision={1} />);
  release(preflight);
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Checking…' })).toBeNull());
  expect(screen.queryByRole('button', { name: 'Confirm and run' })).toBeNull();
  expect(simulationApi.runSim).not.toHaveBeenCalled();
});

it('offers a retry for failed detail requests without treating the error as empty data', async () => {
  vi.mocked(simulationApi.getCachedSecurity).mockRejectedValueOnce(new Error('cache offline'));
  const initial = props(); render(<SimulationWorkspace {...initial} />);
  await screen.findByText('SPY: cache offline');
  fireEvent.click(screen.getByRole('button', { name: 'Retry coverage' }));
  expect(initial.onRefresh).toHaveBeenCalledTimes(1);
  expect((screen.getByRole('button', { name: 'Review simulation' }) as HTMLButtonElement).disabled).toBe(true);
});
