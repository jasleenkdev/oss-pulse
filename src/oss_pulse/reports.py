"""Run records and the generated data quality report."""

from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import duckdb

from oss_pulse.config import DBT_DIR, REPO_ROOT, REPORTS_DIR, Settings
from oss_pulse.extracts import is_denied, rows_as_dicts
from oss_pulse.window import Window

RUN_SUMMARY = REPORTS_DIR / "run_summary.json"
TEST_SUMMARY = REPORTS_DIR / "test_summary.json"
QUALITY_REPORT = REPO_ROOT / "docs" / "data_quality.md"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


def record_ingest_run(seconds: float, workers: int, window: Window) -> None:
    summary = load_json(RUN_SUMMARY)
    summary.update(
        {
            "ingest_seconds": seconds,
            "ingest_workers": workers,
            "window_start": window.start.isoformat(),
            "window_end_inclusive": window.end.isoformat(),
        }
    )
    save_json(RUN_SUMMARY, summary)


def record_step_seconds(step: str, seconds: float) -> None:
    summary = load_json(RUN_SUMMARY)
    summary[f"{step}_seconds"] = round(seconds, 1)
    save_json(RUN_SUMMARY, summary)


def dbt_test_counts(run_results: Path | None = None) -> dict:
    """Pass, warn and fail counts from the last dbt invocation."""
    path = run_results or DBT_DIR / "target" / "run_results.json"
    results = load_json(path).get("results", [])
    tests = [result for result in results if result["unique_id"].startswith("test.")]
    counts = {"total": len(tests), "pass": 0, "warn": 0, "fail": 0, "error": 0}
    for test in tests:
        status = test["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def record_dbt_tests(run_results: Path | None = None) -> None:
    summary = load_json(TEST_SUMMARY)
    summary["dbt"] = dbt_test_counts(run_results)
    save_json(TEST_SUMMARY, summary)


def prune_old_partitions(settings: Settings, keep_days: int) -> int:
    """Delete partition directories outside the retention window. Returns days removed."""
    days: set[str] = set()
    for root in (settings.bronze_dir, settings.audit_dir, settings.rejects_dir):
        if root.exists():
            days.update(path.name for path in root.glob("date=*"))
    ordered = sorted(days)
    if not ordered:
        return 0
    newest = date.fromisoformat(ordered[-1].removeprefix("date="))
    cutoff = newest - timedelta(days=keep_days - 1)
    removed = 0
    for day in ordered:
        if date.fromisoformat(day.removeprefix("date=")) >= cutoff:
            continue
        for root in (settings.bronze_dir, settings.audit_dir, settings.rejects_dir):
            target = root / day
            if target.exists():
                shutil.rmtree(target)
        removed += 1
    return removed


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    header = "| " + " | ".join(title for _, title in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_format(row[key]) for key, _ in columns) + " |" for row in rows
    ]
    return "\n".join([header, divider, *body])


