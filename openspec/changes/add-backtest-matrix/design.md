# Design: Reproducible Backtest Matrix

## Matrix Format

The input is JSON so the standard library can parse it without a new dependency:

```json
{
  "name": "momentum-windows",
  "defaults": {
    "connection": "sub2api opencode go",
    "model": "deepseek-v4.1-flash",
    "capital": 100000,
    "concurrency": 2,
    "benchmark": "SPY"
  },
  "runs": [
    {
      "name": "2026-h1",
      "tickers": ["AAPL", "MSFT"],
      "start": "2026-01-02",
      "end": "2026-06-30"
    }
  ]
}
```

`defaults` is optional. Each run may override `connection`, `model`, `capital`,
`concurrency`, and `benchmark`. `tickers`, `start`, and `end` are required per
run. Unknown keys are rejected so a typo cannot silently change only part of an
experiment.

## Execution

The command validates the complete document, including the API's ticker,
benchmark, and ten-year range constraints, before resolving a provider or
calling simulation preflight. It then invokes the existing `run_simulation`
contract sequentially, preserving the current cached-data, raw-price, benchmark,
and no-lookahead behavior.

The matrix name and run names are restricted to a filename-safe character set.
Simulation names use `<matrix>-<run>`, capped at the API's 100-character limit.

## Persistence and Comparison

Outputs are timestamped under `logs/ops/`:

- `matrix-<timestamp>-<name>.json`: the normalized matrix, source path, SHA-256
  digest, every run's parameters and full record or error, and extracted metrics.
- `matrix-<timestamp>-<name>.md`: a table of all runs and a ranking of completed
  runs by excess return.

Extracted metrics are simulation ID, status, final NAV, total return, benchmark
return, excess return, maximum drawdown, and Sharpe ratio. Terminal run failures
remain in the table without a rank and do not prevent later variants from
starting. An ambiguous submission, a failure to monitor an already-started
simulation, or a missing result is different: the matrix records the affected
run and stops immediately, because launching another run could overlap paid
backend work. The command exits 0 only when every run completed.

## Validation

Tests cover defaults and overrides, duplicate/unsafe names, malformed dates,
universe size, API-compatible ticker/benchmark/range validation, ranking order,
output persistence, continuation after a terminal run failure, and stopping
after submission or monitoring is lost. No network or LLM calls are used.
