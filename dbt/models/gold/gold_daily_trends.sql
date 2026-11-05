-- Network-wide activity per day, split between people and bots.
{{ config(location=layer_location('gold')) }}

with days as (
    select
        event_date,
        count(*) as total_events,
        count(*) filter (where is_bot) as bot_events,
        count(*) filter (where not is_bot) as human_events,
        count(distinct repo_id) filter (where not is_bot) as active_repos,
        count(distinct actor_id) filter (where not is_bot) as active_humans,
        count(*) filter (where event_type = 'IssuesEvent' and action = 'opened' and not is_bot) as issues_opened,
        count(*) filter (where event_type = 'IssuesEvent' and action = 'closed' and not is_bot) as issues_closed,
        count(*) filter (where event_type = 'PullRequestEvent' and action = 'opened' and not is_bot) as prs_opened,
        count(*) filter (where event_type = 'PullRequestEvent' and action = 'merged' and not is_bot) as prs_merged,
        count(*) filter (where event_type = 'WatchEvent') as stars,
        count(*) filter (where event_type = 'ForkEvent') as forks
    from {{ ref('events') }}
    group by event_date
),

responses as (
    select
        cast(first_response_at as date) as event_date,
        count(*) as responses,
        median(response_hours) filter (where kind = 'issue') as issue_response_median_h,
        median(response_hours) filter (where kind = 'pr') as pr_response_median_h
    from {{ ref('int_first_responses') }}
    where response_hours is not null
    group by 1
)

select d.*, r.responses, r.issue_response_median_h, r.pr_response_median_h
from days d
left join responses r using (event_date)
