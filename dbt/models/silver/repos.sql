-- One row per repository id. Names can change, so the most recent one wins.
{{ config(location=layer_location('silver')) }}

select
    repo_id,
    arg_max(repo_name, (created_at, event_id)) as repo_name,
    arg_max(repo_owner, (created_at, event_id)) as owner,
    max(org_login) as org_login,
    min(created_at) as first_seen_at,
    max(created_at) as last_seen_at,
    count(*) as total_events,
    count(*) filter (where not is_bot) as human_events
from {{ ref('stg_events') }}
group by repo_id
