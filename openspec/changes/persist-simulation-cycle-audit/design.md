# Design: Failure Semantics and Cycle Audit

## Signal Outcomes

`Signal.status` defaults to `produced` for source compatibility. A produced
signal may be positive, negative, or exactly zero; zero remains a successful
neutral view. `abstained` means the model intentionally had insufficient
point-in-time inputs. `failed` means an attempted computation could not produce
a trustworthy view.

Failures carry a category, a safe summary, and retryability. LLM authentication,
rate-limit, timeout, transport, and invalid-response errors become failed
signals. `InsufficientData` remains an abstention. Data-access exceptions that
prevent cycle construction remain fatal and produce a failed cycle audit row;
they are never converted into neutral signals.

Raw prompts and provider responses remain in the existing prompt cache. Cycle
audit payloads retain prompt-cache keys and model metadata but never API keys,
authorization headers, or endpoint query strings.

## Persistence Shape

`sim_cycle_record` stores one row per attempted decision cycle:

- simulation id and cycle number;
- indexed signal and execution dates;
- completed or failed status;
- effective universe and complete serialized `CycleRecord` payload;
- safe failure category/message for failed attempts;
- cash and NAV summary fields.

`sim_cycle_ticker_index` is a compact child index used for ticker filtering. It
stores signal outcome counts, target/final weights, and order/fill counts. The
nested strategy data remains in the serialized cycle payload rather than being
fully normalized.

The initial benchmark/fund NAV point is not a decision cycle. Each subsequent
T/T+1 cycle is numbered from one. A completed cycle row, its ticker indexes,
the T+1 NAV snapshot, and fills are committed atomically. Existing historical
runs simply return no audit records.

The serialized record distinguishes T signal marks, T+1 execution prices, and
T+1 valuation closes. Orders and fills therefore remain reproducible even when
a ticker was priced but did not trade.

## Query API

`GET /dashboard/sim/{id}/cycles` returns paginated summaries and supports exact
signal date, execution date, and ticker filters. `GET
/dashboard/sim/{id}/cycles/{cycle_id}` returns the full payload after verifying
that the cycle belongs to the run. Empty results expose `audit_available=false`
and are valid for historical runs.

## Web View

The simulation result page adds a Decision Audit section. Users filter by date
or ticker, select a cycle, and inspect strategy signals and their outcome,
target-to-final weight changes, clamps, skips, orders, fills, ending positions,
cash, and NAV. Existing summary, NAV, and trades rendering remains unchanged.

## Compatibility and Security

The database change is additive. Existing `Signal` construction works because
the new status has a compatibility default. Existing simulation result routes
retain their response shape except for optional additive audit availability.
Failure summaries are categorized and sanitized; raw exception bodies are not
persisted for remote LLM errors.
