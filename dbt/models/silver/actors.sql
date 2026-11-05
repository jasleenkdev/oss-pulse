-- Every account seen, as an event actor or embedded in a payload.
{{ config(location=layer_location('silver')) }}

with sightings as (
    select actor_id as id, actor_login as login, created_at, event_id, cast(null as varchar) as type
    from {{ ref('stg_events') }}
    union all
    select issue_user_id, issue_user_login, created_at, event_id, issue_user_type
    from {{ ref('stg_events') }}
    where issue_user_id is not null
    union all
    select comment_user_id, comment_user_login, created_at, event_id, comment_user_type
    from {{ ref('stg_events') }}
    where comment_user_id is not null
    union all
    select review_user_id, review_user_login, created_at, event_id, cast(null as varchar)
    from {{ ref('stg_events') }}
    where review_user_id is not null
    union all
    select pr_user_id, pr_user_login, created_at, event_id, cast(null as varchar)
    from {{ ref('stg_events') }}
    where pr_user_id is not null
),

rollup as (
    select
        id as actor_id,
        arg_max(login, (created_at, event_id)) as login,
        bool_or(type = 'Bot') as has_bot_type,
        min(created_at) as first_seen_at,
        max(created_at) as last_seen_at
    from sightings
    group by id
),

activity as (
    select actor_id, count(*) as events_acted, count(distinct repo_id) as repos_touched
    from {{ ref('stg_events') }}
    group by actor_id
)

select
    r.actor_id,
    r.login,
    coalesce(r.has_bot_type, false) or {{ is_bot('r.login') }} as is_bot,
    r.first_seen_at,
    r.last_seen_at,
    coalesce(a.events_acted, 0) as events_acted,
    coalesce(a.repos_touched, 0) as repos_touched
from rollup r
left join activity a using (actor_id)
