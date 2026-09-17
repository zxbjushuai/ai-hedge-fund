# Proposal: US Security Catalog and Batch Cache

## Why

The dashboard currently requires memorized ticker strings and performs a long,
synchronous Yahoo request for every security. Price rows also have no explicit
adjustment provenance, so adjusted and raw execution prices can be confused.

## What Changes

- Add a current US security catalog, searchable selection, and saved universes.
- Introduce market-level adapters. US is implemented; HK and CN remain explicit
  unsupported TODOs.
- Cache raw Yahoo OHLCV, adjusted close, dividends, splits, source, and price mode.
- Add bounded in-memory cache jobs with progress, cancellation, partial failure,
  coverage reporting, and failed-item retry.
- Apply cached corporate actions during simulations and use adjusted benchmark
  closes for total-return comparison.
- Reuse the security selector on cache and simulation pages.

## Compatibility

Existing ticker-based cache and simulation requests remain accepted. Existing
price rows are migrated to `legacy_unknown`; they are not silently relabelled or
deleted. Historical simulation results remain readable.

## Non-goals

- Hong Kong or mainland China data acquisition.
- Point-in-time historical index membership.
- Persistent cache-job recovery after a service restart.
- Replacing Yahoo financial filing-date estimates.
