# Proposal: Incremental Cache Updates

## Why

Price coverage is keyed by the exact requested range. When a caller extends the
same historical start date by one day, the cache treats the new range as an
entirely new request and downloads the full history again. That wastes remote
capacity and makes repeated daily fetches slower than necessary.

## What Changes

- Plan price fetches from fresh, complete coverage rows for the same ticker.
- Download only trading sessions that are not already covered.
- Skip an extension that contains no US market sessions, such as a weekend.
- Preserve `force=True` as an explicit full-range refresh.
- Keep cache-job batching while allowing each ticker to fetch from its own gap.
- Refresh the full requested range when the incremental tail contains a
  dividend or split, because historical adjusted closes changed at that event.

## Compatibility

No database column or API shape changes are required. Coverage history remains
an append-only record of actual fetch requests, and existing rows remain valid.

## Non-goals

- Automatic recurring data scheduling.
- Point-in-time security catalog history.
- Background cache-job persistence across backend restarts.
