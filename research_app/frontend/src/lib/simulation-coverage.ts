import type { CachedSecurityDetail } from '../services/simulation-api';

export type DetailMap = Record<string, CachedSecurityDetail>;
export type DateRange = { start: string; end: string };
const positive = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) && value > 0;
const sorted = (detail?: CachedSecurityDetail) => [...(detail?.prices ?? [])].sort((a, b) => a.date.localeCompare(b.date));

export function benchmarkDates(detail?: CachedSecurityDetail): string[] {
  return sorted(detail).filter(row => positive(row.close)).map(row => row.date);
}

export function commonCoverage(tickers: string[], benchmark: string, details: DetailMap): DateRange | null {
  if (!tickers.length) return null;
  const ranges = [...new Set([...tickers, benchmark])].map(ticker => {
    const rows = sorted(details[ticker]).filter(row => row.price_mode === 'raw' && positive(row.close)
      && (ticker !== benchmark || positive(row.adjusted_close)));
    return rows.length ? { start: rows[0].date, end: rows[rows.length - 1].date } : null;
  });
  if (ranges.some(range => !range)) return null;
  const start = ranges.reduce((value, range) => range!.start > value ? range!.start : value, '');
  const end = ranges.reduce((value, range) => range!.end < value ? range!.end : value, '9999-12-31');
  const days = benchmarkDates(details[benchmark]).filter(day => day >= start && day <= end);
  return days.length >= 2 ? { start: days[0], end: days[days.length - 1] } : null;
}

export interface CoverageRow {
  ticker: string; start: string | null; end: string | null;
  leading: string[]; missingOpen: string[]; missingClose: string[];
  metrics: number; earnings: number;
}

export function analyzeCoverage(tickers: string[], benchmark: string, details: DetailMap, range: DateRange) {
  const errors: string[] = [];
  const warnings: string[] = [];
  const allDays = benchmarkDates(details[benchmark]);
  const days = allDays.filter(day => day >= range.start && day <= range.end);
  if (!tickers.length) errors.push('Select at least one cached security.');
  if (!range.start || !range.end || range.start >= range.end) errors.push('Choose a start date before the end date.');
  if (allDays.length && (range.start < allDays[0] || range.end > allDays[allDays.length - 1])) errors.push('Dates must stay within the benchmark cache range.');
  if (days.length < 2) errors.push('Benchmark needs at least two cached trading days.');
  const benchmarkRows = sorted(details[benchmark]).filter(row => row.date >= range.start && row.date <= range.end);
  if (benchmarkRows.some(row => row.price_mode !== 'raw' || !positive(row.adjusted_close))) errors.push(`${benchmark}: refresh legacy prices or missing adjusted close in Data.`);
  let withPrices = 0;
  const rows: CoverageRow[] = tickers.map(ticker => {
    const detail = details[ticker];
    const prices = sorted(detail);
    const inRange = prices.filter(row => row.date >= range.start && row.date <= range.end);
    if (inRange.length) withPrices++;
    else warnings.push(`${ticker}: no prices in this range; it may be skipped.`);
    if (inRange.some(row => row.price_mode !== 'raw')) errors.push(`${ticker}: legacy or mixed price modes. Refresh in Data.`);
    const closes = prices.filter(row => positive(row.close));
    const first = closes[0]?.date ?? null;
    const last = closes[closes.length - 1]?.date ?? null;
    const byDate = new Map(prices.map(row => [row.date, row]));
    const leading = days.filter(day => !first || day < first);
    const missingOpen = days.slice(1).filter(day => !positive(byDate.get(day)?.open));
    const missingClose = days.slice(1).filter(day => first && day >= first && !positive(byDate.get(day)?.close));
    if (leading.length) warnings.push(`${ticker}: ${leading.length} initial benchmark days without prices; signals may be skipped or abstain.`);
    if (missingOpen.length) warnings.push(`${ticker}: ${missingOpen.length} execution days without a valid open; orders may be skipped.`);
    if (missingClose.length) warnings.push(`${ticker}: ${missingClose.length} days without a close after prices begin. If held, the simulation may fail.`);
    const metrics = detail?.metrics.filter(row => row.filing_date <= (days[0] ?? range.start)).length ?? 0;
    const earnings = detail?.earnings.filter(row => row.announcement_date <= range.end && row.surprise_pct != null && row.surprise_pct !== 0).length ?? 0;
    if (metrics < 4) warnings.push(`${ticker}: ${metrics} visible financial records at the first signal date; LLM analysts may abstain until eligible.`);
    if (!earnings) warnings.push(`${ticker}: no actionable cached earnings by the end date. Review preflight for strategy availability.`);
    return { ticker, start: first, end: last, leading, missingOpen, missingClose, metrics, earnings };
  });
  if (tickers.length && !withPrices) errors.push('None of the selected securities has prices in this range.');
  const common = commonCoverage(tickers, benchmark, details);
  const expanded = !!range.start && !!range.end && (!common || range.start < common.start || range.end > common.end);
  if (expanded && tickers.length) warnings.push('This range extends beyond common coverage. Missing data can affect signals, execution and valuation.');
  return { errors, warnings, rows, days, common, expanded, requiresAcknowledgement: expanded || warnings.length > 0 };
}
