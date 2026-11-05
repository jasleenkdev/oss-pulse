-- Latest observed state per issue, from IssuesEvent and comments on the issue.
{{ config(location=layer_location('silver')) }}

with observations as (
    select *
    from {{ ref('stg_events') }}
    where issue_id is not null and not issue_is_pull_request
),

latest as (
    select
        issue_id,
        arg_max(repo_id, (created_at, event_id)) as repo_id,
        arg_max(repo_name, (created_at, event_id)) as repo_name,
        arg_max(issue_number, (created_at, event_id)) as issue_number,
        arg_max(issue_title, (created_at, event_id)) as title,
        arg_max(issue_state, (created_at, event_id)) as state,
        arg_max(issue_state_reason, (created_at, event_id)) as state_reason,
        arg_max(issue_closed_at, (created_at, event_id)) as closed_at,
        arg_max(issue_labels, (created_at, event_id)) as raw_labels,
        arg_max(issue_url, (created_at, event_id)) as url,
        arg_max(issue_comment_count, (created_at, event_id)) as comment_count,
        min(issue_created_at) as payload_created_at,
        min(created_at) as first_seen_at,
        max(created_at) as last_seen_at,
        count(*) as observed_events,
        arg_max(issue_user_login, (created_at, event_id)) as author_login,
        arg_max(issue_user_id, (created_at, event_id)) as author_id,
        arg_max(issue_user_type, (created_at, event_id)) as author_type,
        max(issue_author_association) as author_association
    from observations
    group by issue_id
),

-- A resource cannot be created after its first observed event or its close. GitHub
-- shifted embedded timestamps by +1h around the US DST change on 2026-11-01, in REST
-- as well as in events, while envelope timestamps stayed correct.
guarded as (
    select
        *,
        least(payload_created_at, first_seen_at, closed_at) as created_at,
        payload_created_at > least(first_seen_at, closed_at) as has_timestamp_anomaly
    from latest
),

labelled as (
    select
        guarded.*,
        list_transform(raw_labels, lambda x: lower(trim(x))) as labels,
        list_transform(raw_labels, lambda x: {{ label_key('x') }}) as label_keys
    from guarded
),

gfi_keys as (
    select list(label_key) as keys
    from {{ ref('label_mappings') }}
    where category = 'good_first_issue'
)

select
    issue_id,
    repo_id,
    repo_name,
    issue_number,
    title,
    state,
    state_reason,
    created_at,
    case when state = 'closed' then closed_at end as closed_at,
    last_seen_at,
    has_timestamp_anomaly,
    author_id,
    author_login,
    author_association,
    author_type = 'Bot' or {{ is_bot('author_login') }} as author_is_bot,
    url,
    comment_count,
    observed_events,
    labels,
    list_has_any(label_keys, (select keys from gfi_keys)) as is_good_first_issue
from labelled
