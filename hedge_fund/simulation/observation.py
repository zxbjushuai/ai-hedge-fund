"""Run-local, credential-free telemetry. Never accepts prompts or response bodies."""
from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
import time
import uuid
import hashlib

CURRENT_CALL = ContextVar("simulation_call", default=None)
HTTP_SLOTS = threading.BoundedSemaphore(8)


def emit(event: str, **fields) -> None:
    context = CURRENT_CALL.get()
    if context:
        observer, identity = context
        observer.emit(event, **(identity | fields))


def http_request(request) -> None:
    # Deliberately do not log URL, headers or payload.
    context = CURRENT_CALL.get()
    if context:
        _, identity = context
        identity["attempt_number"] = identity.get("attempt_number", 0) + 1
        identity["_http_started"] = time.monotonic()
        identity.pop("last_http_status", None)
    emit("http_attempt", http_status=None)


def http_response(response) -> None:
    context = CURRENT_CALL.get()
    if context:
        context[1]["last_http_status"] = response.status_code
    headers = getattr(response, "headers", {})
    request_id = headers.get("x-request-id") or headers.get("request-id")
    elapsed = time.monotonic() - context[1]["_http_started"] if context and "_http_started" in context[1] else None
    emit("http_response", http_status=response.status_code, http_elapsed_seconds=elapsed,
         request_id_hash=hashlib.sha256(request_id.encode()).hexdigest()[:24] if request_id else None)


def http_failure(exc: Exception) -> None:
    from hedge_fund.failures import classify_llm_failure
    failure = classify_llm_failure(exc)
    context = CURRENT_CALL.get()
    elapsed = time.monotonic() - context[1]["_http_started"] if context and "_http_started" in context[1] else None
    emit("http_attempt_failed", http_status=None, category=failure.category,
         reason=failure.message, exception_type=type(exc).__name__, http_elapsed_seconds=elapsed)


class RunObservation:
    def __init__(self, sim_id: int, concurrency: int, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self._file = (directory / f"sim-{sim_id}.log").open("a", encoding="utf-8")
        self._lock = threading.RLock()
        self.sim_id, self.concurrency = sim_id, concurrency
        self.stage = "starting"
        self.cycle = {}
        self.active = {}
        self.recent = deque(maxlen=50)
        self.counts = Counter()
        self.queued = 0
        self.error = None
        self.updated = None
        self.identity = {}

    def emit(self, event, **fields):
        with self._lock:
            fields = {key: value for key, value in fields.items() if not key.startswith("_")}
            self.updated = datetime.now(timezone.utc).isoformat()
            if event == "created":
                self.identity = {k: fields[k] for k in ("connection_id", "provider", "protocol", "model") if k in fields}
            level = "ERROR" if event in {"failed", "simulation_failed"} else (
                "WARNING" if event in {"request_failed", "parse_failed", "http_attempt_failed"} else "INFO")
            row = dict(timestamp=self.updated, level=level, sim_id=self.sim_id, event=event) | self.identity | self.cycle | fields
            self.counts[event] += 1
            if event == "persona_result":
                status = fields.get("attempt_status")
                if status == "produced":
                    self.counts["refresh_success"] += 1
                elif status == "failed":
                    self.counts["refresh_failure"] += 1
                if fields.get("provenance") == "reused":
                    self.counts["opinion_reused"] += 1
                if fields.get("failure_category") == "insufficient_data":
                    self.counts["insufficient_data"] += 1
            if event == "http_attempt" and fields.get("attempt_number", 1) > 1:
                self.counts["http_retries"] += 1
            if fields.get("call_id") in self.active:
                self.active[fields["call_id"]]["stage"] = event
            self.recent.append(row)
            try:
                self._file.write(json.dumps(row, ensure_ascii=False) + "\n")
                self._file.flush()
            except (OSError, ValueError):
                self.error = "Simulation log write failed"
                logging.getLogger(__name__).error("Simulation %s log write failed", self.sim_id)

    def phase(self, stage, **cycle):
        with self._lock:
            self.stage = stage
            self.cycle.update(cycle)
            self.emit(stage)

    def queue(self, count):
        with self._lock:
            self.queued = count

    @contextmanager
    def call(self, **identity):
        identity = dict(call_id=uuid.uuid4().hex, **identity)
        call_id = identity["call_id"]
        started = time.monotonic()
        token = CURRENT_CALL.set((self, identity))
        with self._lock:
            self.active[call_id] = dict(**identity, started=started)
        self.emit("refresh_started", **identity)
        try:
            yield
        finally:
            self.emit("refresh_finished", **identity, elapsed_seconds=round(time.monotonic() - started, 3))
            with self._lock:
                self.active.pop(call_id, None)
            CURRENT_CALL.reset(token)

    def snapshot(self):
        with self._lock:
            return dict(available=True, stage=self.stage, **self.cycle,
                        concurrency=self.concurrency, queued=max(0, self.queued - len(self.active)),
                        active=[{k: v for k, v in item.items() if k != "started"} |
                                {"elapsed_seconds": round(time.monotonic() - item["started"], 1)}
                                for item in self.active.values()], counts=dict(self.counts),
                        recent=list(self.recent), updated_at=self.updated, error=self.error)

    def close(self):
        with self._lock:
            try:
                self._file.close()
            except OSError:
                self.error = "Simulation log close failed"
                logging.getLogger(__name__).error("Simulation %s log close failed", self.sim_id)
