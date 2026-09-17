"""Offline extraction checks; never open the user's databases or call an LLM."""
import os
import json
import pytest
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient


def test_empty_startup_in_isolated_process(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(root),
               FUND_DB_PATH=str(tmp_path / "fund.db"),
               LLM_DB_PATH=str(tmp_path / "providers.db"),
               PROMPT_CACHE_DIR=str(tmp_path / "prompts"))
    script = '''
import sys
from fastapi.testclient import TestClient
from research_app.backend.main import app
for _ in range(2):
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        for path in ['/dashboard/securities', '/dashboard/universes',
                     '/dashboard/cache/list', '/dashboard/cache/jobs',
                     '/dashboard/llm/providers', '/dashboard/llm/options',
                     '/dashboard/sim/runs']:
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)
        assert client.get('/flows').status_code == 404
        assert client.get('/dashboard/status').status_code == 404
assert not any(name.startswith('app.backend') for name in sys.modules)
assert 'hedge_fund.run_daemon' not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_paths_do_not_depend_on_cwd(tmp_path, monkeypatch):
    from research_app.backend.config import ROOT, load_settings
    monkeypatch.chdir(tmp_path)
    for key in ('FUND_DB_PATH', 'LLM_DB_PATH', 'FUND_SPEC_PATH', 'PROMPT_CACHE_DIR'):
        monkeypatch.setenv(key, 'relative/example')
    settings = load_settings()
    assert all(value == ROOT / 'relative/example' for value in vars(settings).values())


def test_reused_deterministic_runner_and_api_parity(tmp_path, monkeypatch):
    # Reuse the pre-migration fixed fake model, data and T/T+1 assertions.
    from hedge_fund.simulation.test_historical_semantics import (
        test_runner_uses_prior_signal_next_open_and_isolated_sim_tables,
    )
    test_runner_uses_prior_signal_next_open_and_isolated_sim_tables(tmp_path, monkeypatch)
    from research_app.backend.routes import simulations
    from research_app.backend.main import app
    db = str(tmp_path / 'simulation.db')
    monkeypatch.setattr(simulations, '_DB_PATH', db)
    # No lifespan: avoids even opening the configured live provider database.
    after = TestClient(app)
    golden = json.loads((Path(__file__).parent / 'fixtures/migration-baseline.json').read_text())
    result = after.get('/dashboard/sim/result/1').json()
    assert [row['nav'] for row in result['nav_curve']] == pytest.approx(golden['nav'])
    assert [row['benchmark_nav'] for row in result['nav_curve']] == golden['benchmark_nav']
    assert [{key: row[key] for key in golden['fills'][0]} for row in result['trades']] == golden['fills']
    for path in ['/dashboard/sim/runs', '/dashboard/sim/result/1',
                 '/dashboard/sim/1/cycles', '/dashboard/sim/1/cycles/1']:
        migrated = after.get(path)
        assert migrated.status_code == 200
    from hedge_fund.simulation.audit import get_cycle_audit
    assert after.get('/dashboard/sim/1/cycles/1').json() == get_cycle_audit(1, 1, db)
