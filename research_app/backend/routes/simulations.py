from __future__ import annotations
import logging
from datetime import date
from fastapi import APIRouter, HTTPException
from research_app.backend.config import settings
from .schemas import SimRunRequest, ResolvedSimulationLlm

router = APIRouter(prefix="/dashboard", tags=["simulations"])
logger = logging.getLogger(__name__)
_DB_PATH = str(settings.fund_db)

def _fund_path() -> str:
    return str(settings.fund_spec)

def _resolve_simulation_llm(data: SimRunRequest, required: bool):
    """Resolve one immutable client for this request/run."""
    if data.llm_connection_id is not None:
        from research_app.backend.database.connection import SessionLocal
        from research_app.backend.services.llm_provider_service import resolve_connection
        from v2.llm import LlmProtocol, LlmRuntimeConfig, make_connection_llm
        from v2.llm.adapter_registry import get_vendor

        session = SessionLocal()
        try:
            snapshot = resolve_connection(session, data.llm_connection_id, data.model or "")
        finally:
            session.close()
        vendor = get_vendor(snapshot.vendor)
        session_id = vendor.new_session_id()
        client = make_connection_llm(LlmRuntimeConfig(
            vendor=snapshot.vendor,
            protocol=LlmProtocol(snapshot.protocol),
            model=data.model or "",
            base_url=snapshot.base_url,
            api_key=snapshot.api_key,
            session_id=session_id,
        ))
        return ResolvedSimulationLlm(
            client=client,
            provider=snapshot.vendor,
            protocol=snapshot.protocol,
            model=data.model or "",
            connection_id=snapshot.id,
            connection_name=snapshot.name,
            base_url=snapshot.base_url,
            session_id=session_id,
        )

    if data.provider is None:
        if not required:
            return None
        from v2.llm import get_llm
        client = get_llm()  # compatibility for older API callers and CLI-style setup
        return ResolvedSimulationLlm(
            client=client,
            provider=getattr(client, "provider", type(client).__name__),
            protocol=getattr(client, "protocol", None),
            model=client.model,
        )

    from research_app.backend.database.connection import SessionLocal
    from research_app.backend.services.v2_llm_service import resolve_credential
    from v2.llm import make_llm, validate_selection

    provider, model = validate_selection(data.provider, data.model or "")
    session = SessionLocal()
    try:
        credential = resolve_credential(provider, session)
    finally:
        session.close()
    client = make_llm(provider, model, credential=credential)
    return ResolvedSimulationLlm(
        client=client,
        provider=provider,
        protocol=getattr(client, "protocol", None),
        model=model,
    )


def _simulation_preflight(data: SimRunRequest, resolved_llm=None) -> dict:
    from v2.fund import load_spec
    from v2.simulation.runner import (
        _trading_days,
        disable_unavailable_models,
        estimate_persona_event_schedule,
        validate_cached_data,
    )

    tickers = data.tickers
    start_date, end_date = data.start_date.isoformat(), data.end_date.isoformat()
    benchmark = data.benchmark
    spec = load_spec(_fund_path())
    require_earnings = any(model.name == "pead" for strategy in spec.strategies for model in strategy.models)
    errors, warnings = validate_cached_data(
        _DB_PATH, tickers, benchmark, start_date, end_date, require_earnings,
    )
    if errors:
        raise HTTPException(status_code=422, detail={
            "message": "simulation data preflight failed", "errors": errors,
        })
    warnings.extend(disable_unavailable_models(spec, _DB_PATH, tickers, end_date))
    from v2.signals import ALPHA_MODEL_REGISTRY, LLMAgent
    persona_names = {
        model.name
        for strategy in spec.strategies
        for model in strategy.models
        if issubclass(ALPHA_MODEL_REGISTRY[model.name], LLMAgent)
    }
    provider = "none"
    model_name = "none"
    estimate = 0
    event_estimate = {
        "estimated_refresh_events": 0,
        "persona_count": len(persona_names),
        "event_reason_counts": {
            reason: 0 for reason in (
                "bootstrap", "new_filing", "actionable_earnings",
                "valuation_change", "max_age", "universe_entry",
            )
        },
    }
    trading_days = _trading_days(_DB_PATH, benchmark, start_date, end_date)
    llm = resolved_llm if resolved_llm is not None else _resolve_simulation_llm(
        data, required=bool(persona_names)
    )
    if llm is not None:
        provider = getattr(llm, "provider", type(llm).__name__)
        model_name = llm.model
    if persona_names:
        event_estimate = estimate_persona_event_schedule(
            _DB_PATH, tickers, trading_days, persona_names, spec.persona_refresh,
        )
        estimate = event_estimate["estimated_llm_calls"]
    result = {
        "estimated_llm_calls": estimate,
        "estimate_kind": "event_schedule_upper_bound",
        **event_estimate,
        "persona_refresh_policy": spec.persona_refresh.model_dump(),
        "provider": provider,
        "model": model_name,
        "benchmark": benchmark,
        "trading_days": len(trading_days),
        "enabled_models": [model.name for strategy in spec.strategies for model in strategy.models],
        "warnings": warnings,
    }
    logger.info(
        "simulation preflight: tickers=%s benchmark=%s range=%s..%s calls=%d provider=%s model=%s warnings=%s",
        tickers, benchmark, start_date, end_date, estimate, provider, model_name, warnings,
    )
    return result


