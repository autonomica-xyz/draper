#!/usr/bin/env python3
"""Draper Marketing Pipeline background worker."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def get_data_dir() -> Path:
    """Resolve data directory (mirrors dashboard / ProjectManager).

    Order: ``DRAPER_DATA_DIR`` env if set, else ``<repo>/data``.
    Creates the directory if needed.
    """
    env_dir = os.environ.get("DRAPER_DATA_DIR")
    data_dir = Path(env_dir) if env_dir else Path(__file__).parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="draper-worker",
        description="Draper Marketing Pipeline background worker — drains the job queue.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Path to data directory (default: DRAPER_DATA_DIR or <repo>/data).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds to sleep between idle polls (default: 2.0).",
    )
    parser.add_argument(
        "--stop-after-idle",
        type=int,
        default=None,
        help="Debug: stop after N consecutive idle cycles.",
    )
    parser.add_argument(
        "--kinds",
        type=str,
        default=None,
        help="Comma-separated job-kind allowlist forwarded to run_forever(kinds=...).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single run_once() and exit (cron-mode).",
    )
    args = parser.parse_args(argv)

    data_dir = args.data_dir or str(get_data_dir())

    from dashboard.app_container import AppContainer
    from services.observability import configure_logging
    from services.worker import IdleCycles, Worker

    configure_logging()

    container = AppContainer(data_dir=data_dir)
    worker = Worker(container, poll_interval=args.poll_interval)

    kinds = [k.strip() for k in args.kinds.split(",")] if args.kinds else None

    if args.once:
        result = worker.run_once(kinds=kinds)
        print(json.dumps(result or {"idle": True}, default=str))
        return 0

    stop_after = IdleCycles(args.stop_after_idle) if args.stop_after_idle else None
    try:
        worker.run_forever(kinds=kinds, stop_after=stop_after)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
