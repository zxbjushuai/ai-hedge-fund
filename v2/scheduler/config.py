"""Scheduler configuration model."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SchedulerConfig(BaseModel):
    """Configuration for the fund daemon scheduler."""

    interval: str = Field(
        default="manual",
        description="Schedule interval: 'daily', 'hourly', or 'manual'",
    )
    time: str = Field(
        default="16:00",
        description="HH:MM time for daily schedule",
    )
    fund_path: str = Field(
        default="v2/funds/example.yaml",
        description="Path to the fund spec YAML file",
    )
    db_path: str = Field(
        default="fund.db",
        description="Path to the SQLite database file",
    )
    fee_rate: float = Field(
        default=0.001,
        ge=0.0,
        description="Commission fee rate (0.001 = 0.1%%)",
    )
