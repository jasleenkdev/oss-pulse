-- Conformed event log: one row per event id, typed, with bots flagged but retained.
{{ config(location=layer_location('silver')) }}

select
    event_id,
    event_type,
    action,
    created_at,
    event_date,
    actor_id,
    actor_login,
    is_bot,
    repo_id,
    repo_name
from {{ ref('stg_events') }}
