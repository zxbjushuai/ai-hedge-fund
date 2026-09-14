"""Safe failure classification shared by signals and simulation audit."""

from __future__ import annotations

from v2.models import FailureDetail


def classify_llm_failure(exc: Exception) -> FailureDetail:
    """Classify an SDK exception without retaining its potentially secret body."""
    status = _status_code(exc)
    name = type(exc).__name__.lower()
    message = str(exc).lower()

    if status in {401, 403} or "authentication" in name or "permission" in name:
        return FailureDetail(
            category="authentication", message="LLM authentication failed", retryable=False,
        )
    if status == 429 or "ratelimit" in name or "rate limit" in message:
        return FailureDetail(
            category="rate_limit", message="LLM rate limit exceeded", retryable=True,
        )
    if "timeout" in name or "timed out" in message:
        return FailureDetail(
            category="timeout", message="LLM request timed out", retryable=True,
        )
    return FailureDetail(
        category="transport", message="LLM request failed", retryable=True,
    )


def classify_cycle_failure(exc: Exception) -> FailureDetail:
    """Return a bounded cycle-level category and a credential-safe summary."""
    module = type(exc).__module__.lower()
    name = type(exc).__name__.lower()
    message = str(exc)
    lowered = message.lower()
    status = _status_code(exc)

    if status in {401, 403}:
        category = "authentication"
        safe = "Data provider authentication failed"
        retryable = False
    elif status == 429 or "rate limit" in lowered:
        category = "rate_limit"
        safe = "Data provider rate limit exceeded"
        retryable = True
    elif "timeout" in name or "timed out" in lowered:
        category = "timeout"
        safe = "Cycle data request timed out"
        retryable = True
    elif "v2.data" in module or "fdclient" in name or "data provider" in lowered:
        category = "data_provider"
        safe = "Data provider failed while constructing the cycle"
        retryable = True
    elif isinstance(exc, ConnectionError):
        category = "transport"
        safe = "Cycle transport failed"
        retryable = True
    else:
        category = "internal"
        safe = _sanitize_local_message(message)
        retryable = False
    return FailureDetail(category=category, message=safe, retryable=retryable)


def _status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _sanitize_local_message(message: str) -> str:
    if not message:
        return "Cycle execution failed"
    lowered = message.lower()
    if any(token in lowered for token in ("api_key", "api-key", "authorization", "bearer ")):
        return "Cycle execution failed (sensitive error details omitted)"
    return message[:500]
