"""Start the fund daemon with dashboard API.

Usage::

    poetry run python -m hedge_fund.run_daemon hedge_fund/fund/example.yaml
    poetry run python -m hedge_fund.run_daemon hedge_fund/fund/example.yaml --interval daily --time 16:00
    poetry run python -m hedge_fund.run_daemon hedge_fund/fund/example.yaml --port 8080

This starts:
1. A background scheduler running fund cycles on a configurable interval
2. A FastAPI dashboard server at http://localhost:8000
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="python -m hedge_fund.run_daemon",
        description="Run the AI hedge fund in daemon mode with a dashboard API.",
    )
    parser.add_argument(
        "fund",
        help="path to a fund spec YAML, e.g. hedge_fund/fund/example.yaml",
    )
    parser.add_argument(
        "--interval",
        default="daily",
        choices=["daily", "hourly", "manual"],
        help="how often to run a fund cycle (default: daily)",
    )
    parser.add_argument(
        "--time",
        default="16:00",
        help="HH:MM to run daily cycles (default: 16:00)",
    )
    parser.add_argument(
        "--db",
        default="fund.db",
        help="SQLite database path (default: fund.db)",
    )
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=0.001,
        help="commission fee rate (default: 0.001 = 0.1%%)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="dashboard API port (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="dashboard API host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="daily log root directory (default: logs)",
    )
    args = parser.parse_args()

    from hedge_fund.logging_config import configure_logging
    log_path = configure_logging(args.log_dir)

    fund_path = str(Path(args.fund).resolve())
    if not os.path.exists(fund_path):
        print(f"Error: fund spec not found: {fund_path}")
        sys.exit(1)

    db_path = str(Path(args.db).resolve())

    os.environ["FUND_DB_PATH"] = db_path
    os.environ["FUND_SPEC_PATH"] = fund_path

    logger.info("Application log: %s", log_path)
    logger.info(
        "Startup configuration: fund=%s db=%s interval=%s host=%s port=%d",
        fund_path, db_path, args.interval, args.host, args.port,
    )

    from hedge_fund.scheduler import FundDaemon

    daemon = FundDaemon(
        fund_path=fund_path,
        db_path=db_path,
        interval=args.interval,
        time=args.time,
        fee_rate=args.fee_rate,
    )
    # Legacy combined launcher only; the standalone research API does not need
    # or register daemon-specific endpoints.

    if args.interval != "manual":
        daemon.start()

    logger.info(
        "Starting dashboard API at http://%s:%d", args.host, args.port,
    )
    logger.info("API docs: http://%s:%d/docs", args.host, args.port)

    try:
        uvicorn.run(
            "research_app.backend.main:app",
            host=args.host,
            port=args.port,
            log_level="info",
            log_config=None,
        )
    except KeyboardInterrupt:
        logger.info("shutting down...")
        daemon.stop()


if __name__ == "__main__":
    main()
