"""The Dagster graph must load and keep its shape. Runs against the fixture manifest."""

import importlib
import os

import pytest
from dagster import AssetKey


@pytest.fixture(scope="module")
def graph(pipeline):
    os.environ["OSS_PULSE_DATA_DIR"] = str(pipeline.data_dir)
    os.environ.setdefault("OSS_PULSE_OFFLINE", "1")
    module = importlib.import_module("oss_pulse.orchestration.definitions")
    return module.defs, module.defs.resolve_asset_graph()


def by_name(graph_view, name):
    return next(key for key in graph_view.get_all_asset_keys() if key.path[-1] == name)


def test_definitions_load(graph):
    defs, _ = graph
    assert defs.resolve_job_def("publish_job") is not None
    assert defs.resolve_job_def("ingest_hour_job") is not None


def test_bronze_is_hourly_partitioned(graph):
    _, view = graph
    node = view.get(AssetKey("bronze_events"))
    assert node.partitions_def is not None
    assert "2026-11-04-12:00" in node.partitions_def.get_partition_keys(
        dynamic_partitions_store=None
    )


def test_silver_reads_from_bronze(graph):
    _, view = graph
    parents = view.get(by_name(view, "stg_events")).parent_keys
    assert AssetKey("bronze_events") in parents


def test_gold_reads_from_enrichment(graph):
    _, view = graph
    assert AssetKey("repo_metadata") in view.get(by_name(view, "gold_repo_metrics")).parent_keys


def test_enrichment_reads_from_silver(graph):
    _, view = graph
    parents = view.get(AssetKey("repo_metadata")).parent_keys
    assert by_name(view, "int_enrichment_candidates") in parents


def test_dashboard_extracts_follow_the_export(graph):
    _, view = graph
    assert by_name(view, "firstpr_export") in view.get(AssetKey("dashboard_extracts")).parent_keys


def test_every_dependency_is_a_real_asset(graph):
    # A bare string dependency on a dbt model silently creates an unconnected stub asset.
    _, view = graph
    stubs = [
        key.to_user_string() for key in view.get_all_asset_keys() if not view.get(key).is_executable
    ]
    assert stubs == []


def test_checks_target_real_assets(graph):
    _, view = graph
    keys = set(view.get_all_asset_keys())
    assert all(check.asset_key in keys for check in view.asset_check_keys)
    assert all(view.get(check.asset_key).is_executable for check in view.asset_check_keys)


def test_quality_checks_are_registered(graph):
    _, view = graph
    names = {key.name for key in view.asset_check_keys}
    assert {
        "partition_gaps_within_limit",
        "reject_rate_within_limit",
        "scores_in_range",
        "firstpr_contract",
        "extracts_under_size_limit",
    } <= names


def test_schedules_are_defined(graph):
    defs, _ = graph
    assert len(list(defs.schedules)) == 2
