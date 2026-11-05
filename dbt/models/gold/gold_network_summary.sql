-- Network-wide figures, bots excluded, for the findings and the dashboard overview.
{{ config(location=layer_location('gold')) }}

with facts as (
    select
        *,
        case when not has_timestamp_anomaly then {{ hours_between('created_at', 'merged_at') }} end
            as merge_hours
    from {{ ref('int_pr_facts') }}
    where not author_is_bot
),

prs as (
    select
        count(*) filter (where is_merged) as prs_merged,
        count(*) filter (where outcome = 'closed_unmerged') as prs_closed_unmerged,
        count(*) filter (where is_merged and is_fork) as fork_prs_merged,
        count(*) filter (where outcome = 'closed_unmerged' and is_fork) as fork_prs_closed_unmerged,
        count(*) filter (where is_merged and is_fork = false) as branch_prs_merged,
        count(*) filter (where outcome = 'closed_unmerged' and is_fork = false) as branch_prs_closed_unmerged,
        count(*) filter (where is_merged and is_external) as external_prs_merged,
        count(*) filter (where outcome = 'closed_unmerged' and is_external) as external_prs_closed_unmerged,
        count(*) filter (where is_merged and is_first_time_proxy) as first_time_prs_merged,
        count(*) filter (where outcome = 'closed_unmerged' and is_first_time_proxy)
            as first_time_prs_closed_unmerged,
        round(median(merge_hours), 3) as time_to_merge_median_h,
        round(quantile_cont(merge_hours, 0.9), 3) as time_to_merge_p90_h,
        count(merge_hours) as time_to_merge_samples,
        round(median(merge_hours) filter (where is_external), 3) as external_time_to_merge_median_h,
        count(merge_hours) filter (where is_external) as external_time_to_merge_samples,
        round(median(merge_hours) filter (where is_fork = false), 3) as branch_time_to_merge_median_h,
        count(merge_hours) filter (where is_fork = false) as branch_time_to_merge_samples
    from facts
),

gfi as (
    select
        count(*) as good_first_issues_seen,
        count(*) filter (where state = 'open') as open_good_first_issues,
        count(distinct repo_id) as repos_with_good_first_issues,
        count(*) filter (where is_measurable) as gfi_measurable,
        count(pickup_hours) as gfi_pickups,
        round(median(pickup_hours), 3) as gfi_pickup_median_h,
        round(quantile_cont(pickup_hours, 0.9), 3) as gfi_pickup_p90_h,
        count(pickup_hours) filter (where pickup_kind = 'comment') as gfi_pickups_by_comment,
        count(pickup_hours) filter (where pickup_kind = 'assignment') as gfi_pickups_by_assignment,
        count(pickup_hours) filter (where pickup_kind = 'linked_pr') as gfi_pickups_by_linked_pr,
        count(*) filter (where labelled_at_source = 'labeled_event') as gfi_with_labeled_event
    from {{ ref('int_gfi_pickup') }}
),

maintainers as (
    select
        count(*) as maintainers_inferred,
        count(*) filter (where is_owner) as maintainers_owner,
        count(*) filter (where has_push_evidence) as maintainers_push,
        count(*) filter (where has_triage_evidence) as maintainers_triage
    from {{ ref('int_maintainers') }}
),

solo as (
    select
        round(
            count(*) filter (where distinct_maintainers_acting <= 1) * 1.0 / count(*), 4
        ) as scored_repos_single_maintainer_share,
        count(*) filter (where distinct_maintainers_acting <= 1) as scored_repos_single_maintainer,
        round(median(distinct_maintainers_acting), 1) as scored_repos_median_maintainers
    from {{ ref('gold_repo_scores') }}
)

select
    p.*,
    round(prs_merged * 1.0 / nullif(prs_merged + prs_closed_unmerged, 0), 4) as pr_merge_rate,
    round(fork_prs_merged * 1.0 / nullif(fork_prs_merged + fork_prs_closed_unmerged, 0), 4)
        as fork_pr_merge_rate,
    round(branch_prs_merged * 1.0 / nullif(branch_prs_merged + branch_prs_closed_unmerged, 0), 4)
        as branch_pr_merge_rate,
    round(external_prs_merged * 1.0 / nullif(external_prs_merged + external_prs_closed_unmerged, 0), 4)
        as external_pr_merge_rate,
    round(first_time_prs_merged * 1.0 / nullif(first_time_prs_merged + first_time_prs_closed_unmerged, 0), 4)
        as first_time_pr_merge_rate,
    g.*,
    round(gfi_pickups * 1.0 / nullif(gfi_measurable, 0), 4) as gfi_pickup_share,
    m.*,
    s.*
from prs p
cross join gfi g
cross join maintainers m
cross join solo s