def _format(value) -> str:
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def write_data_quality_report(settings: Settings, target: Path = QUALITY_REPORT) -> None:
    gold = settings.gold_dir
    connection = duckdb.connect()

    def table(name: str) -> str:
        return f"read_parquet('{gold / name}.parquet')"

    summary = rows_as_dicts(connection, f"select * from {table('gold_pipeline_summary')}")[0]
    rejects = rows_as_dicts(
        connection,
        f"""
        select reason, count(*) as rows
        from read_parquet('{settings.rejects_dir}/**/rejects.parquet')
        group by reason
        order by rows desc, reason
        """,
    )
    daily = rows_as_dicts(
        connection,
        f"""
        select
            cast(partition_date as varchar) as day,
            count(*) as partitions,
            count(*) filter (where status <> 'ok') as gaps,
            cast(sum(rows_read) as bigint) as rows_read,
            cast(sum(rows_kept) as bigint) as rows_kept,
            cast(sum(rows_rejected) as bigint) as rows_rejected,
            cast(sum(rows_duplicate) as bigint) as rows_duplicate
        from {table('gold_partition_health')}
        group by partition_date
        order by partition_date
        """,
    )
    missing = rows_as_dicts(
        connection,
        f"""
        select cast(partition_date as varchar) as day, partition_hour as hour, status
        from {table('gold_partition_health')}
        where status <> 'ok'
        order by 1, 2
        """,
    )
    bots = rows_as_dicts(
        connection,
        f"""
        select name, total_events, bot_events, bot_share
        from {table('gold_bot_traffic')}
        where breakdown in ('by_type', 'overall')
        order by total_events desc
        """,
    )
    accounts = [
        row
        for row in rows_as_dicts(
            connection,
            f"""
            select name, total_events
            from {table('gold_bot_traffic')}
            where breakdown = 'by_account'
            order by total_events desc, name
            limit 15
            """,
        )
        if not is_denied(row["name"])
    ][:10]
    tests = load_json(TEST_SUMMARY)
    validation = load_json(REPORTS_DIR / "fallback_validation.json")

    missing_text = _table(missing, [("day", "Day"), ("hour", "Hour"), ("status", "Status")])
    lines = [
        "# Data quality",
        "",
        "Generated by `oss-pulse report` from the gold tables. Do not edit by hand.",
        "",
        f"Window: {summary['window_start']:%Y-%m-%d} to "
        f"{summary['window_end']:%Y-%m-%d} (end exclusive).",
        "",
        "## Totals",
        "",
        _table(
            [
                {"metric": name, "value": summary[key]}
                for name, key in [
                    ("Hourly partitions expected", "partitions_total"),
                    ("Partitions ingested", "partitions_ok"),
                    ("Partitions missing upstream", "partitions_missing"),
                    ("Partitions corrupt", "partitions_corrupt"),
                    ("Lines read", "rows_read"),
                    ("Lines kept", "rows_kept"),
                    ("Lines filtered by event type", "rows_filtered"),
                    ("Lines rejected", "rows_rejected"),
                    ("Duplicates removed within a partition", "rows_duplicate_within_partition"),
                    ("Duplicates removed across partitions", "rows_duplicate_across_partitions"),
                    ("Events outside their partition hour", "rows_out_of_hour"),
                    ("Rows with a corrected timestamp", "timestamp_anomalies"),
                    ("Estimated event capture rate", "estimated_capture_rate"),
                    ("Bot share of events", "bot_share"),
                ]
            ],
            [("metric", "Metric"), ("value", "Value")],
        ),
        "",
        "## Rejects by reason",
        "",
        _table(rejects, [("reason", "Reason"), ("rows", "Rows")]) if rejects else "None.",
        "",
        "## By day",
        "",
        _table(
            daily,
            [
                ("day", "Day"),
                ("partitions", "Partitions"),
                ("gaps", "Gaps"),
                ("rows_read", "Read"),
                ("rows_kept", "Kept"),
                ("rows_rejected", "Rejected"),
                ("rows_duplicate", "Duplicates"),
            ],
        ),
        "",
        "## Missing or corrupt partitions",
        "",
        missing_text if missing else "None.",
        "",
        "## Bot traffic",
        "",
        _table(
            bots,
            [
                ("name", "Event type"),
                ("total_events", "Events"),
                ("bot_events", "Bot events"),
                ("bot_share", "Bot share"),
            ],
        ),
        "",
        "Busiest automation accounts:",
        "",
        _table(accounts, [("name", "Account"), ("total_events", "Events")]),
        "",
        "## Fallback validation",
        "",
    ]
    if validation:
        inference = validation["maintainer_inference"]
        outcomes = validation["external_pr_true_outcomes"]
        lines += [
            "Feed-only rules scored against REST ground truth. Details are in "
            "`reports/fallback_validation.json`.",
            "",
            f"- Maintainer inference precision: {inference['precision_of_inferred']:.1%} of "
            f"{inference['true_positive'] + inference['false_positive']} comments.",
            f"- Maintainers among people not inferred: "
            f"{inference['maintainer_share_among_not_inferred']:.1%} of "
            f"{inference['false_negative'] + inference['true_negative']} comments.",
            f"- True merge rate of resolved external PRs: "
            f"{outcomes['true_merge_rate_of_resolved']:.1%} of "
            f"{outcomes.get('merged', 0) + outcomes.get('closed_unmerged', 0)} PRs. "
            f"The event-based estimate is shown on the dashboard.",
            "",
        ]
    else:
        lines += ["Not run. It needs `GITHUB_TOKEN`.", ""]
    lines += ["## Test results", ""]
    if tests:
        dbt = tests.get("dbt", {})
        pytest_counts = tests.get("pytest", {})
        lines += [
            f"- dbt tests: {dbt.get('pass', 0)} passed of {dbt.get('total', 0)}, "
            f"{dbt.get('fail', 0) + dbt.get('error', 0)} failed.",
            f"- pytest: {pytest_counts.get('passed', 0)} passed, "
            f"{pytest_counts.get('failed', 0)} failed.",
            "",
        ]
    else:
        lines += ["Not recorded yet.", ""]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines))
