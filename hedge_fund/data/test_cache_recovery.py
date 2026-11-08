from datetime import datetime, timezone
from threading import Event

from hedge_fund.data.cache_jobs import CacheJobManager


def test_cache_job_recovery_fails_only_active_jobs(tmp_path):
    manager = CacheJobManager(str(tmp_path / "fund.db"))
    try:
        manager._jobs.update(
            {
                "pending": {"id": "pending", "status": "pending", "completed_at": None},
                "running": {"id": "running", "status": "running", "completed_at": None},
                "completed": {"id": "completed", "status": "completed", "completed_at": "done"},
            }
        )
        manager._cancel.update({"pending": Event(), "running": Event()})

        recovered_at = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)
        assert manager.recover_orphaned(recovered_at=recovered_at) == ["pending", "running"]
        assert manager.get("pending")["status"] == "failed"
        assert manager.get("running")["status"] == "failed"
        assert manager.get("completed")["completed_at"] == "done"
        assert manager._cancel["pending"].is_set()
        assert manager._cancel["running"].is_set()
        assert manager.recover_orphaned(recovered_at=recovered_at) == []
    finally:
        manager._runner.shutdown(wait=False, cancel_futures=True)
