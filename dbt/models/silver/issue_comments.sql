-- One row per comment on an issue or a pull request conversation.
{{ config(location=layer_location('silver')) }}

select
    comment_id,
    arg_max(repo_id, created_at) as repo_id,
    arg_max(issue_id, created_at) as issue_id,
    arg_max(issue_number, created_at) as issue_number,
    bool_or(issue_is_pull_request) as is_pull_request,
    arg_max(repo_id, created_at) || '#' || arg_max(issue_number, created_at) as pr_key,
    arg_max(comment_user_id, created_at) as author_id,
    arg_max(comment_user_login, created_at) as author_login,
    bool_or(comment_user_type = 'Bot' or is_bot) as author_is_bot,
    max(comment_author_association) as author_association,
    least(min(comment_created_at), min(created_at)) as created_at,
    -- issue.comments on the event: 1 means this comment was the thread's first,
    -- which holds even though most events are missing from the feed.
    min(issue_comment_count) as comment_sequence
from {{ ref('stg_events') }}
where event_type = 'IssueCommentEvent' and comment_id is not null
group by comment_id
