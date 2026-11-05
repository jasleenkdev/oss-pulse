-- Automation accounts by event volume, and their share of every event type.
{{ config(location=layer_location('gold')) }}

select
    'by_type' as breakdown,
    event_type as name,
    count(*) as total_events,
    count(*) filter (where is_bot) as bot_events,
    round(count(*) filter (where is_bot) * 1.0 / count(*), 4) as bot_share
from {{ ref('events') }}
group by event_type

union all

select 'overall', 'all events', count(*), count(*) filter (where is_bot),
    round(count(*) filter (where is_bot) * 1.0 / count(*), 4)
from {{ ref('events') }}

union all

select 'by_account', actor_login, count(*), count(*), 1.0
from {{ ref('events') }}
where is_bot
group by actor_login
