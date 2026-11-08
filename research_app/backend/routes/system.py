from fastapi import APIRouter, HTTPException

from research_app.backend.config import settings

router = APIRouter(prefix="/dashboard/system", tags=["system"])
_DB_PATH = str(settings.fund_db)


@router.get("/status")
def system_status():
    """Return startup recovery and process-local runtime counts."""
    try:
        from research_app.backend.services.startup_recovery import runtime_status

        return runtime_status(_DB_PATH)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
