# Design

Prepare point-in-time inputs and apply Persona state on the runner thread. Only prepared
inference executes in workers; bounded submission and a process-wide semaphore protect
providers. Dates remain sequential. Optional context-local observation preserves the
existing LLM complete contract. JSONL logs contain summaries, never raw prompts/responses.

New requests accept concurrency 1–8 (legacy default 1; UI default 4). Activity is ephemeral,
execution configuration persists. Partial results use last committed NAV, not initial cash.

## Implemented interfaces

- `SimRunRequest.llm_concurrency`: strict integer 1–8; API default 1, Review default 4.
- Nullable `sim_run.execution_config` JSON is added through the existing additive migration.
  It stores concurrency and the preflight estimate, never credentials.
- Status adds `activity` and `execution_config`; result adds `valuation_date` and
  `execution_config`. Result NAV/return/drawdown/Sharpe can be null before any valuation.
- Logs are beside the resolved fund database: `logs/simulations/sim-{id}.log`.
  With the default database this is the repository logs directory. Distinct database
  directories do not share logs merely because their run IDs are the same.
- Three managed protocols report HTTP attempts, responses and safe error categories.
  SDK retry attempts share a call ID. Request IDs are hashed rather than logging an
  arbitrary upstream header. Known remote error codes use an allowlist.

## Concurrency and compatibility

The Persona preparation generator pauses only at inference. A rolling executor submits
at most 2C unfinished futures; completed responses are applied in original request order.
Immediate abstention/reuse audit records are sorted into the same stable order. The main
thread prepares data and mutates state. A process-wide semaphore holds a slot until the
actual LLM complete call exits, including SDK retries. There is no future-day prefetch.
Default CLI paths retain their complete contract and do not need Web/database startup.

Logs are append-only diagnostic evidence, not a replay or resume mechanism. Live activity
is in memory and unavailable after restart. Existing prompt-cache payload storage is
unchanged; new simulation logs contain structured summaries only. Cache writes/reads
are serialized within this process. Multi-process scheduling/cache coordination is not
part of this single-backend-process implementation.
