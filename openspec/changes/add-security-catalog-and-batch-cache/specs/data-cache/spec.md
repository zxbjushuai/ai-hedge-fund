## MODIFIED Requirements

### Requirement: Explicit raw price provenance

The cache SHALL store raw OHLCV, adjusted close, dividends, split ratio, source,
and price mode for new US price rows. Existing rows SHALL remain
`legacy_unknown` until refreshed.

#### Scenario: Legacy database is migrated

- **WHEN** a database containing the old price schema is opened
- **THEN** additive columns are created and old rows are labelled `legacy_unknown` without deleting data

#### Scenario: Yahoo price is refreshed

- **WHEN** Yahoo returns a price row with `auto_adjust=false`
- **THEN** the date is upserted with raw provenance and its corporate-action fields

### Requirement: Bounded cache jobs

The system SHALL run bounded process-local cache jobs with progress, cancellation,
partial success, categorized errors, and failed-item retry.

#### Scenario: One ticker fails

- **WHEN** one member times out while other members return valid prices
- **THEN** successful rows are committed and the job finishes partial with the failed ticker retryable

#### Scenario: Complete range is requested again

- **WHEN** a fresh complete coverage record matches a non-forced request
- **THEN** that data kind is skipped without another remote call

### Requirement: US coverage

The system SHALL compare returned dates with an official US exchange calendar and
persist requested range, actual range, row count, and missing sessions.

#### Scenario: Newly listed security has no leading history

- **WHEN** valid rows begin after the requested start but have no gaps through the requested end
- **THEN** the actual start is reported without treating the leading absence as a transport failure

### Requirement: Cache explorer

The UI SHALL present cached securities through a searchable, filterable, sortable,
server-paginated table and SHALL lazily display all effective cached data for a
selected security.

#### Scenario: Cached security is expanded

- **WHEN** a user expands a cached security row
- **THEN** the UI displays its merged price history, raw and adjusted-close SVG curves, financial periods, earnings events, and fetch coverage history without a new chart dependency
