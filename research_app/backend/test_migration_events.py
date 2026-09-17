"""Integrated offline baseline: event engine, execution, actions and audit."""
import json
import pytest
from pathlib import Path

from v2.data.models import FinancialMetrics
from v2.persistence.database import get_session
from v2.persistence.models import MetricsCache, PriceCache, SimCycleRecord, SimPersonaState
from v2.simulation.runner import SimRunner, get_sim_result
from v2.simulation.test_persona_state import SequenceLlm, RESPONSE


@pytest.fixture
def event_action_run(tmp_path, monkeypatch):
    monkeypatch.setenv('PROMPT_CACHE_DIR', str(tmp_path / 'prompts'))
    db = str(tmp_path / 'simulation.db')
    with get_session(db) as session:
        for day, price in [('2024-01-08', 10), ('2024-01-09', 10),
                           ('2024-01-10', 5), ('2024-01-11', 5)]:
            session.add(PriceCache(ticker='AAA', date=day, open=price,
                high=price, low=price, close=price, adjusted_close=5,
                split_ratio=2 if day == '2024-01-10' else 0,
                dividend=0.2 if day == '2024-01-10' else 0))
            session.add(PriceCache(ticker='SPY', date=day, open=100,
                high=100, low=100, close=100, adjusted_close=100))
        for day in ['2023-01-01', '2023-04-01', '2023-07-01', '2023-10-01']:
            metric = FinancialMetrics(ticker='AAA', report_period=day,
                filing_date=day, period='ttm', market_cap=1000000)
            session.add(MetricsCache(ticker='AAA', report_period=day,
                filing_date=day, filing_date_source='fixture',
                data=metric.model_dump_json(exclude={'ticker'})))
        session.commit()
    llm = SequenceLlm([RESPONSE, RESPONSE])
    sim_id = SimRunner.create(tickers=['AAA'], start_date='2024-01-08',
        end_date='2024-01-11', initial_capital=1000, db_path=db,
        fund_spec_path=str(Path(__file__).parent / 'fixtures/migration-events.yaml'),
        benchmark='SPY', fee_rate=0, llm=llm)
    SimRunner._get(sim_id)._run()
    result = get_sim_result(sim_id, db)
    assert result['status'] == 'completed', result['error_message']
    with get_session(db) as session:
        records = [json.loads(row.payload) for row in session.query(SimCycleRecord)
                   .order_by(SimCycleRecord.cycle_number).all()]
        assert session.query(SimPersonaState).count() == 1
    assert records[1]['marks']['AAA'] == 10
    assert records[1]['sizing_marks']['AAA'] == 5
    assert records[1]['equity_before'] == 1040
    actual = {
        'calls': llm.calls,
        'nav': [row['nav'] for row in result['nav_curve']],
        'fills': [{k: row[k] for k in ('date', 'side', 'quantity', 'price')}
                  for row in result['trades']],
        'events': [[{'provenance': e['provenance'], 'reasons': e['trigger_reasons']}
                    for e in record['persona_events']] for record in records],
        'actions': [r['corporate_actions'] for r in records],
    }
    return actual, result


def test_event_and_action_migration_baseline(event_action_run):
    # Corrected baseline: split preserves value; only dividend cash is reinvested.
    actual, _ = event_action_run
    golden = Path(__file__).parent / 'fixtures/migration-events.json'
    assert actual == json.loads(golden.read_text()), json.dumps(actual, indent=2)


def test_split_does_not_create_unlevered_overdraft(event_action_run):
    # Regression: pre-fix sizing used $2040 and overdrew cash by $1000.
    _, result = event_action_run
    assert all(row['cash'] >= 0 for row in result['nav_curve']), result['nav_curve']
