from __future__ import annotations
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from v2.persistence.database import get_session, init_db
from research_app.backend.config import settings
from .schemas import UniverseCreateRequest, UniverseUpdateRequest
from .securities import _security_dict

router = APIRouter(prefix="/dashboard", tags=["universes"])
logger = logging.getLogger(__name__)
_DB_PATH = str(settings.fund_db)

def _universe_dict(session, universe) -> dict:
    from v2.persistence.models import SavedUniverseMember, Security
    rows = session.query(SavedUniverseMember, Security).join(Security, Security.id == SavedUniverseMember.security_id).filter(SavedUniverseMember.universe_id == universe.id).order_by(SavedUniverseMember.position).all()
    return {
        "id": universe.id, "name": universe.name, "market": universe.market,
        "archived": universe.archived, "created_at": universe.created_at,
        "updated_at": universe.updated_at,
        "securities": [_security_dict(security) for _, security in rows],
    }


@router.get("/universes")
def universes_list(include_archived: bool = False):
    from v2.persistence.models import SavedUniverse
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        query = session.query(SavedUniverse)
        if not include_archived:
            query = query.filter(SavedUniverse.archived.is_(False))
        return {"universes": [_universe_dict(session, row) for row in query.order_by(SavedUniverse.name).all()]}


def _replace_universe_members(session, universe_id: int, security_ids: list[int]) -> None:
    from v2.persistence.models import SavedUniverseMember, Security
    unique_ids = list(dict.fromkeys(security_ids))
    found = {
        row[0]
        for offset in range(0, len(unique_ids), 500)
        for row in session.query(Security.id).filter(
            Security.id.in_(unique_ids[offset:offset + 500]),
            Security.market == "US",
            Security.selectable.is_(True),
        ).all()
    }
    if found != set(unique_ids):
        raise HTTPException(status_code=422, detail="one or more securities are missing or not selectable")
    session.query(SavedUniverseMember).filter_by(universe_id=universe_id).delete()
    for position, security_id in enumerate(unique_ids):
        session.add(SavedUniverseMember(universe_id=universe_id, security_id=security_id, position=position))


@router.post("/universes", status_code=201)
def universe_create(data: UniverseCreateRequest):
    from v2.persistence.models import SavedUniverse
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        row = SavedUniverse(name=data.name, market="US")
        session.add(row)
        try:
            session.flush()
            _replace_universe_members(session, row.id, data.security_ids)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="universe name already exists") from exc
        return _universe_dict(session, row)


@router.patch("/universes/{universe_id}")
def universe_update(universe_id: int, data: UniverseUpdateRequest):
    from v2.persistence.models import SavedUniverse
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        row = session.get(SavedUniverse, universe_id)
        if row is None:
            raise HTTPException(status_code=404, detail="universe not found")
        if data.name is not None:
            row.name = data.name.strip()
        if data.archived is not None:
            row.archived = data.archived
        if data.security_ids is not None:
            _replace_universe_members(session, row.id, data.security_ids)
        row.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="universe name already exists") from exc
        return _universe_dict(session, row)


