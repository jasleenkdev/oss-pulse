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

from oss_pulse.config import (
    CONTRACTS_DIR,
    GHARCHIVE_BASE_URL,
    Settings,
)
from oss_pulse.contract import load_contract, validate
from oss_pulse.enrich import enrich
from oss_pulse.extracts import build_extracts
from oss_pulse.ingest import ensure_placeholders, ingest_hour
from oss_pulse.reports import prune_old_partitions, record_ingest_run, write_data_quality_report
from oss_pulse.window import resolve_window

log = logging.getLogger("oss_pulse")


def cmd_backfill(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    settings.ensure()
    ensure_placeholders(settings)
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
            max_attempts=args.max_attempts,
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
    if args.record:
        record_ingest_run(summary["seconds"], args.workers, window)
    if args.verbose_audit:
        for audit in audits:
            print(json.dumps(asdict(audit)))
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    print(enrich(settings, args.top_n))
    return 0


def cmd_check_contract(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    contract = load_contract(CONTRACTS_DIR / "firstpr_export_v1.yml")
    violations = validate(settings.gold_dir / "firstpr_export.parquet", contract)
    for violation in violations:
        print(f"contract violation: {violation}")
    print(f"contract check: {len(violations)} violations")
    return 1 if violations else 0


def cmd_extracts(args: argparse.Namespace) -> int:
    build_extracts(Settings.from_env())
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    write_data_quality_report(Settings.from_env())
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    removed = prune_old_partitions(Settings.from_env(), args.keep_days)
    log.info("pruned %d day directories", removed)
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
    backfill.add_argument("--max-attempts", type=int, default=4)
    backfill.add_argument("--verbose-audit", action="store_true")
    backfill.add_argument("--record", action="store_true", help="Save timing to reports/")
    backfill.set_defaults(func=cmd_backfill)

    enrich_parser = sub.add_parser("enrich", help="Fetch repo metadata from the REST API")
    enrich_parser.add_argument("--top-n", type=int, default=500)
    enrich_parser.set_defaults(func=cmd_enrich)

    sub.add_parser("check-contract", help="Validate the FirstPR export").set_defaults(
        func=cmd_check_contract
    )
    sub.add_parser("extracts", help="Write the dashboard extracts").set_defaults(func=cmd_extracts)
    sub.add_parser("report", help="Write docs/data_quality.md").set_defaults(func=cmd_report)

    prune = sub.add_parser("prune", help="Delete partitions older than the retention window")
    prune.add_argument("--keep-days", type=int, default=7)
    prune.set_defaults(func=cmd_prune)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
