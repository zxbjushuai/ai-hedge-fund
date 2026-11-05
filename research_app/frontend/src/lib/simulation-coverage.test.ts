import { describe, expect, it } from 'vitest';
import { analyzeCoverage, commonCoverage } from './simulation-coverage';
import type { CachedSecurityDetail } from '../services/simulation-api';

export const dates = ['2024-01-05', '2024-01-08', '2024-01-09', '2024-01-10'];
export function detail(ticker: string, days = dates): CachedSecurityDetail {
  return { ticker, security: null, prices: days.map(date => ({ date, open: 10, high: 11, low: 9, close: 10, adjusted_close: 10, volume: 100, dividend: 0, split_ratio: 0, source: 'fixture', price_mode: 'raw' })),
    metrics: [1, 2, 3, 4].map(i => ({ report_period: `2023-0${i}-01`, filing_date: `2023-0${i}-15`, filing_date_source: 'fixture', data: {} })),
    earnings: [{ report_period: '2023-09-30', announcement_date: '2023-11-01', actual_eps: 2, estimated_eps: 1, surprise_pct: 100, source: 'fixture' }], coverage_history: [] };
}
describe('cached simulation coverage', () => {
  it('recommends the overlapping raw range aligned to benchmark days', () => {
    expect(commonCoverage(['AAPL', 'MSFT'], 'SPY', { AAPL: detail('AAPL'), MSFT: detail('MSFT', dates.slice(1)), SPY: detail('SPY') })).toEqual({ start: dates[1], end: dates[3] });
  });
  it('returns no recommendation for disjoint histories or only one common day', () => {
    expect(commonCoverage(['AAPL', 'MSFT'], 'SPY', { AAPL: detail('AAPL', dates.slice(0, 2)), MSFT: detail('MSFT', dates.slice(2)), SPY: detail('SPY') })).toBeNull();
    expect(commonCoverage(['AAPL'], 'SPY', { AAPL: detail('AAPL', [dates[0]]), SPY: detail('SPY') })).toBeNull();
  });
  it('accepts weekend boundaries and retains the benchmark grid across stock gaps', () => {
    const result = analyzeCoverage(['AAPL'], 'SPY', { AAPL: detail('AAPL', [dates[0], dates[3]]), SPY: detail('SPY') }, { start: '2024-01-06', end: dates[3] });
    expect(result.days).toEqual(dates.slice(1));
    expect(result.rows[0].missingClose).toEqual([dates[2]]);
    expect(result.errors).toEqual([]);
    expect(result.warnings.join()).toContain('simulation may fail');
  });
  it('blocks missing/one-day benchmark and out-of-bounds dates', () => {
    for (const spy of [undefined, detail('SPY', [dates[0]])]) {
      const result = analyzeCoverage(['AAPL'], 'SPY', { AAPL: detail('AAPL'), ...(spy ? { SPY: spy } : {}) }, { start: dates[0], end: dates[3] });
      expect(result.errors.join()).toContain('at least two');
    }
    expect(analyzeCoverage(['AAPL'], 'SPY', { AAPL: detail('AAPL'), SPY: detail('SPY') }, { start: '2023-01-01', end: dates[3] }).errors.join()).toContain('within');
  });
  it('blocks mixed price modes and missing benchmark adjusted close', () => {
    const a = detail('AAPL'), spy = detail('SPY');
    a.prices[1].price_mode = 'legacy_unknown'; spy.prices[2].adjusted_close = null;
    const result = analyzeCoverage(['AAPL'], 'SPY', { AAPL: a, SPY: spy }, { start: dates[0], end: dates[3] });
    expect(result.errors).toHaveLength(2);
  });
  it('ignores legacy prices outside the request, but does not assume financial eligibility', () => {
    const a = detail('AAPL'), spy = detail('SPY'); a.prices[0].price_mode = 'legacy_unknown';
    a.metrics[0].filing_date = '2025-01-01'; a.earnings = [];
    const result = analyzeCoverage(['AAPL'], 'SPY', { AAPL: a, SPY: spy }, { start: dates[1], end: dates[3] });
    expect(result.errors).toEqual([]); expect(result.rows[0].metrics).toBe(3);
    expect(result.warnings.join()).toContain('no actionable');
  });
  it('distinguishes leading absence from missing closes after availability', () => {
    const result = analyzeCoverage(['AAPL'], 'SPY', { AAPL: detail('AAPL', [dates[1], dates[2]]), SPY: detail('SPY') }, { start: dates[0], end: dates[3] });
    expect(result.rows[0].leading).toEqual([dates[0]]); expect(result.rows[0].missingClose).toEqual([dates[3]]);
    expect(result.expanded).toBe(true); expect(result.requiresAcknowledgement).toBe(true);
  });
  it('blocks an entirely empty universe range', () => {
    expect(analyzeCoverage(['AAPL'], 'SPY', { AAPL: detail('AAPL', []), SPY: detail('SPY') }, { start: dates[0], end: dates[3] }).errors.join()).toContain('None of the selected');
  });
});
