"""Cooperative simulation cancellation signals and state errors."""

from __future__ import annotations


class SimulationCancelled(RuntimeError):
    """Raised inside a worker after a cancellation request is observed."""


class SimulationNotCancellable(ValueError):
    """Raised when a terminal simulation cannot accept cancellation."""
