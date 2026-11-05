"""Asserts model behaviour end to end, on fixtures with known answers."""

import json
import re

import duckdb
import pytest


def scalar(query, sql):
    return query(sql)[0][0]


def maintainers(pipeline, repo_id):
    connection = duckdb.connect(str(pipeline.warehouse_path), read_only=True)
    rows = connection.execute(
        "select login from staging.int_maintainers where repo_id = ?", [repo_id]
    ).fetchall()
    connection.close()
    return {row[0] for row in rows}


WIDGETS, ENGINE, NOTES, OLDSTACK = 101, 102, 103, 104


def test_duplicate_event_ids_are_removed(query):
    total, distinct = query(
        "select count(*), count(distinct event_id) from 'silver/events.parquet'"
    )[0]
    assert total == distinct


def test_audit_conserves_every_line(query):
    assert scalar(
        query,
        """select count(*) from 'gold/gold_partition_health.parquet'
           where rows_read <> rows_kept + rows_filtered + rows_rejected + rows_duplicate""",
    ) == 0


def test_rejects_and_duplicates_are_counted(query):
    rejected, duplicates = query(
        """select rows_rejected, rows_duplicate_within_partition
           from 'gold/gold_pipeline_summary.parquet'"""
    )[0]
    assert rejected == 4
    assert duplicates == 1


def test_missing_hours_are_recorded(query):
    assert scalar(
        query, "select partitions_missing from 'gold/gold_pipeline_summary.parquet'"
    ) > 0


def test_bots_are_flagged_by_suffix_and_by_seed(query):
    flagged = dict(query("select login, is_bot from 'silver/actors.parquet'"))
    assert flagged["dependabot[bot]"] is True
    assert flagged["Copilot"] is True
    assert flagged["maya"] is False


def test_bots_never_count_as_human_activity(query):
    assert scalar(
        query,
        f"""select count(*) from 'gold/gold_repo_metrics.parquet'
            where repo_id = {WIDGETS} and human_events >= 80""",
    ) == 0
    assert scalar(
        query,
        """select count(*) from 'silver/pull_requests.parquet'
           where author_login = 'dependabot[bot]' and not author_is_bot""",
    ) == 0


def test_label_variants_map_to_good_first_issue(query):
    labels = {
        tuple(row[0])
        for row in query(
            """select labels from 'silver/issues.parquet'
               where is_good_first_issue"""
        )
    }
    assert ("good-first-issue",) in labels
    assert ("good first issue",) in labels


def test_labels_are_lowercase_and_trimmed(query):
    assert scalar(
        query,
        """select count(*) from (select unnest(labels) as label from 'silver/issues.parquet')
           where label <> lower(trim(label))""",
    ) == 0


def test_merge_events_do_not_make_someone_a_maintainer(pipeline):
    # ext-ana's merged PRs appear in the feed under her own name.
    assert "ext-ana" not in maintainers(pipeline, WIDGETS)
    assert {"maya", "omar"} <= maintainers(pipeline, WIDGETS)


def test_association_identifies_maintainers_on_older_payloads(pipeline):
    assert "lena" in maintainers(pipeline, OLDSTACK)


def test_external_means_a_fork_from_a_non_maintainer(pipeline):
    connection = duckdb.connect(str(pipeline.warehouse_path), read_only=True)
    rows = connection.execute(
        """select author_login, is_fork, is_external
           from staging.int_pr_facts
           where repo_id = 101 and pr_number between 100 and 131"""
    ).fetchall()
    connection.close()
    assert rows
    for author, is_fork, is_external in rows:
        assert is_external == (is_fork and author.startswith("ext-"))


def test_repos_that_can_rank_are_enriched_first(pipeline):
    connection = duckdb.connect(str(pipeline.warehouse_path), read_only=True)
    rows = connection.execute(
        """select activity_rank, meets_min_activity and evidence_points >= 5
           from staging.int_enrichment_candidates"""
    ).fetchall()
    connection.close()
    can_rank = [rank for rank, passes in rows if passes]
    others = [rank for rank, passes in rows if not passes]
    assert can_rank and others
    assert max(can_rank) < min(others)


def test_merged_prs_get_their_author_from_the_merged_event(query):
    assert scalar(
        query,
        """select count(*) from 'silver/pull_requests.parquet'
           where is_merged and author_login is null""",
    ) == 0


