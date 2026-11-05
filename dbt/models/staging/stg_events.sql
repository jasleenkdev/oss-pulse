-- Every field the models need, parsed once from the raw payload.
--
-- Payload shapes differ by era. Since late 2025 GH Archive PullRequestEvent rows
-- carry no author, timestamps, merged flag or author_association, and a merge
-- arrives as action = 'merged'. Older rows have all of those and report a merge as
-- action = 'closed' with merged = true. `action` here is normalised so that both
-- eras flow through the same models.
--
-- Two choices keep memory flat. All paths go through one json_extract_string call,
-- because that parses each document once while separate calls parse it once per
-- field. De-duplication ranks ids only, so raw payloads are never buffered.
{{ config(materialized='table') }}

{% set fields = [
    ['action_raw', '$.action'],
    ['pr_merged_flag', '$.pull_request.merged'],
    ['pr_number_nested', '$.pull_request.number'],
    ['pr_number_top', '$.number'],
    ['pr_id', '$.pull_request.id'],
    ['pr_head_repo_id', '$.pull_request.head.repo.id'],
    ['pr_base_repo_id', '$.pull_request.base.repo.id'],
    ['pr_head_ref', '$.pull_request.head.ref'],
    ['pr_user_login', '$.pull_request.user.login'],
    ['pr_user_id', '$.pull_request.user.id'],
    ['pr_created_at', '$.pull_request.created_at'],
    ['pr_merged_at', '$.pull_request.merged_at'],
    ['pr_author_association', '$.pull_request.author_association'],
    ['issue_id', '$.issue.id'],
    ['issue_number', '$.issue.number'],
    ['issue_title', '$.issue.title'],
    ['issue_state', '$.issue.state'],
    ['issue_state_reason', '$.issue.state_reason'],
    ['issue_created_at', '$.issue.created_at'],
    ['issue_closed_at', '$.issue.closed_at'],
    ['issue_user_login', '$.issue.user.login'],
    ['issue_user_id', '$.issue.user.id'],
    ['issue_user_type', '$.issue.user.type'],
    ['issue_author_association', '$.issue.author_association'],
    ['issue_url', '$.issue.html_url'],
    ['issue_comment_count', '$.issue.comments'],
    ['issue_pr_url', '$.issue.pull_request.url'],
    ['issue_pr_merged_at', '$.issue.pull_request.merged_at'],
    ['comment_id', '$.comment.id'],
    ['comment_user_id', '$.comment.user.id'],
    ['comment_user_login', '$.comment.user.login'],
    ['comment_user_type', '$.comment.user.type'],
    ['comment_created_at', '$.comment.created_at'],
    ['comment_author_association', '$.comment.author_association'],
    ['review_id', '$.review.id'],
    ['review_user_id', '$.review.user.id'],
    ['review_user_login', '$.review.user.login'],
    ['review_state', '$.review.state'],
    ['review_submitted_at', '$.review.submitted_at'],
    ['review_author_association', '$.review.author_association'],
    ['label_name', '$.label.name'],
    ['assignee_login', '$.assignee.login']
] %}
{% set position = {} %}
{% for field in fields %}{% do position.update({field[0]: loop.index}) %}{% endfor %}

with first_sighting as (
    select event_id, min(date || '-' || hour) as partition_key
    from {{ source('bronze', 'events') }}
    where created_at >= (select window_start from {{ ref('window_bounds') }})
      and created_at < (select window_end from {{ ref('window_bounds') }})
    group by event_id
),

deduped as (
    select bronze.*
    from {{ source('bronze', 'events') }} as bronze
    inner join first_sighting
        on bronze.event_id = first_sighting.event_id
        and bronze.date || '-' || bronze.hour = first_sighting.partition_key
),

parsed as (
    select
        event_id,
        event_type,
        created_at,
        actor_id,
        actor_login,
        repo_id,
        repo_name,
        org_login,
        json_extract_string(payload, [
            {%- for field in fields %}'{{ field[1] }}'{% if not loop.last %}, {% endif %}{% endfor -%}
        ]) as f,
        json_extract(payload, '$.issue.labels') as labels_json
    from deduped
)

select
    event_id,
    event_type,
    created_at,
    cast(created_at as date) as event_date,
    actor_id,
    actor_login,
    {{ is_bot('actor_login') }} as is_bot,
    repo_id,
    repo_name,
    split_part(repo_name, '/', 1) as repo_owner,
    org_login,
    case
        when event_type = 'PullRequestEvent'
            and f[{{ position.action_raw }}] = 'closed'
            and f[{{ position.pr_merged_flag }}] = 'true'
            then 'merged'
        else f[{{ position.action_raw }}]
    end as action,

    -- pull request
    try_cast(coalesce(f[{{ position.pr_number_nested }}], f[{{ position.pr_number_top }}]) as bigint)
        as pr_number,
    {% for name in ['pr_id', 'pr_head_repo_id', 'pr_base_repo_id', 'pr_user_id'] -%}
    try_cast(f[{{ position[name] }}] as bigint) as {{ name }},
    {% endfor -%}
    {% for name in ['pr_head_ref', 'pr_user_login', 'pr_author_association'] -%}
    f[{{ position[name] }}] as {{ name }},
    {% endfor -%}
    {% for name in ['pr_created_at', 'pr_merged_at'] -%}
    try_cast(f[{{ position[name] }}] as timestamp) as {{ name }},
    {% endfor %}
    -- issue, also present on comments on a pull request
    {% for name in ['issue_id', 'issue_number', 'issue_user_id', 'issue_comment_count'] -%}
    try_cast(f[{{ position[name] }}] as bigint) as {{ name }},
    {% endfor -%}
    {% for name in ['issue_title', 'issue_state', 'issue_state_reason', 'issue_user_login',
                    'issue_user_type', 'issue_author_association', 'issue_url'] -%}
    f[{{ position[name] }}] as {{ name }},
    {% endfor -%}
    {% for name in ['issue_created_at', 'issue_closed_at', 'issue_pr_merged_at'] -%}
    try_cast(f[{{ position[name] }}] as timestamp) as {{ name }},
    {% endfor -%}
    coalesce(json_extract_string(labels_json, '$[*].name'), []) as issue_labels,
    f[{{ position.issue_pr_url }}] is not null as issue_is_pull_request,

    -- comment, on an issue or on a diff
    {% for name in ['comment_id', 'comment_user_id', 'review_id', 'review_user_id'] -%}
    try_cast(f[{{ position[name] }}] as bigint) as {{ name }},
    {% endfor -%}
    {% for name in ['comment_user_login', 'comment_user_type', 'comment_author_association',
                    'review_user_login', 'review_state', 'review_author_association',
                    'label_name', 'assignee_login'] -%}
    f[{{ position[name] }}] as {{ name }},
    {% endfor -%}
    {% for name in ['comment_created_at', 'review_submitted_at'] -%}
    try_cast(f[{{ position[name] }}] as timestamp) as {{ name }}{% if not loop.last %},{% endif %}
    {% endfor %}

from parsed
