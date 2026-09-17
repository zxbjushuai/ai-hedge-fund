## MODIFIED Requirements

### Requirement: Searchable US universe selection

The cache and simulation pages SHALL share a searchable, filterable, paginated US
security selector with page selection, filtered selection, saved universes, and a
manual ticker fallback.

#### Scenario: User selects a catalog security

- **WHEN** a user selects securities by name or symbol
- **THEN** the cache job receives their security IDs and simulation receives the resolved ticker list

### Requirement: Cache job visibility

The cache page SHALL show job progress, per-ticker data-kind outcomes, persistent
coverage, cancellation, and failed-item retry.

#### Scenario: Batch finishes partially

- **WHEN** a cache job has both successful and failed tickers
- **THEN** the UI displays the partial result and offers retry for failed items
