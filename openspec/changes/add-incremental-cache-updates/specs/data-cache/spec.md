## ADDED Requirements

### Requirement: Incremental price cache coverage

The cache SHALL reuse fresh complete price coverage and fetch only trading
sessions that are missing from a requested date range. A forced request SHALL
continue to refresh the complete requested range.

#### Scenario: Daily request extends the end date

- **WHEN** a ticker has fresh complete coverage through a date and the caller
  requests the same start through the next trading day
- **THEN** the cache fetches only that next trading day

#### Scenario: Extended range has no market sessions

- **WHEN** the days after existing coverage through the new end date contain no
  US market sessions
- **THEN** the request is skipped without a remote price call

#### Scenario: Incremental fetch follows a pre-close request

- **WHEN** the previous coverage was fetched before the final session closed
- **THEN** the next request refreshes that final session together with the new
  trading days

#### Scenario: Incremental tail contains a corporate action

- **WHEN** a newly fetched tail contains a dividend or split
- **THEN** the cache refreshes the original requested range before persisting it
  so historical adjusted closes remain coherent

#### Scenario: Caller forces a refresh

- **WHEN** a caller requests `force=True`
- **THEN** the complete requested range is fetched regardless of existing
  coverage

#### Scenario: Inventory shows merged incremental coverage

- **WHEN** one ticker has adjacent coverage rows from incremental fetches
- **THEN** the cache inventory reports the union of their requested and actual
  date ranges while preserving the individual rows in coverage history

#### Scenario: Merged coverage contains a gap

- **WHEN** adjacent coverage bounds contain an uncovered trading session
- **THEN** the inventory reports partial coverage with the correct missing-session
  count and is excluded from a `status=complete` filter
