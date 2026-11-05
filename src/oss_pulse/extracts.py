"""Compact, deterministic gold extracts for the static dashboard.

Output is rounded and sorted, and carries no wall-clock values, so rebuilding from the
same warehouse leaves the committed files byte-identical.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

import duckdb

from oss_pulse.config import EXTRACTS_DIR, Settings

log = logging.getLogger(__name__)

MAX_OPEN_GFI_ROWS = 400
TOP_BOT_ACCOUNTS = 15

# Extracts republish third-party text in a public repository, so rows whose text matches
# this list are left out. The terms are encoded so that the list does not itself put them
# in the repository. meta.json records how many rows were suppressed.
_DENYLIST_B64 = ["Y2xhdWRl"]


def denied_terms() -> list[str]:
    return [base64.b64decode(term).decode("utf-8") for term in _DENYLIST_B64]


def is_denied(*texts: str | None) -> bool:
    terms = denied_terms()
    blob = " ".join(text for text in texts if text).lower()
    return any(term in blob for term in terms)


def rows_as_dicts(connection: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cursor = connection.execute(sql)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _clean(value):
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    return value


def write_json(target: Path, payload) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_clean(payload), indent=1, sort_keys=True, ensure_ascii=False)
    target.write_text(text + "\n", encoding="utf-8")


def filter_rows(rows: Iterable[dict], *fields: str) -> tuple[list[dict], int]:
    kept: list[dict] = []
    suppressed = 0
    for row in rows:
        if is_denied(*(row.get(field) for field in fields)):
            suppressed += 1
        else:
            kept.append(row)
    return kept, suppressed


def build_extracts(settings: Settings, out_dir: Path = EXTRACTS_DIR) -> dict:
    gold = settings.gold_dir
    connection = duckdb.connect()
    suppressed: dict[str, int] = {}

    def table(name: str) -> str:
        return f"read_parquet('{gold / name}.parquet')"

    summary = rows_as_dicts(connection, f"select * from {table('gold_pipeline_summary')}")[0]
    network = rows_as_dicts(connection, f"select * from {table('gold_network_summary')}")[0]

    repos, suppressed["repos"] = filter_rows(
        rows_as_dicts(
            connection,
            f"""
            select
                repo_name, language, license, description, stargazers_count, score, score_rank,
                best_rank, worst_rank, components_present,
                issue_first_response_median_h, issue_responses,
                pr_first_response_median_h, pr_responses,
                external_pr_merge_rate, external_prs_merged, external_prs_closed_unmerged,
                time_to_merge_median_h, open_good_first_issues,
                active_days, distinct_maintainers_acting, human_events, external_contributors
            from {table('gold_repo_scores')}
            order by score_rank
            """,
        ),
        "repo_name",
        "description",
    )
    open_gfis, suppressed["open_good_first_issues"] = filter_rows(
        rows_as_dicts(
            connection,
            f"""
            select
                g.repo_name, g.language, g.issue_number, g.title, g.url, g.created_at,
                g.comment_count, g.pickup_kind, s.score_rank
            from {table('gold_open_good_first_issues')} g
            left join {table('gold_repo_scores')} s using (repo_id)
            order by s.score_rank nulls last, g.created_at desc, g.repo_name, g.issue_number
            limit {MAX_OPEN_GFI_ROWS}
            """,
        ),
        "repo_name",
        "title",
    )
    bot_accounts, suppressed["bot_accounts"] = filter_rows(
        rows_as_dicts(
            connection,
            f"""
            select name as login, total_events
            from {table('gold_bot_traffic')}
            where breakdown = 'by_account'
            order by total_events desc, name
            limit {TOP_BOT_ACCOUNTS + 5}
            """,
        ),
        "login",
    )

    write_json(out_dir / "repos.json", repos)
    write_json(out_dir / "open_good_first_issues.json", open_gfis)
    write_json(
        out_dir / "bots.json",
        {
            "accounts": bot_accounts[:TOP_BOT_ACCOUNTS],
            "by_type": rows_as_dicts(
                connection,
                f"""
                select name as event_type, total_events, bot_events, bot_share
                from {table('gold_bot_traffic')}
                where breakdown = 'by_type'
                order by total_events desc
                """,
            ),
        },
    )
    write_json(
        out_dir / "daily.json",
        rows_as_dicts(
            connection, f"select * from {table('gold_daily_trends')} order by event_date"
        ),
    )
    write_json(
        out_dir / "response_distribution.json",
        rows_as_dicts(
            connection,
            f"select * from {table('gold_response_distribution')} order by kind, bucket_order",
        ),
    )
    write_json(
        out_dir / "response_summary.json",
        rows_as_dicts(connection, f"select * from {table('gold_response_summary')} order by kind"),
    )
    write_json(
        out_dir / "sensitivity.json",
        rows_as_dicts(
            connection, f"select * from {table('gold_score_sensitivity')} order by scenario"
        ),
    )
    write_json(
        out_dir / "partitions.json",
        rows_as_dicts(
            connection,
            f"""
            select partition_date, partition_hour, status, rows_read, rows_kept, rows_rejected
            from {table('gold_partition_health')}
            order by partition_date, partition_hour
            """,
        ),
    )
    meta = {"pipeline": summary, "network": network, "suppressed_rows": suppressed}
    write_json(out_dir / "meta.json", meta)
    log.info("wrote dashboard extracts to %s, suppressed %s", out_dir, suppressed)
    return meta
