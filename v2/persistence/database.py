"""SQLAlchemy engine and session factory."""

from __future__ import annotations

from pathlib import Path
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from v2.persistence.models import Base

_factories: dict[str, sessionmaker] = {}
_engines: dict[str, object] = {}
_lock = threading.RLock()


def _key(db_path: str) -> str:
    return str(Path(db_path).expanduser().resolve())


def init_db(db_path: str = "fund.db") -> sessionmaker:
    """Initialize the database engine and create all tables."""
    key = _key(db_path)
    with _lock:
        if key not in _factories:
            engine = create_engine(f"sqlite:///{key}", echo=False)
            Base.metadata.create_all(bind=engine)
            _migrate(engine)
            _engines[key] = engine
            _factories[key] = sessionmaker(bind=engine, expire_on_commit=False)
        return _factories[key]


def get_session(db_path: str = "fund.db") -> Session:
    """Return a new database session. Caller must close it."""
    return init_db(db_path)()


def _migrate(engine) -> None:
    """Small additive SQLite migration; never drops or rewrites user data."""
    from sqlalchemy import inspect, text
    wanted = {
        "sim_run": {
            "error_message": "TEXT",
            "completed_at": "VARCHAR(26)",
            "warnings": "TEXT NOT NULL DEFAULT '[]'",
            "models": "TEXT NOT NULL DEFAULT '[]'",
        },
        "metrics_cache": {
            "filing_date_source": "VARCHAR(32) NOT NULL DEFAULT 'estimated_45d'",
        },
    }
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        for table, columns in wanted.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
