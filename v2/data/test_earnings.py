"""Yahoo earnings surprise tests — deterministic, no network."""

import pytest

from v2.data.earnings import (
    earnings_surprise_percent,
    has_actionable_surprise,
)
from v2.data.models import EarningsData, EarningsRecord


def _record(*, actual=2.0, estimate=None, direction=None, percent=None):
    return EarningsRecord(
        ticker="AAA",
        report_period="2024-03-31",
        source_type="earnings",
        filing_date="2024-05-01",
        quarterly=EarningsData(
            earnings_per_share=actual,
            estimated_earnings_per_share=estimate,
            eps_surprise=direction,
            eps_surprise_percent=percent,
        ),
    )


def test_surprise_percent_uses_actual_and_estimate():
    assert earnings_surprise_percent(_record(actual=2.0, estimate=1.6)) == pytest.approx(25.0)


def test_explicit_yahoo_surprise_percent_is_preserved():
    assert earnings_surprise_percent(_record(actual=2.0, estimate=1.6, percent=24.75)) == 24.75


def test_label_only_surprise_does_not_fabricate_analyst_estimate():
    assert earnings_surprise_percent(_record(direction="BEAT")) is None
    assert earnings_surprise_percent(_record(direction="MISS")) is None
    assert earnings_surprise_percent(_record(actual=2.0)) is None


def test_actionable_surprise_requires_nonzero_numeric_surprise_and_date():
    assert has_actionable_surprise([_record(estimate=1.5)])
    assert not has_actionable_surprise([_record(direction="BEAT")])
    assert not has_actionable_surprise([_record(estimate=2.0)])

    no_date = _record(estimate=1.5)
    no_date.filing_date = None
    assert not has_actionable_surprise([no_date])
