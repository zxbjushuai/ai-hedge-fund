## ADDED Requirements

### Requirement: Current US security catalog

The system SHALL synchronize a current US security catalog, preserve canonical
and Yahoo symbols, and deactivate listings that disappear without deleting them.

#### Scenario: Repeated catalog synchronization

- **WHEN** the same Nasdaq Trader directory is synchronized twice
- **THEN** the second synchronization updates the existing rows without creating duplicates

#### Scenario: Listing disappears

- **WHEN** a previously stored symbol is absent from a successful current directory response
- **THEN** the symbol is marked inactive and historical universe references remain valid

### Requirement: Market-level adapter boundary

The system SHALL route acquisition by market and SHALL expose only the implemented
US market to users.

#### Scenario: Unsupported market requested

- **WHEN** an HK or CN adapter operation is invoked
- **THEN** it fails with the typed `unsupported_market` category and performs no remote request

### Requirement: Saved universes

The system SHALL let users save an ordered set of selectable US securities and
archive it without changing historical simulation ticker snapshots.

#### Scenario: Saved universe is loaded

- **WHEN** a user selects a saved universe
- **THEN** its current ordered member symbols populate the runtime ticker selection

### Requirement: Concrete filtered selection

The selector SHALL support server-side search, exchange/type filters, directory
sorting, page navigation, and selection or deselection of every matching row.
The complete selection SHALL be materialized as typed security IDs rather than a
deferred filter expression.

#### Scenario: User removes rows after selecting a filter

- **WHEN** a user selects all matching rows and then manually deselects securities
- **THEN** the submitted JSON ID array contains every matched ID except those explicitly removed
