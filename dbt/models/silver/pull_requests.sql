-- One row per pull request, assembled from every event that mentions it.
--
-- The feed captures about one event in seventy, so one PR rarely has both its
-- `opened` and `merged` events. Fields therefore come from whichever source has them:
--   author      legacy payload, `opened` actor, comment snapshot, then `merged` actor
--               (validated against REST: the merged actor is the author, not the merger)
--   created_at  earliest of `opened` and the comment snapshot's issue.created_at
--   merged_at   comment snapshot, legacy payload, then the `merged` event time
-- The `closed` actor stays in its own column: it is the author only about 80% of the time.
{{ config(location=layer_location('silver')) }}

with pr_events as (
    select
        repo_id,
        pr_number,
        max(repo_name) as repo_name,
        max(pr_id) as pr_id,
        max(pr_user_login) as legacy_author_login,
        max(pr_user_id) as legacy_author_id,
        max(pr_author_association) as author_association,
        min(pr_created_at) as legacy_created_at,
        max(pr_merged_at) as legacy_merged_at,
        min(created_at) filter (where action = 'opened') as opened_event_at,
        max(created_at) filter (where action = 'merged') as merged_event_at,
        max(created_at) filter (where action = 'closed') as closed_event_at,
        max(created_at) filter (where action = 'reopened') as reopened_event_at,
        arg_max(actor_login, created_at) filter (where action = 'closed') as closed_actor_login,
        min(created_at) as first_pr_event_at,
        arg_min(actor_login, created_at) filter (where action = 'opened') as opened_actor_login,
        arg_min(actor_id, created_at) filter (where action = 'opened') as opened_actor_id,
        arg_max(actor_login, created_at) filter (where action = 'merged') as merged_actor_login,
        arg_max(actor_id, created_at) filter (where action = 'merged') as merged_actor_id
    from {{ ref('stg_events') }}
    where event_type = 'PullRequestEvent' and pr_number is not null
    group by repo_id, pr_number
),

-- Head and base survive on review events too, so they widen fork coverage.
branches as (
    select
        repo_id,
        pr_number,
        max(pr_head_repo_id) as head_repo_id,
        max(pr_base_repo_id) as base_repo_id,
        max(pr_head_ref) as head_ref
    from {{ ref('stg_events') }}
    where event_type in (
        'PullRequestEvent', 'PullRequestReviewEvent', 'PullRequestReviewCommentEvent'
    ) and pr_number is not null
    group by repo_id, pr_number
),

snapshots as (
    select
        repo_id,
        issue_number as pr_number,
        max(repo_name) as repo_name,
        min(issue_created_at) as snapshot_created_at,
        arg_max(issue_user_login, created_at) as snapshot_author_login,
        arg_max(issue_user_id, created_at) as snapshot_author_id,
        max(issue_pr_merged_at) as snapshot_merged_at,
        arg_max(issue_state, created_at) as snapshot_state,
        arg_max(issue_closed_at, created_at) as snapshot_closed_at,
        min(created_at) as first_comment_event_at,
        max(issue_author_association) as snapshot_association
    from {{ ref('stg_events') }}
    where event_type = 'IssueCommentEvent' and issue_is_pull_request
    group by repo_id, issue_number
),

review_mentions as (
    select repo_id, pr_number, max(repo_name) as repo_name, min(created_at) as first_review_event_at
    from {{ ref('stg_events') }}
    where event_type in ('PullRequestReviewEvent', 'PullRequestReviewCommentEvent')
      and pr_number is not null
    group by repo_id, pr_number
),

keys as (
    select repo_id, pr_number from pr_events
    union
    select repo_id, pr_number from snapshots
    union
    select repo_id, pr_number from review_mentions
),

joined as (
    select
        k.repo_id,
        k.pr_number,
        coalesce(e.repo_name, s.repo_name, r.repo_name) as repo_name,
        e.pr_id,
        b.head_repo_id,
        b.base_repo_id,
        b.head_ref,
        coalesce(e.author_association, s.snapshot_association) as author_association,
        coalesce(
            e.legacy_author_login,
            e.opened_actor_login,
            s.snapshot_author_login,
            e.merged_actor_login
        ) as author_login,
        coalesce(
            e.legacy_author_id,
            e.opened_actor_id,
            s.snapshot_author_id,
            e.merged_actor_id
        ) as author_id,
        case
            when e.legacy_author_login is not null then 'payload'
            when e.opened_actor_login is not null then 'opened_event'
            when s.snapshot_author_login is not null then 'comment_snapshot'
            when e.merged_actor_login is not null then 'merged_event'
        end as author_source,
        e.closed_actor_login,
        least(e.legacy_created_at, e.opened_event_at, s.snapshot_created_at) as payload_created_at,
        least(e.first_pr_event_at, s.first_comment_event_at, r.first_review_event_at)
            as first_seen_at,
        coalesce(s.snapshot_merged_at, e.legacy_merged_at, e.merged_event_at) as merged_at,
        e.reopened_event_at,
        greatest(
            e.closed_event_at,
            case when s.snapshot_state = 'closed' then s.snapshot_closed_at end
        ) as closed_unmerged_candidate_at
    from keys k
    left join pr_events e using (repo_id, pr_number)
    left join branches b using (repo_id, pr_number)
    left join snapshots s using (repo_id, pr_number)
    left join review_mentions r using (repo_id, pr_number)
),

resolved as (
    select
        *,
        case
            when merged_at is not null then merged_at
            when closed_unmerged_candidate_at > coalesce(reopened_event_at, timestamp '1970-01-01')
                then closed_unmerged_candidate_at
        end as closed_at
    from joined
),

-- created_at is only known from an opened event or a comment snapshot. When it is known
-- it cannot be later than the first event or the close; see the note in issues.sql.
guarded as (
    select
        *,
        case
            when payload_created_at is not null
                then least(payload_created_at, first_seen_at, closed_at)
        end as created_at,
        coalesce(payload_created_at > least(first_seen_at, closed_at), false)
            as has_timestamp_anomaly
    from resolved
)

select
    repo_id || '#' || pr_number as pr_key,
    repo_id,
    pr_number,
    repo_name,
    pr_id,
    author_id,
    author_login,
    author_source,
    closed_actor_login,
    coalesce({{ is_bot('author_login') }}, false) as author_is_bot,
    author_association,
    created_at,
    has_timestamp_anomaly,
    closed_at,
    merged_at,
    merged_at is not null as is_merged,
    case
        when merged_at is not null then 'merged'
        when closed_at is not null then 'closed_unmerged'
        else 'open_or_unknown'
    end as outcome,
    case
        when head_repo_id is null or base_repo_id is null then null
        else head_repo_id <> base_repo_id
    end as is_fork,
    head_ref
from guarded
