from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
class CacheFetchRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=50)
    benchmark: str = "SPY"
    start_date: date
    end_date: date

    @field_validator("tickers")
    @classmethod
    def valid_tickers(cls, values):
        import re
        cleaned = [v.strip().upper() for v in values]
        if any(not re.fullmatch(r"[A-Z0-9.\-]{1,10}", v) for v in cleaned):
            raise ValueError("invalid ticker")
        return list(dict.fromkeys(cleaned))

    @field_validator("benchmark")
    @classmethod
    def valid_benchmark(cls, value):
        import re
        cleaned = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-]{1,10}", cleaned):
            raise ValueError("invalid benchmark")
        return cleaned

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if (self.end_date - self.start_date).days > 3650:
            raise ValueError("date range cannot exceed 10 years")
        return self


class SecurityFilterRequest(BaseModel):
    search: str = Field(default="", max_length=100)
    exchange: str | None = Field(default=None, max_length=32)
    asset_type: str | None = Field(default=None, pattern=r"^(equity|etf|other)$")
    active: bool = True
    selectable: bool = True


class CacheSelectionRequest(BaseModel):
    security_ids: list[int] | None = Field(default=None, max_length=20000)
    universe_id: int | None = Field(default=None, gt=0)
    filter: SecurityFilterRequest | None = None
    tickers: list[str] | None = Field(default=None, max_length=20000)

    @field_validator("tickers")
    @classmethod
    def normalize_selection_tickers(cls, values: list[str] | None):
        return None if values is None else CacheFetchRequest.valid_tickers(values)

    @model_validator(mode="after")
    def exactly_one_selection(self):
        if sum(value is not None for value in (self.security_ids, self.universe_id, self.filter, self.tickers)) != 1:
            raise ValueError("select exactly one of security_ids, universe_id, filter, or tickers")
        if self.security_ids is not None and not self.security_ids:
            raise ValueError("security_ids cannot be empty")
        if self.tickers is not None and not self.tickers:
            raise ValueError("tickers cannot be empty")
        return self


class CacheJobCreateRequest(BaseModel):
    selection: CacheSelectionRequest
    benchmark: str = "SPY"
    start_date: date
    end_date: date
    data_types: list[str] = Field(default_factory=lambda: ["prices"])
    force: bool = False

    @field_validator("benchmark")
    @classmethod
    def normalize_job_benchmark(cls, value: str):
        return CacheFetchRequest.valid_benchmark(value)

    @field_validator("data_types")
    @classmethod
    def valid_data_types(cls, values: list[str]):
        values = list(dict.fromkeys(values))
        if not values or any(value not in {"prices", "metrics", "earnings"} for value in values):
            raise ValueError("data_types must contain prices, metrics, or earnings")
        return values

    @model_validator(mode="after")
    def valid_job_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if (self.end_date - self.start_date).days > 3650:
            raise ValueError("date range cannot exceed 10 years")
        return self


class UniverseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    security_ids: list[int] = Field(min_length=1, max_length=20000)

    @field_validator("name")
    @classmethod
    def normalize_universe_name(cls, value: str):
        return value.strip()


class UniverseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    security_ids: list[int] | None = Field(default=None, min_length=1, max_length=20000)
    archived: bool | None = None


class SimRunRequest(CacheFetchRequest):
    initial_capital: float = Field(gt=0)
    name: str = Field(default="", max_length=100)
    confirm_cost: bool = False
    provider: str | None = Field(default=None, min_length=1, max_length=32)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    llm_connection_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def complete_llm_selection(self):
        if self.llm_connection_id is not None:
            if self.model is None:
                raise ValueError("model is required with llm_connection_id")
            if self.provider is not None:
                raise ValueError("provider cannot be combined with llm_connection_id")
        elif (self.provider is None) != (self.model is None):
            raise ValueError("provider and model must be supplied together")
        return self


class LlmProviderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    vendor: str | None = None
    protocol: str | None = None
    provider_type: str | None = None
    base_url: str = Field(default="", max_length=500)
    api_key: SecretStr
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def strip_required(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value

    @model_validator(mode="after")
    def complete_connection_kind(self):
        from v2.llm.registry import connection_kind_for_legacy

        if self.vendor is not None or self.protocol is not None:
            if not self.vendor or not self.protocol:
                raise ValueError("vendor and protocol must be supplied together")
        elif self.provider_type:
            self.vendor, self.protocol = connection_kind_for_legacy(self.provider_type)
        else:
            raise ValueError("vendor and protocol are required")
        return self


class LlmProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: SecretStr | None = None
    enabled: bool | None = None


class LlmModelCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    enabled: bool = True

    @field_validator("model_id")
    @classmethod
    def strip_model_id(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("model_id cannot be empty")
        return value


class LlmModelUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


@dataclass(frozen=True)
class ResolvedSimulationLlm:
    client: object
    provider: str
    protocol: str | None
    model: str
    connection_id: int | None = None
    connection_name: str | None = None
    base_url: str | None = None
    session_id: str | None = None


