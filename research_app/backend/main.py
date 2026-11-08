"""Standalone Web API: retained features only, no trading scheduler."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hedge_fund.persistence.database import init_db
from research_app.backend.config import settings
from research_app.backend.database.connection import SessionLocal
from research_app.backend.routes import (
    cache,
    providers,
    securities,
    simulations,
    system,
    universes,
)
from research_app.backend.services.llm_provider_service import ensure_provider_tables
from research_app.backend.services.startup_recovery import recover_startup_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.fund_db.parent.mkdir(parents=True, exist_ok=True)
    settings.llm_db.parent.mkdir(parents=True, exist_ok=True)
    init_db(str(settings.fund_db))
    with SessionLocal() as db:
        ensure_provider_tables(db)
    recover_startup_state(str(settings.fund_db))
    yield


app = FastAPI(title="Research simulation API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
for module in (securities, universes, cache, providers, simulations, system):
    app.include_router(module.router)


@app.get("/health")
def health():
    return {"status": "ok"}
