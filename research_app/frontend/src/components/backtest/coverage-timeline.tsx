import type { DetailMap, DateRange } from '@/lib/simulation-coverage';
import { analyzeCoverage, benchmarkDates } from '@/lib/simulation-coverage';
import { Button } from '@/components/ui/button';

export function CoverageTimeline({ tickers, benchmark, details, range, onCommon, disabled }: {
  tickers: string[]; benchmark: string; details: DetailMap; range: DateRange; onCommon: () => void; disabled: boolean;
}) {
  const analysis = analyzeCoverage(tickers, benchmark, details, range);
  const days = benchmarkDates(details[benchmark]);
  const low = days[0], high = days[days.length - 1];
  const start = Date.parse(low), span = Math.max(1, Date.parse(high) - start);
  const x = (day: string) => Math.min(100, Math.max(0, (Date.parse(day) - start) / span * 100));
  return <section className="work-section" aria-labelledby="coverage-heading">
    <div className="section-heading"><div><h2 id="coverage-heading">Data coverage</h2><p>Compare the cached timeline before committing to a run.</p></div><Button variant="outline" disabled={!analysis.common || disabled} onClick={onCommon}>Use common range</Button></div>
    {analysis.common ? <p className="notice">Common coverage: <strong>{analysis.common.start} – {analysis.common.end}</strong>. Applying this range trims earlier or later history outside these dates; internal gaps still need review.</p> : <p className="notice warning">{tickers.length ? 'No common range with two benchmark trading days. Keep the selection and choose a custom range, or prepare more data.' : 'Select securities to calculate common coverage.'}</p>}
    {low && <><div className="timeline-axis"><span>{low}</span><span>{high}</span></div><div className="timeline-list">{[...new Set([benchmark, ...tickers])].map(ticker => {
      const prices = details[ticker]?.prices.filter(row => row.price_mode === 'raw' && Number.isFinite(row.close) && row.close > 0) ?? [];
      const dates = prices.map(row => row.date).sort();
      const byDate = new Map(prices.map(row => [row.date, row]));
      const gaps = days.filter(day => dates.length && day >= dates[0] && day <= dates[dates.length - 1] && !byDate.has(day));
      return <div className="timeline-row" key={ticker}><div><strong>{ticker}</strong>{ticker === benchmark && <small>Benchmark</small>}</div><div className="timeline-track" role="img" aria-label={`${ticker}: ${dates.length ? `${dates[0]} to ${dates[dates.length - 1]}, ${gaps.length} missing benchmark sessions` : 'no raw price data'}`}>
        {dates.length > 0 && <span className="timeline-bar" style={{ left: `${x(dates[0])}%`, width: `${Math.max(0.5, x(dates[dates.length - 1]) - x(dates[0]))}%` }} />}
        {range.start && range.end && <span className="timeline-window" style={{ left: `${x(range.start)}%`, width: `${Math.max(0, x(range.end) - x(range.start))}%` }} />}
        {gaps.map(day => <span key={day} className="timeline-gap" style={{ left: `${x(day)}%` }} title={`Missing price: ${day}`} />)}
      </div><small>{dates.length ? `${dates[0]} – ${dates[dates.length - 1]}` : 'No raw prices'}</small></div>;
    })}</div></>}
    <p className="quiet">Blue: raw cached prices · Outline: requested range · Orange: missing cached sessions. Dates come from the benchmark cache, not an independent exchange calendar.</p>
    {range.start && range.end && <><p className="quiet">Actual benchmark dates: {analysis.days[0] ?? '—'} – {analysis.days[analysis.days.length - 1] ?? '—'} ({analysis.days.length} days). T+1 is the next cached benchmark trading day.</p>
      {analysis.rows.map(row => <details key={row.ticker}><summary>{row.ticker}: {row.missingOpen.length} missing opens, {row.missingClose.length} missing closes, {row.metrics} visible financial records</summary><p className="quiet">Missing opens: {row.missingOpen.join(', ') || 'None'}<br />Missing closes after prices begin: {row.missingClose.join(', ') || 'None'}</p></details>)}
    </>}
    <p className="quiet">Common coverage is not a guarantee of completion. Missing benchmark sessions cannot be detected from this cache alone. Future holdings determine whether a missing close causes failure.</p>
  </section>;
}
