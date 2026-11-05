-- Each score component on a 0-1 scale, as a percentile among eligible repos.
-- Higher is always friendlier. A component is null when the repo has no evidence for it.
-- Merge rates are shrunk toward the global rate first, so that one lucky PR cannot
-- outrank fifty merged PRs.
{{ config(materialized='table', location=none) }}

with thresholds as (
    select
        max(value) filter (where name = 'merge_rate_prior_strength') as prior_strength,
        max(value) filter (where name = 'min_evidence_points') as min_evidence_points
    from {{ ref('score_thresholds') }}
),

eligible as (
    select *
    from {{ ref('gold_repo_metrics') }}
    where meets_min_activity
      and coalesce(archived, false) = false
      and issue_responses + pr_responses + external_prs_merged + external_prs_closed_unmerged
          >= (select min_evidence_points from thresholds)
),

global_rate as (
    select
        sum(external_prs_merged) * 1.0
            / nullif(sum(external_prs_merged + external_prs_closed_unmerged), 0) as rate
    from eligible
),

prepared as (
    select
        e.*,
        case
            when external_prs_merged + external_prs_closed_unmerged > 0 then
                (external_prs_merged + t.prior_strength * coalesce(g.rate, 0))
                / (external_prs_merged + external_prs_closed_unmerged + t.prior_strength)
        end as shrunk_external_merge_rate
    from eligible e
    cross join thresholds t
    cross join global_rate g
),

-- percent_rank over the rows that have a value: nulls would otherwise take rank positions.
issue_response as (
    select repo_id, 1 - percent_rank() over (order by issue_first_response_median_h) as value
    from prepared where issue_first_response_median_h is not null
),

pr_response as (
    select repo_id, 1 - percent_rank() over (order by pr_first_response_median_h) as value
    from prepared where pr_first_response_median_h is not null
),

external_merge_rate as (
    select repo_id, percent_rank() over (order by shrunk_external_merge_rate) as value
    from prepared where shrunk_external_merge_rate is not null
),

time_to_merge as (
    select repo_id, 1 - percent_rank() over (order by time_to_merge_median_h) as value
    from prepared where time_to_merge_median_h is not null
),

gfi_supply as (
    select repo_id, percent_rank() over (order by open_good_first_issues) as value
    from prepared where open_good_first_issues > 0
),

activity_health as (
    select
        repo_id,
        (
            percent_rank() over (order by active_days)
            + percent_rank() over (order by distinct_maintainers_acting)
        ) / 2 as value
    from prepared
)

select repo_id, 'issue_response' as component, value from issue_response
union all select repo_id, 'pr_response', value from pr_response
union all select repo_id, 'external_merge_rate', value from external_merge_rate
union all select repo_id, 'time_to_merge', value from time_to_merge
union all select repo_id, 'gfi_supply', value from gfi_supply
union all select repo_id, 'activity_health', value from activity_health
