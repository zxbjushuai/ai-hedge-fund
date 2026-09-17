## ADDED Requirements

### Requirement: Materialize complete daily persona signals from event-driven state
The system SHALL produce an effective signal for every eligible `(ticker, persona)` on every cycle without requiring every persona to run every day.

#### Scenario: One ticker receives a new filing
- **WHEN** AAPL receives a new filing and MSFT does not
- **THEN** AAPL personas refresh, MSFT reuses its still-valid states, and both tickers participate in the same portfolio blend

#### Scenario: Refresh fails with prior valid state
- **WHEN** an event-triggered LLM request fails while a prior opinion remains valid
- **THEN** the prior opinion remains effective and the failed refresh is recorded

#### Scenario: No prior state exists
- **WHEN** a ticker has never completed a persona analysis or its state has expired
- **THEN** that persona abstains for the ticker without removing other model signals

### Requirement: Preserve point-in-time event chronology
The system SHALL only refresh or reuse state that was observable on or before the cycle signal date.

#### Scenario: Backtest processes an earnings event
- **WHEN** an earnings announcement becomes visible after a prior close
- **THEN** it cannot affect a signal, order, or state dated before that announcement
