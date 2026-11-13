"""Bootstrap recovery and compact runtime status."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock

from sqlalchemy import func, select

from hedge_fund.data.cache_jobs import (
    get_cache_job_manager,
    recover_orphaned_cache_jobs,
)
from hedge_fund.persistence.database import get_session, init_db
from hedge_fund.persistence.models import SimRun
from hedge_fund.simulation.runner import SimRunner

logger = logging.getLogger(__name__)

_SIMULATION_STATUSES = (
    "pending",
    "running",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
)
_CACHE_JOB_STATUSES = (
    "pending",
    "running",
    "cancelling",
    "completed",
    "partial",
    "failed",
    "cancelled",
)
_recovery_lock = RLock()
_startup_recovery: dict = {
    "completed_at": None,
    "orphaned_simulations_recovered": 0,
    "orphaned_simulations_failed": 0,
    "orphaned_simulations_cancelled": 0,
    "simulation_ids": [],
    "orphaned_cache_jobs_failed": 0,
    "cache_job_ids": [],
}


def recover_startup_state(fund_db: str) -> dict:
    """Recover work that cannot survive a backend process restart."""
    recovered_at = datetime.now(timezone.utc)
    simulation_ids = SimRunner.recover_orphaned_runs(
        fund_db,
        recovered_at=recovered_at,
    )
    cache_job_ids = recover_orphaned_cache_jobs(
        fund_db,
        recovered_at=recovered_at,
    )
    report = {
        "completed_at": recovered_at.isoformat(),
        "orphaned_simulations_recovered": len(simulation_ids),
        "orphaned_simulations_failed": _status_count(fund_db, simulation_ids, "failed"),
        "orphaned_simulations_cancelled": _status_count(fund_db, simulation_ids, "cancelled"),
        "simulation_ids": simulation_ids,
        "orphaned_cache_jobs_failed": len(cache_job_ids),
        "cache_job_ids": cache_job_ids,
    }
    global _startup_recovery
    with _recovery_lock:
        _startup_recovery = deepcopy(report)
    logger.info(
        "startup recovery recovered %d simulations and cancelled %d cache jobs",
        len(simulation_ids),
        len(cache_job_ids),
    )
    return report


def _status_count(fund_db: str, simulation_ids: list[int], status: str) -> int:
    if not simulation_ids:
        return 0
    with get_session(fund_db) as session:
        return int(session.scalar(select(func.count()).select_from(SimRun).where(SimRun.id.in_(simulation_ids), SimRun.status == status)) or 0)


def _empty_status_counts(defaults: tuple[str, ...]) -> dict[str, int]:
    counts = {status: 0 for status in defaults}
    return counts


def runtime_status(fund_db: str) -> dict:
    """Return safe process and persisted-runtime summaries for the dashboard."""
    init_db(fund_db)
    with get_session(fund_db) as session:
        simulation_rows = session.execute(select(SimRun.status, func.count()).group_by(SimRun.status)).all()

    jobs = get_cache_job_manager(fund_db).list()
    cache_statuses = [job.get("status", "unknown") for job in jobs]
    simulation_counts = _empty_status_counts(_SIMULATION_STATUSES)
    for status, count in simulation_rows:
        simulation_counts[status] = count
    cache_counts = _empty_status_counts(_CACHE_JOB_STATUSES)
    for status in cache_statuses:
        cache_counts[status] = cache_counts.get(status, 0) + 1
    with _recovery_lock:
        recovery = deepcopy(_startup_recovery)
    return {
        "startup_recovery": recovery,
        "simulations": simulation_counts,
        "cache_jobs": {
            "total": len(jobs),
            "by_status": cache_counts,
            "active": sum(
                cache_counts[status]
                for status in (
                    "pending",
                    "running",
                    "cancelling",
                )
            ),
        },
    }
