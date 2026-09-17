"""Reuse existing connection tables at an explicit, stable database path."""
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker
from research_app.backend.config import settings

DATABASE_PATH = settings.llm_db
DATABASE_URL = URL.create("sqlite", database=str(DATABASE_PATH))
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    with SessionLocal() as db:
        yield db
