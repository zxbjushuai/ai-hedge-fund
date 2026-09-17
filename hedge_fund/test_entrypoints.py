"""Offline acceptance of upstream entrypoints after Web isolation."""
import asyncio
import json
import sys


def test_cli_saves_file_receipt_without_web(tmp_path, monkeypatch, capsys):
    from hedge_fund import run
    from hedge_fund.fund import Fund
    from hedge_fund.pipeline.test_run_cycle import FakeAnalyst, FakeDataClient

    class Client(FakeDataClient):
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    mandate = tmp_path / 'fund.yaml'
    mandate.write_text('name: cli-test\nstrategies:\n  - name: value\n'
                       '    models: [{name: buffett}]\nrisk: {max_position_pct: 1, max_gross_exposure: 1}\n')
    output = tmp_path / 'receipt.json'
    monkeypatch.setattr(run, 'apply_credentials', lambda: None)
    monkeypatch.setattr(run, 'ensure_mandates_dir', lambda: tmp_path)
    monkeypatch.setattr(run, 'FDClient', lambda: Client({'AAPL': 10}))
    monkeypatch.setattr(run, 'CachedDataClient', lambda client: client)
    monkeypatch.setattr(run, 'Fund', lambda spec: Fund(spec,
        models={'value': [FakeAnalyst('buffett', {'AAPL': 1})]}))
    monkeypatch.setattr(sys, 'argv', ['aihf', str(mandate), '--tickers', 'AAPL',
                                    '--date', '2024-01-02', '--out', str(output)])
    run.main()
    receipt = json.loads(output.read_text())
    assert receipt['universe'] == ['AAPL']
    assert receipt['positions'] == {'AAPL': 10000}
    assert receipt['nav'] == 100000
    assert json.loads(capsys.readouterr().out) == receipt
    assert not list(tmp_path.glob('*.db'))


def test_textual_home_starts_without_web_or_credentials(tmp_path, monkeypatch):
    from hedge_fund.tui import app as tui
    monkeypatch.setattr(tui, 'apply_credentials', lambda: None)
    monkeypatch.setattr(tui, 'ensure_mandates_dir', lambda: tmp_path)
    monkeypatch.setattr(tui, '_saved_funds', lambda: [])

    async def check():
        app = tui.HedgeFundApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.HomeScreen)
    asyncio.run(check())
