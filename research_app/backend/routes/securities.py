from __future__ import annotations
import logging
from fastapi import APIRouter, HTTPException, Query
from hedge_fund.persistence.database import get_session, init_db
from research_app.backend.config import settings
from .schemas import SecurityFilterRequest

router = APIRouter(prefix="/dashboard", tags=["securities"])
logger = logging.getLogger(__name__)
_DB_PATH = str(settings.fund_db)

def _security_query(session, filters: SecurityFilterRequest):
    from sqlalchemy import or_
    from hedge_fund.persistence.models import Security

    query = session.query(Security).filter(Security.market == "US")
    if filters.active:
        query = query.filter(Security.active.is_(True))
    if filters.selectable:
        query = query.filter(Security.selectable.is_(True), Security.is_test.is_(False))
    if filters.exchange:
        query = query.filter(Security.exchange == filters.exchange)
    if filters.asset_type:
        query = query.filter(Security.asset_type == filters.asset_type)
    if filters.search.strip():
        pattern = f"%{filters.search.strip()}%"
        query = query.filter(or_(Security.symbol.ilike(pattern), Security.name.ilike(pattern)))
    return query


def _security_dict(row) -> dict:
    return {
        "id": row.id, "market": row.market, "symbol": row.symbol,
        "data_symbol": row.data_symbol, "name": row.name, "exchange": row.exchange,
        "asset_type": row.asset_type, "currency": row.currency, "active": row.active,
        "selectable": row.selectable, "catalog_source": row.catalog_source,
        "synced_at": row.synced_at,
    }


def _security_order(sort_by: str, sort_dir: str):
    from hedge_fund.persistence.models import Security

    columns = {
        "symbol": Security.symbol,
        "name": Security.name,
        "exchange": Security.exchange,
        "asset_type": Security.asset_type,
    }
    column = columns[sort_by]
    return column.desc() if sort_dir == "desc" else column.asc()


@router.post("/securities/sync")
def securities_sync():
    from hedge_fund.data.cache_service import sync_us_catalog
    try:
        return sync_us_catalog(_DB_PATH)
    except Exception as exc:
        logger.exception("US security catalog synchronization failed")
        raise HTTPException(status_code=502, detail=f"catalog synchronization failed: {type(exc).__name__}") from exc


@router.get("/securities")
def securities_list(
    search: str = Query(default="", max_length=100),
    exchange: str | None = Query(default=None, max_length=32),
    asset_type: str | None = Query(default=None, pattern=r"^(equity|etf|other)$"),
    active: bool = True,
    selectable: bool = True,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    sort_by: str = Query(default="symbol", pattern=r"^(symbol|name|exchange|asset_type)$"),
    sort_dir: str = Query(default="asc", pattern=r"^(asc|desc)$"),
):
    from sqlalchemy import distinct
    from hedge_fund.persistence.models import Security

    init_db(_DB_PATH)
    filters = SecurityFilterRequest(search=search, exchange=exchange, asset_type=asset_type, active=active, selectable=selectable)
    with get_session(_DB_PATH) as session:
        query = _security_query(session, filters)
        total = query.count()
        rows = query.order_by(_security_order(sort_by, sort_dir), Security.symbol).offset((page - 1) * page_size).limit(page_size).all()
        exchanges = [row[0] for row in session.query(distinct(Security.exchange)).filter(Security.market == "US", Security.active.is_(True)).order_by(Security.exchange).all() if row[0]]
        return {"items": [_security_dict(row) for row in rows], "total": total, "page": page, "page_size": page_size, "exchanges": exchanges}


@router.get("/securities/selection")
def securities_selection(
    search: str = Query(default="", max_length=100),
    exchange: str | None = Query(default=None, max_length=32),
    asset_type: str | None = Query(default=None, pattern=r"^(equity|etf|other)$"),
    sort_by: str = Query(default="symbol", pattern=r"^(symbol|name|exchange|asset_type)$"),
    sort_dir: str = Query(default="asc", pattern=r"^(asc|desc)$"),
):
    """Return the complete filtered selection as typed IDs, not a filter token."""
    from hedge_fund.persistence.models import Security

    init_db(_DB_PATH)
    filters = SecurityFilterRequest(search=search, exchange=exchange, asset_type=asset_type)
    with get_session(_DB_PATH) as session:
        rows = _security_query(session, filters).order_by(
            _security_order(sort_by, sort_dir), Security.symbol,
        ).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "symbol": row.symbol,
                    "name": row.name,
                    "exchange": row.exchange,
                    "asset_type": row.asset_type,
                }
                for row in rows
            ],
            "total": len(rows),
        }


@router.get("/securities/{security_id}")
def security_detail(security_id: int):
    from hedge_fund.persistence.models import Security
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        row = session.get(Security, security_id)
        if row is None:
            raise HTTPException(status_code=404, detail="security not found")
        return _security_dict(row)


