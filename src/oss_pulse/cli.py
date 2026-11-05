"""Command line entry point: `python -m oss_pulse.cli backfill --days 7`."""

from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date

from dotenv import load_dotenv

from oss_pulse.config import GHARCHIVE_BASE_URL, Settings
from oss_pulse.ingest import ingest_hour
from oss_pulse.window import resolve_window

log = logging.getLogger("oss_pulse")


def cmd_backfill(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    settings.ensure()
    end = date.fromisoformat(args.end_date) if args.end_date else None
    window = resolve_window(args.days, end)
    log.info("backfill window: %s", window)
    started = time.monotonic()

    def run(hour):
        return ingest_hour(
            settings,
            hour,
            base_url=args.base_url,
            retain_raw=args.retain_raw,
            skip_existing=not args.force,
        )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        audits = list(pool.map(run, window.hours()))

    summary = {
        "hours": len(audits),
        "ok": sum(a.status == "ok" for a in audits),
        "missing": sum(a.status == "missing" for a in audits),
        "corrupt": sum(a.status == "corrupt" for a in audits),
        "rows_read": sum(a.rows_read for a in audits),
        "rows_kept": sum(a.rows_kept for a in audits),
        "rows_rejected": sum(a.rows_rejected for a in audits),
        "seconds": round(time.monotonic() - started, 1),
    }
    log.info("backfill summary: %s", json.dumps(summary))
    if args.verbose_audit:
        for audit in audits:
            print(json.dumps(asdict(audit)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oss-pulse")
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser("backfill", help="Ingest hourly partitions into bronze")
    backfill.add_argument("--days", type=int, default=7, help="Complete days to ingest")
    backfill.add_argument("--end-date", help="Last day to ingest, YYYY-MM-DD (default: auto)")
    backfill.add_argument("--workers", type=int, default=4)
    backfill.add_argument("--force", action="store_true", help="Re-ingest existing partitions")
    backfill.add_argument("--retain-raw", action="store_true", help="Keep the .json.gz files")
    backfill.add_argument("--base-url", default=GHARCHIVE_BASE_URL)
    backfill.add_argument("--verbose-audit", action="store_true")
    backfill.set_defaults(func=cmd_backfill)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
