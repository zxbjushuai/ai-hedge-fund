"""FundSpec — a fund's mandate as data, and the Fund that lives it.

The hierarchy mirrors a real shop (see VISION.md):

    FUND      = capital slices over STRATEGIES  (master risk on the netted book)
    STRATEGY  = a blend policy over MODELS      (a "pod")
    MODEL     = an alpha model -> Signal

Models come in two kinds, and the strategy's character follows from its
staff: a strategy of LLM investor AGENTS (Buffett, Munger, ...) is a
discretionary pod — its identity is who's on the desk; a strategy powered
by quant models (PEAD, ...) is a systematic pod — its identity is the edge
it harvests. Same spec shape, same engine slot; the kind is derived, never
declared.

Specs are data (a Loop-2 ground rule): a mandate is a serializable YAML/JSON
config. The wizard, a chat LLM, and the strategy generator all emit this same
format — nothing downstream ever needs to know who authored a fund.

A `Fund` is the living counterpart: the spec plus its models instantiated
once. Models are stateful (LLM prompt caches, PEAD earnings caches), so
they must be constructed per fund — never per cycle — for caches to survive
across cycles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from v2.risk.limits import RiskLimits
from v2.llm import LLMClient
from v2.signals import ALPHA_MODEL_REGISTRY, LLMAgent
from v2.signals.base import AlphaModel


class PersonaRefreshPolicy(BaseModel):
    """Deterministic refresh policy for run-scoped persona opinions."""

    model_config = ConfigDict(extra="forbid")

    valuation_change_pct: float = Field(default=20.0, gt=0)
    max_age_days: int = Field(default=90, ge=1)
    retry_backoff_trading_days: list[int] = Field(
        default_factory=lambda: [1, 2, 4, 5], min_length=1,
    )

    @field_validator("retry_backoff_trading_days")
    @classmethod
    def _positive_backoff(cls, delays: list[int]) -> list[int]:
        if any(delay < 1 for delay in delays):
            raise ValueError("retry backoff delays must be positive")
        return delays


class ModelSpec(BaseModel):
    """One signal model in a strategy — an LLM agent or a quant model."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="key into ALPHA_MODEL_REGISTRY, e.g. 'buffett'")
    weight: float = Field(default=1.0, gt=0, description="blend weight")
    params: dict[str, Any] = Field(
        default_factory=dict, description="constructor kwargs for the model"
    )


class BlendPolicy(BaseModel):
    """How a strategy's model views combine into one sleeve."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["conviction_weighted"] = "conviction_weighted"
    gross_target: float = Field(
        default=1.0, gt=0, description="desired sum of |weights| when views exist"
    )
    market_neutral: bool = Field(
        default=False,
        description="demean convictions cross-sectionally before scaling: long "
        "the best-liked names relative to the rest, short the least-liked — a "
        "dollar-neutral sleeve",
    )


class StrategySpec(BaseModel):
    """A strategy ("pod"): signal models plus the policy that blends them.

    `weight` is the fund's capital slice for this strategy, relative to its
    siblings (normalized at netting time — 2/2 means the same as 1/1). In a
    library file (v2/strategies/) it stays at the default; slices are a
    fund-assembly decision, not a property of the strategy itself.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str | None = Field(
        default=None, description="human-facing name, e.g. 'Deep Value'"
    )
    weight: float = Field(default=1.0, gt=0)
    models: list[ModelSpec] = Field(min_length=1)
    blend: BlendPolicy = Field(default_factory=BlendPolicy)

    @property
    def title(self) -> str:
        """Display name, falling back to a title-cased slug."""
        return self.display_name or self.name.replace("-", " ").title()

    @property
    def model_weights(self) -> dict[str, float]:
        """model_name -> blend weight, as portfolio construction consumes it."""
        return {m.name: m.weight for m in self.models}


class FundSpec(BaseModel):
    """A fund's complete mandate. `extra='forbid'` everywhere: YAML typos
    fail loud at load time, not silently at trade time. `risk` is MASTER
    risk — applied to the netted book after all strategies are combined."""

    model_config = ConfigDict(extra="forbid")

    name: str
    universe: list[str] | None = Field(
        default=None,
        min_length=1,
        description="optional compatibility default; run-time universe takes precedence",
    )
    strategies: list[StrategySpec] = Field(min_length=1)
    risk: RiskLimits
    capital: float = Field(default=100_000.0, gt=0)
    persona_refresh: PersonaRefreshPolicy = Field(default_factory=PersonaRefreshPolicy)

    @field_validator("universe")
    @classmethod
    def _uppercase_unique(cls, tickers: list[str] | None) -> list[str] | None:
        if tickers is None:
            return None
        upper = [t.upper() for t in tickers]
        duplicates = {t for t in upper if upper.count(t) > 1}
        if duplicates:
            raise ValueError(f"duplicate tickers in universe: {sorted(duplicates)}")
        return upper

    @field_validator("strategies")
    @classmethod
    def _unique_strategy_names(cls, strategies: list[StrategySpec]) -> list[StrategySpec]:
        names = [s.name for s in strategies]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate strategy names: {sorted(duplicates)}")
        return strategies


def normalize_universe(tickers: list[str]) -> list[str]:
    """Upper-case, trim, and de-duplicate a run-time universe in input order."""
    universe: list[str] = []
    for ticker in tickers:
        normalized = ticker.strip().upper()
        if normalized and normalized not in universe:
            universe.append(normalized)
    if not universe:
        raise ValueError("universe is empty - a run needs at least one ticker")
    return universe


def load_spec(path: str | Path) -> FundSpec:
    """Load a mandate from YAML. Validation errors carry the pydantic detail."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return FundSpec(**data)


def load_strategy(path: str | Path) -> StrategySpec:
    """Load one strategy (a library file under v2/strategies/) from YAML."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return StrategySpec(**data)


class Fund:
    """A living fund: its spec plus instantiated models, per strategy.

    Plain class, not pydantic — models hold state (LLM clients, prompt
    caches, per-ticker data caches) and are constructed exactly once here.
    A persona appearing in two strategies gets two instances; that's fine —
    the prompt cache is disk-keyed by prompt content and shared, so the
    second instance's calls are cache hits, not spend.

    The `models` override (strategy name -> instances) exists for tests to
    inject fakes; production callers let the registry build the staff.
    """

    def __init__(
        self,
        spec: FundSpec,
        models: dict[str, list[AlphaModel]] | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.spec = spec
        self.strategies: list[tuple[StrategySpec, list[AlphaModel]]] = []
        for strategy in spec.strategies:
            if models is not None:
                self.strategies.append((strategy, models[strategy.name]))
                continue
            staff = []
            for m in strategy.models:
                if m.name not in ALPHA_MODEL_REGISTRY:
                    raise ValueError(
                        f"unknown model {m.name!r} in strategy "
                        f"{strategy.name!r}; available: {sorted(ALPHA_MODEL_REGISTRY)}"
                    )
                model_class = ALPHA_MODEL_REGISTRY[m.name]
                params = dict(m.params)
                if llm is not None and issubclass(model_class, LLMAgent):
                    if "llm" in params:
                        raise ValueError(
                            f"model {m.name!r} config cannot override the run-scoped LLM"
                        )
                    params["llm"] = llm
                staff.append(model_class(**params))
            self.strategies.append((strategy, staff))
