## ADDED Requirements

### Requirement: Cache actionable point-in-time Yahoo earnings surprises
The system SHALL cache Yahoo actual EPS, estimated EPS when available, numeric surprise percentage when available, surprise direction, fiscal report period, and announcement date without inventing an estimate or joining fields from another provider.

#### Scenario: Yahoo supplies actionable earnings
- **WHEN** Yahoo returns reported EPS and either estimated EPS or a non-zero surprise
- **THEN** the system caches the Yahoo event as an actionable PEAD input

#### Scenario: Yahoo omits actionable surprise
- **WHEN** Yahoo returns actual EPS but no numeric surprise and no analyst estimate from which to derive one
- **THEN** available values may be cached, PEAD remains neutral for that ticker-event, and no BEAT/MISS sentinel is fabricated

#### Scenario: One ticker lacks EPS
- **WHEN** one ticker has no actionable Yahoo earnings event while other tickers do
- **THEN** only the missing ticker-event is neutral and the system continues evaluating PEAD and all other models for the rest of the universe

### Requirement: Keep quarterly LLM prompts stable between filings
The system SHALL value the latest visible filing with the last close on or before its filing date and SHALL NOT inject the exact simulation-date close into the quarterly fundamentals prompt.

#### Scenario: Price changes without a new filing
- **WHEN** two simulation dates see the same latest filing but different closes
- **THEN** the rendered fundamental prompt and prompt cache key remain identical

#### Scenario: New filing becomes visible
- **WHEN** another filing becomes point-in-time visible
- **THEN** its filing-date valuation and financial content produce a new prompt cache key

### Requirement: Estimate filing-level LLM calls
The simulation preflight SHALL estimate cold-cache calls from bootstrap snapshots and distinct filing changes for unique enabled personas.

#### Scenario: Many trading days contain no new filing
- **WHEN** a simulation contains multiple daily closes but one visible fundamentals snapshot per ticker
- **THEN** the estimate is `ticker_count * unique_persona_count`

#### Scenario: A filing appears during the signal range
- **WHEN** a ticker gains one new visible filing during the simulation signal dates
- **THEN** the estimate adds one call per unique persona for that ticker
