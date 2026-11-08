import os
import subprocess
import sys
from pathlib import Path


def test_startup_recovers_orphaned_run_and_reports_status(tmp_path):
    root = Path(__file__).resolve().parents[2]
    fund_db = tmp_path / "fund.db"
    env = dict(
        os.environ,
        PYTHONPATH=str(root),
        FUND_DB_PATH=str(fund_db),
        LLM_DB_PATH=str(tmp_path / "providers.db"),
        PROMPT_CACHE_DIR=str(tmp_path / "prompts"),
    )
    script = """
from hedge_fund.persistence.database import get_session, init_db
from hedge_fund.persistence.models import SimRun

db = __import__("os").environ["FUND_DB_PATH"]
init_db(db)
with get_session(db) as session:
    session.add(SimRun(
        name="interrupted", tickers='["AAPL"]',
        start_date="2024-01-02", end_date="2024-01-03",
        initial_capital=1000.0, status="running",
        current_day=1, total_days=2,
    ))
    session.commit()

from fastapi.testclient import TestClient
from research_app.backend.main import app

with TestClient(app) as client:
    status = client.get("/dashboard/system/status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["startup_recovery"]["orphaned_simulations_failed"] == 1
    assert body["simulations"]["failed"] == 1
    assert body["simulations"]["running"] == 0
    assert body["cache_jobs"]["total"] == 0
    assert body["cache_jobs"]["active"] == 0
    detail = client.get("/dashboard/sim/status/1").json()
    assert detail["status"] == "failed"
    assert "backend restart" in detail["error_message"].lower()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
