"""Shared application logging with one persistent directory per local date."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


class DailyFileHandler(logging.Handler):
    """Write records to ``<root>/YYYY-MM-DD/backend.log``.

    The stream changes automatically after local midnight, so a daemon can
    stay alive across days without mixing dates or requiring a restart.
    """

    def __init__(self, root: str | Path, encoding: str = "utf-8") -> None:
        super().__init__()
        self.root = Path(root).resolve()
        self.encoding = encoding
        self._day = ""
        self._stream = None

    @property
    def current_path(self) -> Path:
        day = datetime.now().astimezone().date().isoformat()
        return self.root / day / "backend.log"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            path = self.current_path
            day = path.parent.name
            if day != self._day or self._stream is None:
                if self._stream is not None:
                    self._stream.close()
                path.parent.mkdir(parents=True, exist_ok=True)
                self._stream = path.open("a", encoding=self.encoding)
                self._day = day
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        super().close()


def configure_logging(log_dir: str | Path = "logs") -> Path:
    """Configure console and daily application logs, returning today's path."""
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    daily = DailyFileHandler(log_dir)
    daily.setFormatter(formatter)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.addHandler(console)
    root.addHandler(daily)
    # Uvicorn normally owns non-propagating handlers. Route both server and
    # access records through the same daily application log instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(logging.INFO)
    return daily.current_path
