# Proposal: Improve Filing-Date Provenance

## Why

The cached fundamentals path currently assigns every quarterly metrics row a
`report_period + 45 days` filing date. That is a conservative estimate, not the
date the filing became public, and the persona layer cannot distinguish it from
an authoritative timestamp. The Yahoo earnings fallback also labels fiscal
period columns as filing dates, which can create a fabricated PEAD event.

## What Changes

- Add a small SEC submissions client that maps tickers to CIKs and reads recent
  `10-Q`, `10-K`, and `20-F` acceptance metadata.
- Match filing report dates to cached quarterly metrics within a bounded window
  and persist the SEC acceptance date as `filing_date_source=sec_submissions`.
- Preserve the existing `estimated_45d` fallback when no safe match exists.
- Stop emitting Yahoo earnings records with fiscal-period dates when exact
  earnings announcement dates are unavailable; PEAD remains neutral instead.
- Update cache/API provenance text and tests for matching, fallback, and
  abstention behavior.

## Non-goals

- Reconstructing historical filings that SEC no longer exposes in the recent
  submissions feed.
- Using 8-K dates for PEAD surprises when Yahoo has no announcement timestamp.
- Backfilling every existing cache row automatically; operators can refresh
  metrics through the existing cache fetch flow.
