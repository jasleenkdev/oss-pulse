-- Pull request reviews and diff comments. Reviews and comments have separate id
-- spaces, so the key carries the kind.
{{ config(location=layer_location('silver')) }}

with reviews as (
    select
        'review:' || review_id as review_key,
        'review' as review_kind,
        repo_id,
        pr_number,
        review_user_id as author_id,
        review_user_login as author_login,
        is_bot,
        review_state as state,
        review_author_association as author_association,
        least(review_submitted_at, created_at) as submitted_at,
        created_at as event_at
    from {{ ref('stg_events') }}
    where event_type = 'PullRequestReviewEvent' and review_id is not null and pr_number is not null
),

diff_comments as (
    select
        'comment:' || comment_id,
        'review_comment',
        repo_id,
        pr_number,
        comment_user_id,
        comment_user_login,
        is_bot,
        cast(null as varchar),
        comment_author_association,
        least(comment_created_at, created_at),
        created_at
    from {{ ref('stg_events') }}
    where event_type = 'PullRequestReviewCommentEvent'
      and comment_id is not null
      and pr_number is not null
)

select
    review_key,
    any_value(review_kind) as review_kind,
    any_value(repo_id) as repo_id,
    any_value(pr_number) as pr_number,
    any_value(repo_id) || '#' || any_value(pr_number) as pr_key,
    arg_max(author_id, event_at) as author_id,
    arg_max(author_login, event_at) as author_login,
    bool_or(is_bot) or {{ is_bot('arg_max(author_login, event_at)') }} as author_is_bot,
    arg_max(state, event_at) as state,
    max(author_association) as author_association,
    min(submitted_at) as submitted_at
from (select * from reviews union all select * from diff_comments)
group by review_key
