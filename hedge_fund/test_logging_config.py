from __future__ import annotations

import logging

from hedge_fund.logging_config import DailyFileHandler


def test_daily_handler_writes_to_dated_directory(tmp_path):
    handler = DailyFileHandler(tmp_path)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "simulation started", (), None)
    handler.emit(record)
    path = handler.current_path
    handler.close()

    assert path.parent.parent == tmp_path
    assert path.name == "backend.log"
    assert path.read_text(encoding="utf-8") == "INFO simulation started\n"
