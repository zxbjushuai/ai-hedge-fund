## ADDED Requirements

### Requirement: Select securities from a local catalog
The system SHALL maintain a locally queryable securities catalog and let users search, filter, and select multiple supported equities without memorizing ticker symbols.

#### Scenario: Search by name or ticker
- **WHEN** a user searches for `Apple` or `AAPL`
- **THEN** matching local catalog entries include ticker, name, exchange, type, and cached coverage

#### Scenario: Select a filtered universe
- **WHEN** a user selects all eligible US common stocks matching configured liquidity filters
- **THEN** the backend resolves the selection and reports the exact ticker count before a cache job starts

### Requirement: Fetch historical data as a bounded background job
The system SHALL process selected securities in bounded batches, expose progress and per-ticker failures, and retain rate-limit backoff without requiring process-restart recovery in this phase.

#### Scenario: Partial failure
- **WHEN** some tickers fail while others succeed
- **THEN** successful cache rows remain committed and failed tickers can be retried independently

#### Scenario: Coverage already exists
- **WHEN** a ticker already has complete requested coverage
- **THEN** the job skips redundant retrieval and records the ticker as already complete
