"""Recompute every README number from pipeline outputs and fail on any mismatch.

Numbers in the README are tagged with the metric they show:

    <!--m:rows_read-->770,397<!--/m-->

The tags are invisible once rendered. In the sections listed in CHECKED_SECTIONS, any digit
outside a tag also fails, so a number cannot be added without a traceable source.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
REPORTS = ROOT / "reports"

TAG = re.compile(r"<!--m:(?P<name>[a-z0-9_]+)-->(?P<text>.*?)<!--/m-->")
CHECKED_SECTIONS = ("Scale", "Findings", "Data quality summary")
# Digits that are names rather than measurements.
ALLOWED_UNTAGGED = re.compile(r"\bp90\b|^\s*\d+\.\s")


def rows(connection, sql: str) -> list[dict]:
    cursor = connection.execute(sql)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def load_json(name: str) -> dict:
    return json.loads((REPORTS / name).read_text())


def compute_metrics(data_dir: Path) -> dict:
    """Every metric the README may cite, read from gold tables and reports."""
    gold = data_dir / "gold"
    connection = duckdb.connect()

    def table(name: str) -> str:
        return f"read_parquet('{gold / name}.parquet')"

    p = rows(connection, f"select * from {table('gold_pipeline_summary')}")[0]
    n = rows(connection, f"select * from {table('gold_network_summary')}")[0]
    responses = {
        row["kind"]: row
        for row in rows(connection, f"select * from {table('gold_response_summary')}")
    }
    sensitivity = {
        row["scenario"]: row
        for row in rows(connection, f"select * from {table('gold_score_sensitivity')}")
    }
    bots = {
        row["name"]: row
        for row in rows(
            connection,
            f"select * from {table('gold_bot_traffic')} where breakdown = 'by_type'",
        )
    }
    ranks = rows(
        connection,
        f"""select score_rank, repo_name, score, worst_rank - best_rank as spread
            from {table("gold_repo_scores")} order by score_rank""",
    )
    export = rows(
        connection,
        f"""select count(*) as repos, sum(len(open_good_first_issues)) as issues
            from {table("firstpr_export")}""",
    )[0]
    validation = load_json("fallback_validation.json")
    outcomes = validation["external_pr_true_outcomes"]
    inference = validation["maintainer_inference"]
    merged_actor = validation["merged_event_actor"]
    run = load_json("run_summary.json")
    tests = load_json("test_summary.json")
    issue, pr = responses["issue"], responses["pr"]
    spreads = sorted(row["spread"] for row in ranks)

    metrics = {
        "window_start": f"{p['window_start']:%Y-%m-%d}",
        "window_last_day": run["window_end_inclusive"],
        "window_days": p["window_days"],
        "partitions_total": p["partitions_total"],
        "partitions_ok": p["partitions_ok"],
        "partitions_missing": p["partitions_missing"],
        "partitions_corrupt": p["partitions_corrupt"],
        "rows_read": p["rows_read"],
        "rows_kept": p["rows_kept"],
        "rows_filtered": p["rows_filtered"],
        "rows_rejected": p["rows_rejected"],
        "rows_duplicate": p["rows_duplicate_within_partition"]
        + p["rows_duplicate_across_partitions"],
        "rows_out_of_hour": p["rows_out_of_hour"],
        "gb_compressed": p["bytes_compressed"] / 1e9,
        "gb_uncompressed": p["bytes_uncompressed"] / 1e9,
        "ingest_seconds": run["ingest_seconds"],
        "ingest_workers": run["ingest_workers"],
        "build_seconds": run["build_seconds"],
        "repos_seen": p["repos_seen"],
        "repos_human": p["repos_with_human_activity"],
        "repos_gate": p["repos_meeting_min_activity"],
        "repos_scored": p["repos_scored"],
        "repos_enriched": p["repos_enriched"],
        "capture_rate": p["estimated_capture_rate"],
        "timestamp_anomalies": p["timestamp_anomalies"],
        "bot_share": p["bot_share"],
        "bot_events": p["bot_events"],
        "bot_share_issue_comments": bots["IssueCommentEvent"]["bot_share"],
        "bot_share_review_comments": bots["PullRequestReviewCommentEvent"]["bot_share"],
        "bot_share_issues": bots["IssuesEvent"]["bot_share"],
        "issue_items": issue["items"],
        "issue_observed_share": issue["observed_response_share"],
        "issue_median_h": issue["median_h"],
        "issue_p90_h": issue["p90_h"],
        "issue_exact_items": issue["exact_items"],
        "issue_exact_median_h": issue["exact_median_h"],
        "pr_responses": pr["items_with_response"],
        "pr_median_h": pr["median_h"],
        "pr_p90_h": pr["p90_h"],
        "external_merge_rate": n["external_pr_merge_rate"],
        "external_resolved": n["external_prs_merged"] + n["external_prs_closed_unmerged"],
        "branch_merge_rate": n["branch_pr_merge_rate"],
        "first_time_merge_rate": n["first_time_pr_merge_rate"],
        "first_time_resolved": n["first_time_prs_merged"] + n["first_time_prs_closed_unmerged"],
        "true_merge_rate": outcomes["true_merge_rate_of_resolved"],
        "true_resolved": outcomes["merged"] + outcomes["closed_unmerged"],
        "true_still_open_share": outcomes["still_open_share"],
        "external_ttm_h": n["external_time_to_merge_median_h"],
        "external_ttm_samples": n["external_time_to_merge_samples"],
        "branch_ttm_min": n["branch_time_to_merge_median_h"] * 60,
        "branch_ttm_samples": n["branch_time_to_merge_samples"],
        "ttm_ratio": n["external_time_to_merge_median_h"] / n["branch_time_to_merge_median_h"],
        "gfi_seen": n["good_first_issues_seen"],
        "gfi_open": n["open_good_first_issues"],
        "gfi_repos": n["repos_with_good_first_issues"],
        "gfi_measurable": n["gfi_measurable"],
        "gfi_pickups": n["gfi_pickups"],
        "gfi_pickup_share": n["gfi_pickup_share"],
        "gfi_pickup_median_h": n["gfi_pickup_median_h"],
        "gfi_pickup_p90_h": n["gfi_pickup_p90_h"],
        "single_maintainer_share": n["scored_repos_single_maintainer_share"],
        "single_maintainer_repos": n["scored_repos_single_maintainer"],
        "rank_spread_median": spreads[len(spreads) // 2],
        "rank_spread_max": spreads[-1],
        "top_repo": ranks[0]["repo_name"],
        "top_score": ranks[0]["score"],
        "export_repos": export["repos"],
        "export_issues": export["issues"],
        "maintainer_precision": inference["precision_of_inferred"],
        "maintainer_checked": inference["true_positive"] + inference["false_positive"],
        "maintainer_missed_share": inference["maintainer_share_among_not_inferred"],
        "maintainer_owner_precision": inference["precision_by_first_matching_rule"][
            "owner_namespace"
        ]["precision"],
        "maintainer_push_precision": inference["precision_by_first_matching_rule"][
            "push_branch_pr"
        ]["precision"],
        "merged_actor_checked": merged_actor["actor_is_author_and_merger"]
        + merged_actor["actor_is_author_not_merger"],
        "merged_actor_not_merger": merged_actor["actor_is_author_not_merger"],
        "dbt_tests_passed": tests["dbt"]["pass"],
        "dbt_tests_total": tests["dbt"]["total"],
        "pytest_passed": tests["pytest"]["passed"],
    }
    for scenario, row in sensitivity.items():
        metrics[f"spearman_{scenario}"] = row["spearman_with_baseline"]
        metrics[f"top10_{scenario}"] = row["top10_overlap"]
    return metrics


def matches(text: str, value) -> bool:
    """Compare what the README shows with the value, at the precision the README shows."""
    if isinstance(value, str):
        return text == value
    shown = text.strip().replace(",", "")
    number = re.search(r"-?\d+(?:\.\d+)?", shown)
    if number is None:
        return False
    digits = number.group()
    decimals = len(digits.partition(".")[2])
    expected = float(value) * 100 if shown.endswith("%") else float(value)
    return round(expected, decimals) == float(digits)


def sections(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    for heading, body in zip(parts[1::2], parts[2::2], strict=True):
        found[heading.strip()] = body
    return found


def untagged_numbers(section: str) -> list[str]:
    """Lines that still contain a digit once tags, code and allowed names are removed."""
    problems = []
    for line in re.sub(r"```.*?```", "", section, flags=re.DOTALL).splitlines():
        stripped = TAG.sub("", line)
        stripped = re.sub(r"`[^`]*`", "", stripped)
        stripped = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", stripped)
        stripped = ALLOWED_UNTAGGED.sub("", stripped)
        if re.search(r"\d", stripped):
            problems.append(line.strip())
    return problems


def check(text: str, metrics: dict) -> list[str]:
    errors = []
    tags = list(TAG.finditer(text))
    for tag in tags:
        name, shown = tag.group("name"), tag.group("text")
        if name not in metrics:
            errors.append(f"unknown metric: {name}")
        elif not matches(shown, metrics[name]):
            errors.append(f"{name}: README shows {shown}, outputs say {metrics[name]}")
    parts = sections(text)
    for heading in CHECKED_SECTIONS:
        if heading not in parts:
            errors.append(f"missing section: {heading}")
            continue
        errors.extend(
            f"untagged number in {heading}: {line}" for line in untagged_numbers(parts[heading])
        )
    if not tags:
        errors.append("no tagged numbers found")
    return errors


def main() -> int:
    data_dir = Path(os.environ.get("OSS_PULSE_DATA_DIR") or ROOT / "data")
    if not (data_dir / "gold" / "gold_pipeline_summary.parquet").exists():
        print(f"no gold outputs in {data_dir}: run make backfill build first", file=sys.stderr)
        return 1
    text = README.read_text()
    errors = check(text, compute_metrics(data_dir))
    for error in errors:
        print(f"FAIL {error}")
    print(f"checked {len(TAG.findall(text))} tagged numbers: {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
