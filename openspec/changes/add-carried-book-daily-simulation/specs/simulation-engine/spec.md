## ADDED Requirements

### Requirement: Carried-book simulation continuity

The simulation engine SHALL allow a completed run to seed a child run with its
final cash and signed positions. A child SHALL start on the parent's final
valuation date, retain the same benchmark and ticker universe, and record the
parent run identifier.

#### Scenario: Child starts from the parent close

- **WHEN** a caller creates a carried run from a completed parent
- **THEN** the child's initial NAV snapshot equals the parent's final NAV, cash,
  and positions on the parent's valuation date

#### Scenario: Child executes the next trading day

- **WHEN** the carried child advances
- **THEN** signals use the parent valuation date's close and orders execute at
  the next cached trading day's open

#### Scenario: Parent is incompatible

- **WHEN** the parent is incomplete, uses another benchmark or universe, or its
  final valuation date differs from the child start date
- **THEN** the request fails before creating a child run

### Requirement: Position history in NAV snapshots

Each simulation NAV snapshot SHALL persist the signed position book at that
snapshot date, including the inherited book at the carried boundary.

#### Scenario: Continuous position history

- **WHEN** a carried chain completes
- **THEN** the parent's final positions equal the child's initial positions and
  every post-cycle snapshot contains its own position book
