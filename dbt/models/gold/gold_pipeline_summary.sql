-- One row of run-level facts for the README, the dashboard and the quality report.
--
-- Capture rate is estimated from comment counters. issue.comments on an event gives the
-- comment's position in its thread, so for a thread whose observed positions span lo to
-- hi, the hi - lo - 1 interior comments are known to exist and seen - 2 were captured.
-- Interior positions avoid the selection effect of only seeing threads with a capture.
{{ config(location=layer_location('gold')) }}

with audit as (
    select * from {{ ref('gold_partition_health') }}
),

totals as (
    select
        count(*) as partitions_total,
        count(*) filter (where status = 'ok') as partitions_ok,
        count(*) filter (where status = 'missing') as partitions_missing,
        count(*) filter (where status = 'corrupt') as partitions_corrupt,
        cast(sum(rows_read) as bigint) as rows_read,
        cast(sum(rows_kept) as bigint) as rows_kept,
        cast(sum(rows_filtered) as bigint) as rows_filtered,
        cast(sum(rows_rejected) as bigint) as rows_rejected,
        cast(sum(rows_duplicate) as bigint) as rows_duplicate_within_partition,
        cast(sum(rows_out_of_hour) as bigint) as rows_out_of_hour,
        cast(sum(bytes_compressed) as bigint) as bytes_compressed,
        cast(sum(bytes_uncompressed) as bigint) as bytes_uncompressed
    from audit
),

threads as (
    select
        repo_id,
        issue_number,
        count(distinct comment_sequence) as seen,
        min(comment_sequence) as lo,
        max(comment_sequence) as hi
    from {{ ref('issue_comments') }}
    group by 1, 2
),

capture as (
    select sum(seen - 2) * 1.0 / nullif(sum(hi - lo - 1), 0) as estimated_capture_rate
    from threads
    where seen >= 2 and hi - lo >= 2
),

events as (
    select
        count(*) as silver_events,
        count(*) filter (where is_bot) as bot_events,
        count(distinct repo_id) as repos_seen,
        count(distinct actor_id) as actors_seen,
        max(created_at) as latest_event_at
    from {{ ref('events') }}
),

anomalies as (
    select
        (select count(*) from {{ ref('issues') }} where has_timestamp_anomaly)
        + (select count(*) from {{ ref('pull_requests') }} where has_timestamp_anomaly)
            as timestamp_anomalies
),

scored as (
    select count(*) as repos_scored from {{ ref('gold_repo_scores') }}
),

active as (
    select
        count(*) as repos_with_human_activity,
        count(*) filter (where meets_min_activity) as repos_meeting_min_activity,
        count(language) as repos_enriched
    from {{ ref('gold_repo_metrics') }}
)

select
    w.window_start,
    w.window_end,
    w.window_days,
    t.*,
    t.rows_kept - e.silver_events as rows_duplicate_across_partitions,
    e.silver_events,
    e.bot_events,
    round(e.bot_events * 1.0 / e.silver_events, 4) as bot_share,
    e.repos_seen,
    e.actors_seen,
    e.latest_event_at,
    round(c.estimated_capture_rate, 4) as estimated_capture_rate,
    a.timestamp_anomalies,
    s.repos_scored,
    x.repos_with_human_activity,
    x.repos_meeting_min_activity,
    x.repos_enriched
from {{ ref('window_bounds') }} w
cross join totals t
cross join events e
cross join capture c
cross join anomalies a
cross join scored s
cross join active x
