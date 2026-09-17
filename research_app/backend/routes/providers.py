from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from research_app.backend.database import get_db
from research_app.backend.config import settings
from .schemas import LlmProviderCreateRequest, LlmProviderUpdateRequest, LlmModelCreateRequest, LlmModelUpdateRequest

router = APIRouter(prefix="/dashboard", tags=["providers"])
logger = logging.getLogger(__name__)
_DB_PATH = str(settings.fund_db)

@router.get("/llm/providers")
def llm_provider_connections(db: Session = Depends(get_db)):
    from research_app.backend.database.models import LlmProviderConnection
    from research_app.backend.services.llm_provider_service import connection_dict, ensure_provider_tables

    ensure_provider_tables(db)
    rows = db.query(LlmProviderConnection).order_by(LlmProviderConnection.name).all()
    return {"providers": [connection_dict(row) for row in rows]}


@router.post("/llm/providers", status_code=201)
def create_llm_provider(data: LlmProviderCreateRequest, db: Session = Depends(get_db)):
    from research_app.backend.database.models import LlmProviderConnection
    from research_app.backend.services.llm_provider_service import (
        connection_dict, ensure_provider_tables, normalize_connection_base_url,
    )
    from hedge_fund.llm.registry import legacy_provider_type

    ensure_provider_tables(db)
    vendor = (data.vendor or "").strip().lower()
    protocol = (data.protocol or "").strip()
    secret = data.api_key.get_secret_value().strip()
    if not secret:
        raise HTTPException(status_code=422, detail="api_key cannot be empty")
    try:
        base_url = normalize_connection_base_url(data.base_url, vendor, protocol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.query(LlmProviderConnection).filter(LlmProviderConnection.name == data.name).first():
        raise HTTPException(status_code=409, detail="connection name already exists")
    row = LlmProviderConnection(
        name=data.name,
        vendor=vendor,
        protocol=protocol,
        provider_type=legacy_provider_type(vendor, protocol),
        base_url=base_url,
        api_key=secret,
        enabled=data.enabled,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="connection name already exists") from exc
    db.refresh(row)
    return connection_dict(row)


@router.patch("/llm/providers/{connection_id}")
def update_llm_provider(
    connection_id: int,
    data: LlmProviderUpdateRequest,
    db: Session = Depends(get_db),
):
    from research_app.backend.database.models import LlmProviderConnection, LlmProviderModel
    from research_app.backend.services.llm_provider_service import (
        connection_dict, connection_kind, get_connection,
        normalize_connection_base_url,
    )

    try:
        row = get_connection(db, connection_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    changes = data.model_dump(exclude_unset=True)
    endpoint_changed = False
    if "name" in changes:
        name = changes["name"].strip()
        if not name:
            raise HTTPException(status_code=422, detail="name cannot be empty")
        duplicate = db.query(LlmProviderConnection).filter(
            LlmProviderConnection.name == name,
            LlmProviderConnection.id != connection_id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="connection name already exists")
        row.name = name
    if "base_url" in changes:
        try:
            vendor, protocol = connection_kind(row)
            normalized = normalize_connection_base_url(
                changes["base_url"] or "", vendor, protocol,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        endpoint_changed = endpoint_changed or normalized != row.base_url
        row.base_url = normalized
    if changes.get("api_key"):
        replacement = changes["api_key"].get_secret_value().strip()
        if replacement:
            endpoint_changed = endpoint_changed or replacement != row.api_key
            row.api_key = replacement
    if "enabled" in changes:
        row.enabled = changes["enabled"]
    if endpoint_changed:
        db.query(LlmProviderModel).filter(
            LlmProviderModel.connection_id == row.id,
            LlmProviderModel.source == "remote",
        ).update({"available": False}, synchronize_session=False)
        row.last_tested_at = None
        row.last_test_status = None
        row.last_error = None
        row.last_synced_at = None
    db.commit()
    db.refresh(row)
    return connection_dict(row)


@router.post("/llm/providers/{connection_id}/test")
async def test_llm_provider(connection_id: int, db: Session = Depends(get_db)):
    from research_app.backend.services.llm_provider_service import get_connection, test_connection

    try:
        row = get_connection(db, connection_id)
        models = await test_connection(db, row)
        return {"status": "success", "model_count": len(models)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM connection test failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="unable to reach model endpoint") from exc


@router.post("/llm/providers/{connection_id}/models/sync")
async def sync_llm_provider_models(connection_id: int, db: Session = Depends(get_db)):
    from research_app.backend.services.llm_provider_service import get_connection, model_dict, sync_models

    try:
        row = get_connection(db, connection_id)
        models = await sync_models(db, row)
        return {"models": [model_dict(model) for model in models]}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM model sync failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="unable to synchronize models") from exc


@router.get("/llm/providers/{connection_id}/models")
def list_llm_provider_models(connection_id: int, db: Session = Depends(get_db)):
    from research_app.backend.database.models import LlmProviderModel
    from research_app.backend.services.llm_provider_service import get_connection, model_dict

    try:
        row = get_connection(db, connection_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    models = db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == row.id
    ).order_by(LlmProviderModel.display_name).all()
    return {"models": [model_dict(model) for model in models]}


@router.post("/llm/providers/{connection_id}/models", status_code=201)
def create_llm_provider_model(
    connection_id: int,
    data: LlmModelCreateRequest,
    db: Session = Depends(get_db),
):
    from research_app.backend.database.models import LlmProviderModel
    from research_app.backend.services.llm_provider_service import get_connection, model_dict

    try:
        row = get_connection(db, connection_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    exists = db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == row.id,
        LlmProviderModel.model_id == data.model_id,
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="model already exists for this connection")
    model = LlmProviderModel(
        connection_id=row.id,
        model_id=data.model_id,
        display_name=(data.display_name or data.model_id).strip(),
        source="manual",
        enabled=data.enabled,
        available=True,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model_dict(model)


@router.patch("/llm/providers/{connection_id}/models/{model_id:path}")
def update_llm_provider_model(
    connection_id: int,
    model_id: str,
    data: LlmModelUpdateRequest,
    db: Session = Depends(get_db),
):
    from research_app.backend.database.models import LlmProviderModel
    from research_app.backend.services.llm_provider_service import get_connection, model_dict

    try:
        get_connection(db, connection_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    model = db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == connection_id,
        LlmProviderModel.model_id == model_id,
    ).first()
    if model is None:
        raise HTTPException(status_code=404, detail="LLM model not found")
    changes = data.model_dump(exclude_unset=True)
    if "display_name" in changes and changes["display_name"] is not None:
        model.display_name = changes["display_name"].strip() or model.model_id
    if "enabled" in changes:
        model.enabled = changes["enabled"]
    db.commit()
    db.refresh(model)
    return model_dict(model)


@router.get("/llm/options")
def llm_options(db: Session = Depends(get_db)):
    from research_app.backend.database.models import LlmProviderConnection, LlmProviderModel
    from research_app.backend.services.llm_provider_service import ensure_provider_tables

    ensure_provider_tables(db)
    connections = db.query(LlmProviderConnection).filter(
        LlmProviderConnection.enabled.is_(True),
    ).order_by(LlmProviderConnection.name).all()
    options = []
    for connection in connections:
        if not connection.api_key:
            continue
        models = db.query(LlmProviderModel).filter(
            LlmProviderModel.connection_id == connection.id,
            LlmProviderModel.enabled.is_(True),
        ).order_by(LlmProviderModel.display_name).all()
        models = [model for model in models if model.source == "manual" or model.available]
        if models:
            options.append({
                "id": connection.id,
                "name": connection.name,
                "provider_type": connection.provider_type,
                "vendor": connection.vendor,
                "protocol": connection.protocol,
                "models": [
                    {"model_id": model.model_id, "display_name": model.display_name}
                    for model in models
                ],
            })
    return {"providers": options}


async def llm_models():
    """Legacy internal helper; no longer registered as a public Web route."""
    from research_app.backend.database.connection import SessionLocal
    from research_app.backend.services.v2_llm_service import credential_configured
    from hedge_fund.llm import catalog

    session = SessionLocal()
    try:
        from research_app.backend.services.ollama_service import OllamaService
        ollama_models = await OllamaService().get_available_models()
        providers = []
        for provider in catalog():
            models = provider["models"]
            configured = credential_configured(provider["id"], session)
            if provider["id"] == "ollama":
                models = [
                    {"display_name": item["display_name"], "model": item["model_name"]}
                    for item in ollama_models
                ]
                configured = bool(models)
            providers.append({
                "id": provider["id"],
                "display_name": provider["display_name"],
                "credential_configured": configured,
                "models": models,
            })
        return {"providers": providers}
    finally:
        session.close()