def test_unmerged_closes_are_not_lost_when_author_is_unknown(query):
    merged, closed = query(
        f"""select external_prs_merged, external_prs_closed_unmerged
            from 'gold/gold_repo_metrics.parquet' where repo_id = {ENGINE}"""
    )[0]
    assert merged == 1
    assert closed == 3


def test_friendly_repo_merges_everything(query):
    assert scalar(
        query,
        f"select external_pr_merge_rate from 'gold/gold_repo_metrics.parquet' "
        f"where repo_id = {WIDGETS}",
    ) == 1.0


def test_response_times_match_the_fixture(query):
    friendly, slow = (
        scalar(
            query,
            f"select pr_first_response_median_h from 'gold/gold_repo_metrics.parquet' "
            f"where repo_id = {repo}",
        )
        for repo in (WIDGETS, ENGINE)
    )
    assert friendly == pytest.approx(2.0)
    assert slow == pytest.approx(7.0)


def test_issue_response_counts_triage(query):
    assert scalar(
        query,
        f"select issue_first_response_median_h from 'gold/gold_repo_metrics.parquet' "
        f"where repo_id = {WIDGETS}",
    ) == pytest.approx(2.0)


def test_solo_repo_is_not_scored(query):
    assert scalar(
        query, f"select count(*) from 'gold/gold_repo_scores.parquet' where repo_id = {NOTES}"
    ) == 0


def test_friendlier_repo_scores_higher(query):
    scores = dict(query("select repo_id, score from 'gold/gold_repo_scores.parquet'"))
    assert scores[WIDGETS] > scores[ENGINE]


def test_scores_stay_in_range_in_all_scenarios(query):
    low, high = query("select min(score), max(score) from 'gold/gold_score_scenarios.parquet'")[0]
    assert 0 <= low <= high <= 100


def test_every_weight_scenario_is_scored(query):
    assert scalar(
        query, "select count(distinct scenario) from 'gold/gold_score_sensitivity.parquet'"
    ) == 6


def test_baseline_matches_itself_in_sensitivity(query):
    assert scalar(
        query,
        """select median_rank_shift from 'gold/gold_score_sensitivity.parquet'
           where scenario = 'baseline'""",
    ) == 0


def test_older_payloads_use_author_association(query):
    first_timers = scalar(
        query,
        f"""select first_time_prs_merged from 'gold/gold_repo_metrics.parquet'
            where repo_id = {OLDSTACK}""",
    )
    assert first_timers == 1


def test_older_merge_is_normalised(query):
    assert scalar(
        query, f"select count(*) from 'silver/events.parquet' where repo_id = {OLDSTACK} "
        "and action = 'merged'"
    ) == 4


def test_older_merge_actor_is_not_the_author(query):
    assert scalar(
        query,
        f"""select count(*) from 'silver/pull_requests.parquet'
            where repo_id = {OLDSTACK} and author_login = 'lena'""",
    ) == 0


def test_timestamp_anomaly_is_corrected_and_flagged(query):
    anomalies = query(
        """select created_at <= closed_at, has_timestamp_anomaly
           from 'silver/issues.parquet' where issue_number = 700"""
    )
    assert anomalies == [(True, True)]


def test_open_good_first_issues_are_exported(query):
    counts = dict(
        query(
            """select repo_id, len(open_good_first_issues)
               from 'gold/firstpr_export.parquet'"""
        )
    )
    assert counts[WIDGETS] == 4


def test_pickup_time_matches_the_fixture(query):
    assert scalar(
        query,
        f"select gfi_pickup_median_h from 'gold/gold_repo_metrics.parquet' "
        f"where repo_id = {WIDGETS}",
    ) == pytest.approx(4.0)


def test_good_first_issue_without_pickup_stays_null(query):
    assert scalar(
        query,
        f"select gfi_pickups from 'gold/gold_repo_metrics.parquet' where repo_id = {ENGINE}",
    ) == 0


def test_export_serialises_to_json(query):
    rows = query("select to_json(open_good_first_issues) from 'gold/firstpr_export.parquet'")
    assert all(re.match(r"^\[", json.dumps(json.loads(row[0]))) for row in rows)
