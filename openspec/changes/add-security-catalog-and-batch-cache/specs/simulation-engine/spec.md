## MODIFIED Requirements

### Requirement: Raw-price simulation with corporate actions

New simulations SHALL use only raw universe price rows, apply splits and dividends
to carried positions before execution-day orders, and atomically persist the
action audit with fills, NAV, and cycle audit.

#### Scenario: Split produces a fractional share

- **WHEN** a split transforms an integer holding into a fractional holding
- **THEN** the integer shares are retained and the remainder is settled at that day's raw open

#### Scenario: Dividend becomes effective

- **WHEN** a position is carried into a day with a cached cash dividend
- **THEN** long cash is credited and short cash is debited before that day's orders

#### Scenario: Legacy and raw rows are mixed

- **WHEN** a requested simulation range contains `legacy_unknown` and raw rows
- **THEN** preflight fails with instructions to refresh the prices

### Requirement: Total-return benchmark

The benchmark NAV SHALL be normalized from adjusted close while fund execution
and valuation continue to use raw open and close.

#### Scenario: Benchmark adjusted close is missing

- **WHEN** a benchmark row has no adjusted close or is not raw
- **THEN** preflight fails instead of silently calculating a price-only benchmark
