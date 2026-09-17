"""Yahoo earnings helpers used by the PEAD cache path.

An actionable earnings surprise requires either Yahoo's explicit surprise
percentage or both reported EPS and the contemporaneous analyst estimate.
Missing estimates are never inferred from labels, prices, or future data.
"""

from __future__ import annotations

from hedge_fund.data.models import EarningsRecord


def surprise_direction(value: float | None) -> str | None:
    if value is None:
        return None
    if value > 0:
        return "BEAT"
    if value < 0:
        return "MISS"
    return "MEET"


def earnings_surprise_percent(record: EarningsRecord) -> float | None:
    """Return Yahoo's point-in-time surprise without inventing an estimate."""
    data = record.quarterly
    if data is None:
        return None
    if data.eps_surprise_percent is not None:
        return data.eps_surprise_percent
    actual = data.earnings_per_share
    estimate = data.estimated_earnings_per_share
    if actual is not None and estimate not in (None, 0):
        return ((actual - estimate) / abs(estimate)) * 100.0
    return None


def has_actionable_surprise(records: list[EarningsRecord]) -> bool:
    return any(record.filing_date and (surprise := earnings_surprise_percent(record)) is not None and surprise != 0 for record in records)
