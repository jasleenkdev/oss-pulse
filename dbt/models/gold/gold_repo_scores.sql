-- The newcomer friendliness ranking: baseline scores with component values and how
-- far each repo's rank moves across the weighting scenarios.
{{ config(location=layer_location('gold')) }}

with baseline as (
    select * from {{ ref('gold_score_scenarios') }} where scenario = 'baseline'
),

spread as (
    select repo_id, min(score_rank) as best_rank, max(score_rank) as worst_rank
    from {{ ref('gold_score_scenarios') }}
    group by repo_id
),

components as (
    select
        repo_id,
        count(*) as components_present,
        max(value) filter (where component = 'issue_response') as component_issue_response,
        max(value) filter (where component = 'pr_response') as component_pr_response,
        max(value) filter (where component = 'external_merge_rate') as component_external_merge_rate,
        max(value) filter (where component = 'time_to_merge') as component_time_to_merge,
        max(value) filter (where component = 'gfi_supply') as component_gfi_supply,
        max(value) filter (where component = 'activity_health') as component_activity_health
    from {{ ref('int_score_components') }}
    group by repo_id
)

select
    b.repo_id,
    m.repo_name,
    m.language,
    m.license,
    m.description,
    m.stargazers_count,
    b.score,
    b.score_rank,
    s.best_rank,
    s.worst_rank,
    c.components_present,
    c.component_issue_response,
    c.component_pr_response,
    c.component_external_merge_rate,
    c.component_time_to_merge,
    c.component_gfi_supply,
    c.component_activity_health,
    m.issue_first_response_median_h,
    m.issue_responses,
    m.pr_first_response_median_h,
    m.pr_responses,
    m.external_pr_merge_rate,
    m.external_prs_merged,
    m.external_prs_closed_unmerged,
    m.time_to_merge_median_h,
    m.open_good_first_issues,
    m.active_days,
    m.distinct_maintainers_acting,
    m.human_events,
    m.external_contributors
from baseline b
inner join {{ ref('gold_repo_metrics') }} m using (repo_id)
inner join spread s using (repo_id)
inner join components c using (repo_id)
