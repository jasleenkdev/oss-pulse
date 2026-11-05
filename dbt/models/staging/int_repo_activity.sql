-- Human activity per repo, used for the minimum-activity gate and to choose which
-- repositories to enrich. Bots never count here.
{{ config(materialized='table') }}

with events as (
    select * from {{ ref('stg_events') }} where not is_bot
),

participants as (
    -- People who engaged with a repo. Stars and forks need no interaction, so they don't count.
    select distinct repo_id, actor_login as login
    from events
    where event_type in (
        'IssuesEvent', 'IssueCommentEvent', 'PullRequestEvent',
        'PullRequestReviewEvent', 'PullRequestReviewCommentEvent'
    )
),

external_participants as (
    select p.repo_id, count(*) as external_contributors
    from participants p
    left join {{ ref('int_maintainers') }} m
        on p.repo_id = m.repo_id and p.login = m.login
    where m.login is null
    group by p.repo_id
),

activity as (
    select
        repo_id,
        count(*) as human_events,
        count(distinct event_date) as active_days,
        count(distinct actor_login) as distinct_humans
    from events
    group by repo_id
)

select
    a.repo_id,
    a.human_events,
    a.active_days,
    a.distinct_humans,
    coalesce(x.external_contributors, 0) as external_contributors,
    a.human_events >= (select value from {{ ref('score_thresholds') }} where name = 'min_human_events')
        and a.active_days >= (select value from {{ ref('score_thresholds') }} where name = 'min_active_days')
        and coalesce(x.external_contributors, 0)
            >= (select value from {{ ref('score_thresholds') }} where name = 'min_external_contributors')
        as meets_min_activity
from activity a
left join external_participants x using (repo_id)
