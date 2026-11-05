"""Dagster assets, checks, jobs and schedules.

Flow: hourly bronze partitions -> dbt staging and silver -> REST enrichment ->
dbt gold -> FirstPR export check -> dashboard extracts and the quality report.

dbt tests surface as asset checks through dagster-dbt. The checks below add what dbt
cannot see: partition gaps, reject rates, the data contract and extract size.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    AssetSpec,
    Definitions,
    HourlyPartitionsDefinition,
    MaterializeResult,
    MetadataValue,
    ScheduleDefinition,
    asset,
    asset_check,
    build_schedule_from_partitioned_job,
    define_asset_job,
    multi_asset,
)
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets
from dotenv import load_dotenv

from oss_pulse.config import CONTRACTS_DIR, DBT_DIR, EXTRACTS_DIR, Settings
from oss_pulse.contract import load_contract, validate
from oss_pulse.enrich import enrich
from oss_pulse.extracts import build_extracts
from oss_pulse.ingest import ensure_placeholders, ingest_hour
from oss_pulse.reports import write_data_quality_report

load_dotenv()
settings = Settings.from_env()
os.environ.setdefault("OSS_PULSE_DATA_DIR", str(settings.data_dir))
os.environ.setdefault("DBT_PROFILES_DIR", str(DBT_DIR))

MAX_PARTITION_GAP_SHARE = 0.05
MAX_REJECT_SHARE = 0.01
MAX_EXTRACT_BYTES = 20_000_000

hourly_partitions = HourlyPartitionsDefinition(start_date="2026-10-01-00:00", timezone="UTC")

dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
if not dbt_project.manifest_path.exists():
    subprocess.run(
        [str(Path(sys.executable).parent / "dbt"), "parse", "--quiet"],
        cwd=DBT_DIR,
        check=True,
        env={**os.environ},
    )


def gold_key(name: str) -> AssetKey:
    """dagster-dbt prefixes keys with the schema. A bare name would create a separate asset."""
    return AssetKey(["gold", name])


class Translator(DagsterDbtTranslator):
    """Point dbt sources at the Dagster assets that write them."""

    def get_asset_key(self, dbt_resource_props) -> AssetKey:
        if dbt_resource_props["resource_type"] == "source":
            if dbt_resource_props["source_name"] == "bronze":
                return AssetKey(f"bronze_{dbt_resource_props['name']}")
            return AssetKey(dbt_resource_props["name"])
        return super().get_asset_key(dbt_resource_props)

    def get_group_name(self, dbt_resource_props) -> str | None:
        tags = dbt_resource_props.get("tags", [])
        if "gold" in tags:
            return "gold"
        if dbt_resource_props["resource_type"] == "seed":
            return "seeds"
        return "silver"


@multi_asset(
    specs=[
        AssetSpec(
            "bronze_events",
            group_name="bronze",
            kinds={"python", "parquet"},
            description="One GH Archive hour, filtered and de-duplicated.",
        ),
        AssetSpec(
            "bronze_audit",
            group_name="bronze",
            kinds={"parquet"},
            description="Row counts, bytes and duration for the hour, including gaps.",
        ),
        AssetSpec(
            "bronze_rejects",
            group_name="bronze",
            kinds={"parquet"},
            description="Lines quarantined from the hour.",
        ),
    ],
    partitions_def=hourly_partitions,
    name="ingest_hour",
)
def ingest_hour_asset(context: AssetExecutionContext) -> Iterator[MaterializeResult]:
    settings.ensure()
    ensure_placeholders(settings)
    hour = context.partition_time_window.start.replace(tzinfo=None)
    audit = ingest_hour(settings, hour)
    if audit.status != "ok":
        # A gap is recorded, not raised. The partition-gap check decides if it matters.
        context.log.warning("partition %s is %s upstream", hour, audit.status)
    yield MaterializeResult(
        asset_key="bronze_events",
        metadata={"status": audit.status, "rows_kept": audit.rows_kept},
    )
    yield MaterializeResult(
        asset_key="bronze_audit",
        metadata={
            "rows_read": audit.rows_read,
            "rows_filtered": audit.rows_filtered,
            "rows_duplicate": audit.rows_duplicate,
            "bytes_compressed": audit.bytes_compressed,
            "duration_s": audit.duration_s,
        },
    )
    yield MaterializeResult(
        asset_key="bronze_rejects", metadata={"rows_rejected": audit.rows_rejected}
    )


@dbt_assets(
    manifest=dbt_project.manifest_path,
    select="resource_type:seed tag:staging tag:silver",
    dagster_dbt_translator=Translator(),
    name="dbt_silver",
)
def dbt_silver(context: AssetExecutionContext, dbt: DbtCliResource) -> Iterator:
    yield from dbt.cli(["build"], context=context).stream()


@asset(
    deps=[AssetKey(["staging", "int_enrichment_candidates"])],
    group_name="silver",
    kinds={"python", "parquet"},
    description="Language, topics, license and archived status from the GitHub REST API.",
)
def repo_metadata(context: AssetExecutionContext) -> MaterializeResult:
    result = enrich(settings)
    if result.skipped_reason:
        context.log.info("enrichment skipped: %s", result.skipped_reason)
    return MaterializeResult(
        metadata={
            "requested": result.requested,
            "fetched": result.fetched,
            "cache_hits": result.cache_hits,
            "not_found": result.not_found,
            "skipped_reason": result.skipped_reason or "",
        }
    )


@dbt_assets(
    manifest=dbt_project.manifest_path,
    select="tag:gold",
    dagster_dbt_translator=Translator(),
    name="dbt_gold",
)
def dbt_gold(context: AssetExecutionContext, dbt: DbtCliResource) -> Iterator:
    yield from dbt.cli(["build"], context=context).stream()


@asset(
    deps=[
        gold_key("firstpr_export"),
        gold_key("gold_repo_scores"),
        gold_key("gold_pipeline_summary"),
        gold_key("gold_network_summary"),
    ],
    group_name="publish",
    kinds={"json"},
    description="Compact committed extracts that the static dashboard builds from.",
)
def dashboard_extracts() -> MaterializeResult:
    meta = build_extracts(settings)
    total = sum(path.stat().st_size for path in EXTRACTS_DIR.glob("*.json"))
    return MaterializeResult(
        metadata={
            "total_bytes": total,
            "repos_scored": meta["pipeline"]["repos_scored"],
        }
    )


@asset(
    deps=[dashboard_extracts],
    group_name="publish",
    kinds={"markdown"},
    description="docs/data_quality.md, generated from the gold tables.",
)
def data_quality_report() -> None:
    write_data_quality_report(settings)


@asset_check(asset=gold_key("gold_partition_health"), blocking=False)
def partition_gaps_within_limit() -> AssetCheckResult:
    source = f"read_parquet('{settings.gold_dir}/gold_partition_health.parquet')"
    total, gaps = duckdb.sql(
        f"select count(*), count(*) filter (where status <> 'ok') from {source}"
    ).fetchall()[0]
    share = gaps / total if total else 1.0
    return AssetCheckResult(
        passed=share <= MAX_PARTITION_GAP_SHARE,
        severity=AssetCheckSeverity.ERROR,
        metadata={"partitions": total, "gaps": gaps, "gap_share": share},
    )


@asset_check(asset=gold_key("gold_pipeline_summary"), blocking=True)
def reject_rate_within_limit() -> AssetCheckResult:
    source = f"read_parquet('{settings.gold_dir}/gold_pipeline_summary.parquet')"
    read, rejected = duckdb.sql(f"select rows_read, rows_rejected from {source}").fetchall()[0]
    share = rejected / read if read else 1.0
    return AssetCheckResult(
        passed=share <= MAX_REJECT_SHARE,
        severity=AssetCheckSeverity.ERROR,
        metadata={"rows_read": read, "rows_rejected": rejected, "reject_share": share},
    )


@asset_check(asset=gold_key("gold_repo_scores"), blocking=True)
def scores_in_range() -> AssetCheckResult:
    source = f"read_parquet('{settings.gold_dir}/gold_repo_scores.parquet')"
    rows, invalid = duckdb.sql(
        f"select count(*), count(*) filter (where score < 0 or score > 100) from {source}"
    ).fetchall()[0]
    return AssetCheckResult(
        passed=rows > 0 and invalid == 0,
        severity=AssetCheckSeverity.ERROR,
        metadata={"repos_scored": rows, "out_of_range": invalid},
    )


@asset_check(asset=gold_key("firstpr_export"), blocking=True)
def firstpr_contract() -> AssetCheckResult:
    contract = load_contract(CONTRACTS_DIR / "firstpr_export_v1.yml")
    violations = validate(settings.gold_dir / "firstpr_export.parquet", contract)
    return AssetCheckResult(
        passed=not violations,
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "contract_version": contract["version"],
            "violations": MetadataValue.json(violations),
        },
    )


@asset_check(asset=dashboard_extracts, blocking=True)
def extracts_under_size_limit() -> AssetCheckResult:
    total = sum(path.stat().st_size for path in EXTRACTS_DIR.glob("*.json"))
    return AssetCheckResult(
        passed=total <= MAX_EXTRACT_BYTES,
        severity=AssetCheckSeverity.ERROR,
        metadata={"total_bytes": total, "limit_bytes": MAX_EXTRACT_BYTES},
    )


@asset_check(asset=gold_key("gold_pipeline_summary"), blocking=False)
def data_is_fresh() -> AssetCheckResult:
    source = f"read_parquet('{settings.gold_dir}/gold_pipeline_summary.parquet')"
    latest = duckdb.sql(f"select latest_event_at from {source}").fetchall()[0][0]
    age_hours = (datetime.now(UTC).replace(tzinfo=None) - latest).total_seconds() / 3600
    return AssetCheckResult(
        passed=age_hours <= 72,
        severity=AssetCheckSeverity.WARN,
        metadata={"latest_event_at": str(latest), "age_hours": age_hours},
    )


ingest_job = define_asset_job(
    "ingest_hour_job",
    selection=AssetSelection.assets(ingest_hour_asset),
)

publish_job = define_asset_job(
    "publish_job",
    selection=AssetSelection.all() - AssetSelection.assets(ingest_hour_asset),
    description="Rebuild silver and gold from bronze, then publish the export and extracts.",
)

hourly_ingest_schedule = build_schedule_from_partitioned_job(ingest_job, minute_of_hour=20)

daily_publish_schedule = ScheduleDefinition(
    job=publish_job,
    cron_schedule="30 3 * * *",
    execution_timezone="UTC",
)

defs = Definitions(
    assets=[
        ingest_hour_asset,
        dbt_silver,
        repo_metadata,
        dbt_gold,
        dashboard_extracts,
        data_quality_report,
    ],
    asset_checks=[
        partition_gaps_within_limit,
        reject_rate_within_limit,
        scores_in_range,
        firstpr_contract,
        extracts_under_size_limit,
        data_is_fresh,
    ],
    jobs=[ingest_job, publish_job],
    schedules=[hourly_ingest_schedule, daily_publish_schedule],
    resources={
        "dbt": DbtCliResource(
            project_dir=dbt_project, dbt_executable=str(Path(sys.executable).parent / "dbt")
        )
    },
)