@router.post("/sim/preflight")
def sim_preflight(data: SimRunRequest):
    """Always return the model-call estimate before starting a simulation."""
    try:
        return _simulation_preflight(data)
    except HTTPException:
        raise
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sim/run")
def sim_run(data: SimRunRequest):
    """Start a backtest simulation using cached data.

    Body: {
        "tickers": ["AAPL"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "name": ""
    }
    """
    tickers, start_date, end_date = data.tickers, data.start_date.isoformat(), data.end_date.isoformat()
    capital, name = data.initial_capital, data.name

    try:
        resolved = (
            _resolve_simulation_llm(data, required=True)
            if data.llm_connection_id is not None or data.provider is not None
            else None
        )
        preflight = _simulation_preflight(data, resolved_llm=resolved)
        if not data.confirm_cost:
            raise HTTPException(status_code=409, detail={
                "message": "LLM call confirmation required",
                **preflight,
            })
        from v2.simulation.runner import SimRunner
        if resolved is None:
            resolved = _resolve_simulation_llm(data, required=preflight["provider"] != "none")
        llm = getattr(resolved, "client", resolved)
        sim_id = SimRunner.create(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=capital,
            benchmark=data.benchmark,
            db_path=_DB_PATH,
            fund_spec_path=_fund_path(),
            name=name,
            llm=llm,
            llm_provider=preflight["provider"],
            llm_protocol=getattr(resolved, "protocol", None),
            llm_model=preflight["model"],
            llm_connection_id=getattr(resolved, "connection_id", None),
            llm_connection_name=getattr(resolved, "connection_name", None),
            llm_base_url=getattr(resolved, "base_url", None),
        )
        runner = SimRunner._get(sim_id)
        if runner is None:
            raise HTTPException(status_code=500, detail="failed to create runner")
        runner.start()
        return {"sim_id": sim_id, "status": "started"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sim run failed")
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/sim/status/{sim_id}")
def sim_status(sim_id: int):
    """Get simulation progress."""
    try:
        from v2.simulation.runner import get_sim_status
        result = get_sim_status(sim_id, _DB_PATH)
        if result is None:
            raise HTTPException(status_code=404, detail="sim not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sim/result/{sim_id}")
def sim_result(sim_id: int):
    """Get full simulation results."""
    try:
        from v2.simulation.runner import get_sim_result
        result = get_sim_result(sim_id, _DB_PATH)
        if result is None:
            raise HTTPException(status_code=404, detail="sim not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sim/{sim_id}/cycles")
def sim_cycles(
    sim_id: int,
    date: str | None = None,
    signal_date: str | None = None,
    execution_date: str | None = None,
    ticker: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List indexed decision-cycle audit summaries for one simulation."""
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(status_code=422, detail="invalid audit pagination")
    try:
        from v2.simulation.audit import list_cycle_audits

        result = list_cycle_audits(
            sim_id,
            _DB_PATH,
            date=date,
            signal_date=signal_date,
            execution_date=execution_date,
            ticker=ticker,
            limit=limit,
            offset=offset,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="sim not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("cycle audit list failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sim/{sim_id}/cycles/{cycle_id}")
def sim_cycle_detail(sim_id: int, cycle_id: int):
    """Return one full serialized cycle after run ownership validation."""
    try:
        from v2.simulation.audit import get_cycle_audit

        result = get_cycle_audit(sim_id, cycle_id, _DB_PATH)
        if result is None:
            raise HTTPException(status_code=404, detail="cycle not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("cycle audit detail failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sim/runs")
def sim_runs():
    """List all simulation runs."""
    try:
        from v2.simulation.runner import list_sim_runs
        return {"runs": list_sim_runs(_DB_PATH)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


