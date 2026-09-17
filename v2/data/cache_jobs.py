"""Bounded process-local cache jobs for the single-machine dashboard."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from threading import Event, RLock
from uuid import uuid4

from v2.data.cache_service import coverage_is_fresh, fetch_security_data
from v2.data.cache_service import persist_prices
from v2.data.market import USMarketDataAdapter


class CacheJobManager:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._jobs: dict[str, dict] = {}
        self._cancel: dict[str, Event] = {}
        self._lock = RLock()
        self._runner = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache-job")

    def create(
        self,
        tickers: list[str],
        benchmark: str,
        start_date: str,
        end_date: str,
        data_types: list[str],
        force: bool = False,
    ) -> dict:
        normalized = list(dict.fromkeys(value.strip().upper() for value in tickers if value.strip()))
        benchmark = benchmark.strip().upper()
        work = list(normalized)
        if benchmark not in work:
            work.append(benchmark)
        job_id = uuid4().hex
        job = {
            "id": job_id, "status": "pending", "tickers": normalized,
            "benchmark": benchmark, "start_date": start_date, "end_date": end_date,
            "data_types": list(data_types), "force": force,
            "progress": {"total": len(work), "completed": 0, "failed": 0, "cancelled": 0},
            "items": {}, "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._cancel[job_id] = Event()
        self._runner.submit(self._run, job_id, work)
        return self.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            values = [deepcopy(value) for value in self._jobs.values()]
        return sorted(values, key=lambda value: value["created_at"], reverse=True)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            value = self._jobs.get(job_id)
            return deepcopy(value) if value else None

    def cancel(self, job_id: str) -> dict | None:
        with self._lock:
            event = self._cancel.get(job_id)
            job = self._jobs.get(job_id)
            if event is None or job is None:
                return None
            event.set()
            if job["status"] == "pending":
                job["status"] = "cancelling"
        return self.get(job_id)

    def retry(self, job_id: str) -> dict | None:
        job = self.get(job_id)
        if job is None:
            return None
        failed = [
            ticker for ticker, item in job["items"].items()
            if any(value and value.get("status") in {"failed", "no_data"} for key, value in item.items() if key in {"prices", "metrics", "earnings"})
        ]
        if not failed:
            return None
        return self.create(failed, job["benchmark"], job["start_date"], job["end_date"], job["data_types"], True)

    def _run(self, job_id: str, work: list[str]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "running"
            cancel = self._cancel[job_id]
            selected = set(job["tickers"])
            benchmark = job["benchmark"]
            start_date, end_date, force = job["start_date"], job["end_date"], job["force"]
            requested_types = list(job["data_types"])

        def run_one(ticker: str, kinds: list[str]) -> dict:
            return fetch_security_data(self.db_path, ticker, start_date, end_date, kinds, force=force)

        # Yahoo price history is fetched in batches. Missing batch members receive
        # bounded individual fallbacks so one bad symbol does not poison the batch.
        price_candidates = work if "prices" in requested_types else [benchmark]
        price_work: list[str] = []
        for ticker in price_candidates:
            if not force and coverage_is_fresh(self.db_path, ticker, "prices", start_date, end_date):
                with self._lock:
                    self._jobs[job_id]["items"][ticker] = {
                        "ticker": ticker, "prices": {"status": "skipped", "reason": "fresh complete coverage"}, "warnings": [],
                    }
            else:
                price_work.append(ticker)
        fallback: list[str] = []
        adapter = USMarketDataAdapter()
        for offset in range(0, len(price_work), 50):
            if cancel.is_set():
                break
            chunk = price_work[offset:offset + 50]
            try:
                batch = adapter.get_prices_batch(chunk, start_date, end_date)
            except Exception:
                batch = {}
            for ticker in chunk:
                prices = batch.get(ticker, [])
                if prices:
                    detail = persist_prices(self.db_path, ticker, prices, start_date, end_date)
                    with self._lock:
                        self._jobs[job_id]["items"][ticker] = {"ticker": ticker, "prices": detail, "warnings": []}
                else:
                    fallback.append(ticker)
            self._refresh_progress(job_id, work)
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="cache-price") as pool:
            futures = {pool.submit(run_one, ticker, ["prices"]): ticker for ticker in fallback if not cancel.is_set()}
            for future in as_completed(futures):
                ticker = futures[future]
                item = self._safe_result(future, ticker)
                with self._lock:
                    self._jobs[job_id]["items"][ticker] = item
                self._refresh_progress(job_id, work)

        extra_types = [kind for kind in requested_types if kind in {"metrics", "earnings"}]
        if extra_types and not cancel.is_set():
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache-fundamental") as pool:
                futures = {
                    pool.submit(run_one, ticker, extra_types): ticker
                    for ticker in work if ticker in selected and not cancel.is_set()
                }
                for future in as_completed(futures):
                    ticker = futures[future]
                    extra = self._safe_result(future, ticker)
                    with self._lock:
                        current = self._jobs[job_id]["items"].setdefault(ticker, {"ticker": ticker, "warnings": []})
                        for key in extra_types:
                            current[key] = extra.get(key)
                        current.setdefault("warnings", []).extend(extra.get("warnings", []))
                    self._refresh_progress(job_id, work)

        with self._lock:
            job = self._jobs[job_id]
            completed = failed = 0
            for ticker in work:
                item = job["items"].get(ticker)
                if item is None:
                    continue
                values = [value for key, value in item.items() if key in {"prices", "metrics", "earnings"} and value]
                if any(value.get("status") in {"failed", "no_data"} for value in values):
                    failed += 1
                else:
                    completed += 1
            cancelled = len(work) - completed - failed if cancel.is_set() else 0
            job["progress"] = {"total": len(work), "completed": completed, "failed": failed, "cancelled": cancelled}
            if cancel.is_set():
                job["status"] = "cancelled"
            elif failed and completed:
                job["status"] = "partial"
            elif failed:
                job["status"] = "failed"
            else:
                job["status"] = "completed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()

    def _refresh_progress(self, job_id: str, work: list[str]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            requested = set(job["data_types"])
            completed = failed = 0
            for ticker, item in job["items"].items():
                required = set(requested if ticker in job["tickers"] else ["prices"])
                values = [item.get(kind) for kind in required]
                if not values or any(value is None for value in values):
                    continue
                if any(value.get("status") in {"failed", "no_data"} for value in values):
                    failed += 1
                else:
                    completed += 1
            job["progress"] = {
                "total": len(work), "completed": completed, "failed": failed,
                "cancelled": max(0, len(work) - completed - failed) if self._cancel[job_id].is_set() else 0,
            }

    @staticmethod
    def _safe_result(future, ticker: str) -> dict:
        try:
            return future.result()
        except Exception as exc:
            return {"ticker": ticker, "warnings": [], "prices": {"status": "failed", "error_category": "internal", "error": type(exc).__name__}}


_managers: dict[str, CacheJobManager] = {}
_manager_lock = RLock()


def get_cache_job_manager(db_path: str) -> CacheJobManager:
    with _manager_lock:
        manager = _managers.get(db_path)
        if manager is None:
            manager = CacheJobManager(db_path)
            _managers[db_path] = manager
        return manager
