"""Stable market-data failure categories used by cache jobs and APIs."""

from __future__ import annotations


class MarketDataError(RuntimeError):
    category = "transport_error"
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message[:500])
        self.retry_after = retry_after


class NoDataError(MarketDataError):
    category = "no_data"
    retryable = False


class InvalidSymbolError(MarketDataError):
    category = "invalid_symbol"
    retryable = False


class RateLimitedError(MarketDataError):
    category = "rate_limited"


class MarketDataTimeoutError(MarketDataError):
    category = "timeout"


class MarketDataParseError(MarketDataError):
    category = "parse_error"
    retryable = False


class UnsupportedMarketError(MarketDataError):
    category = "unsupported_market"
    retryable = False


def classify_market_error(exc: Exception) -> MarketDataError:
    if isinstance(exc, MarketDataError):
        return exc
    text = str(exc).lower()
    if "rate limit" in text or "too many requests" in text or "429" in text:
        return RateLimitedError("market-data service rate limited the request")
    if isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in text:
        return MarketDataTimeoutError("market-data request timed out")
    if "delisted" in text or "no timezone found" in text or "invalid ticker" in text:
        return InvalidSymbolError("ticker is invalid, delisted, or unsupported")
    return MarketDataError(f"market-data request failed: {type(exc).__name__}")
