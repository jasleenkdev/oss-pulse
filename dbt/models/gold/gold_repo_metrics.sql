-- One row per repo with human activity in the window. Bots are excluded throughout.
{{ config(location=layer_location('gold')) }}

with bounds as (
    select * from {{ ref('window_bounds') }}
),

issue_counts as (
    select
        repo_id,
        count(*) filter (where created_at >= (select window_start from bounds)) as issues_opened,
        count(*) filter (where closed_at >= (select window_start from bounds)) as issues_closed
    from {{ ref('issues') }}
    where not author_is_bot
    group by repo_id
),

responses as (
    select
        repo_id,
        count(*) filter (where kind = 'issue') as external_issues,
        count(response_hours) filter (where kind = 'issue') as issue_responses,
        median(response_hours) filter (where kind = 'issue') as issue_first_response_median_h,
        quantile_cont(response_hours, 0.9) filter (where kind = 'issue') as issue_first_response_p90_h,
        count(*) filter (where kind = 'pr') as external_prs_with_created_at,
        count(response_hours) filter (where kind = 'pr') as pr_responses,
        median(response_hours) filter (where kind = 'pr') as pr_first_response_median_h,
        quantile_cont(response_hours, 0.9) filter (where kind = 'pr') as pr_first_response_p90_h
    from {{ ref('int_first_responses') }}
    group by repo_id
),

prs as (
    select
        repo_id,
        count(*) filter (where is_merged and not author_is_bot) as prs_merged,
        count(*) filter (where outcome = 'closed_unmerged' and not author_is_bot) as prs_closed_unmerged,
        count(*) filter (where is_merged and is_external) as external_prs_merged,
        count(*) filter (where outcome = 'closed_unmerged' and is_external) as external_prs_closed_unmerged,
        count(*) filter (where is_merged and is_first_time_proxy) as first_time_prs_merged,
        count(*) filter (where outcome = 'closed_unmerged' and is_first_time_proxy)
            as first_time_prs_closed_unmerged,
        median({{ hours_between('created_at', 'merged_at') }}) filter (
            where is_merged and not author_is_bot and not has_timestamp_anomaly
        ) as time_to_merge_median_h,
        count(created_at) filter (
            where is_merged and not author_is_bot and not has_timestamp_anomaly
        ) as time_to_merge_samples
    from {{ ref('int_pr_facts') }}
    group by repo_id
),

gfi as (
    select
        repo_id,
        count(*) filter (where state = 'open') as open_good_first_issues,
        count(*) as good_first_issues_seen,
        count(pickup_hours) as gfi_pickups,
        median(pickup_hours) as gfi_pickup_median_h
    from {{ ref('int_gfi_pickup') }}
    group by repo_id
),

popularity as (
    select
        repo_id,
        count(*) filter (where event_type = 'WatchEvent') as stars_gained,
        count(*) filter (where event_type = 'ForkEvent') as forks_gained
    from {{ ref('events') }}
    where not is_bot
    group by repo_id
),

maintainers_acting as (
    select e.repo_id, count(distinct e.actor_login) as distinct_maintainers_acting
    from {{ ref('events') }} e
    inner join {{ ref('int_maintainers') }} m
        on e.repo_id = m.repo_id and e.actor_login = m.login
    where not e.is_bot
    group by e.repo_id
),

enrichment as (
    select * from {{ source('enrichment', 'repo_metadata') }}
)

select
    a.repo_id,
    r.repo_name,
    e.language,
    e.topics,
    e.license,
    e.description,
    e.archived,
    e.stargazers_count,
    a.human_events,
    a.active_days,
    a.distinct_humans,
    a.external_contributors,
    a.meets_min_activity,
    coalesce(m.distinct_maintainers_acting, 0) as distinct_maintainers_acting,
    coalesce(i.issues_opened, 0) as issues_opened,
    coalesce(i.issues_closed, 0) as issues_closed,
    coalesce(s.external_issues, 0) as external_issues,
    coalesce(s.issue_responses, 0) as issue_responses,
    s.issue_first_response_median_h,
    s.issue_first_response_p90_h,
    coalesce(s.pr_responses, 0) as pr_responses,
    s.pr_first_response_median_h,
    s.pr_first_response_p90_h,
    coalesce(p.prs_merged, 0) as prs_merged,
    coalesce(p.prs_closed_unmerged, 0) as prs_closed_unmerged,
    p.prs_merged * 1.0 / nullif(p.prs_merged + p.prs_closed_unmerged, 0) as pr_merge_rate,
    coalesce(p.external_prs_merged, 0) as external_prs_merged,
    coalesce(p.external_prs_closed_unmerged, 0) as external_prs_closed_unmerged,
    p.external_prs_merged * 1.0
        / nullif(p.external_prs_merged + p.external_prs_closed_unmerged, 0) as external_pr_merge_rate,
    coalesce(p.first_time_prs_merged, 0) as first_time_prs_merged,
    coalesce(p.first_time_prs_closed_unmerged, 0) as first_time_prs_closed_unmerged,
    p.first_time_prs_merged * 1.0
        / nullif(p.first_time_prs_merged + p.first_time_prs_closed_unmerged, 0)
        as first_time_pr_merge_rate,
    p.time_to_merge_median_h,
    coalesce(p.time_to_merge_samples, 0) as time_to_merge_samples,
    coalesce(g.open_good_first_issues, 0) as open_good_first_issues,
    coalesce(g.good_first_issues_seen, 0) as good_first_issues_seen,
    coalesce(g.gfi_pickups, 0) as gfi_pickups,
    g.gfi_pickup_median_h,
    coalesce(o.stars_gained, 0) as stars_gained,
    coalesce(o.forks_gained, 0) as forks_gained,
    (select window_start from bounds) as window_start,
    (select window_end from bounds) as window_end
from {{ ref('int_repo_activity') }} a
inner join {{ ref('repos') }} r using (repo_id)
left join issue_counts i using (repo_id)
left join responses s using (repo_id)
left join prs p using (repo_id)
left join gfi g using (repo_id)
left join popularity o using (repo_id)
left join maintainers_acting m using (repo_id)
left join enrichment e using (repo_id)
