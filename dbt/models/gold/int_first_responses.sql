-- First observed maintainer response to items raised by non-maintainers and created
-- inside the window. One row per item with `kind` = issue or pr; unanswered items have
-- a null first_response_at. "First observed": a missed event can only make the true
-- response earlier, so these durations are upper bounds. `is_exact` marks responses
-- known to be the first comment on the thread, from the event's comment counter.
{{ config(materialized='table', location=none) }}

with bounds as (
    select * from {{ ref('window_bounds') }}
),

maintainers as (
    select repo_id, login from {{ ref('int_maintainers') }}
),

external_issues as (
    select i.issue_id as item_id, i.repo_id, i.issue_number as number, i.author_login, i.created_at
    from {{ ref('issues') }} i
    left join maintainers m on i.repo_id = m.repo_id and i.author_login = m.login
    where not i.author_is_bot
      and m.login is null
      and i.author_association is distinct from 'OWNER'
      and i.author_association is distinct from 'MEMBER'
      and i.author_association is distinct from 'COLLABORATOR'
      and i.created_at >= (select window_start from bounds)
),

external_prs as (
    select pr_key as item_id, repo_id, pr_number as number, author_login, created_at, merged_at
    from {{ ref('int_pr_facts') }}
    where is_external
      and created_at >= (select window_start from bounds)
),

issue_comment_actions as (
    select
        c.repo_id,
        c.issue_number as number,
        c.is_pull_request,
        c.author_login as actor_login,
        c.created_at as acted_at,
        c.comment_sequence = 1 as is_first_comment
    from {{ ref('issue_comments') }} c
    where not c.author_is_bot
),

issue_triage_actions as (
    select
        repo_id,
        issue_number as number,
        false as is_pull_request,
        actor_login,
        created_at as acted_at,
        false as is_first_comment
    from {{ ref('stg_events') }}
    where event_type = 'IssuesEvent'
      and action in ('labeled', 'unlabeled', 'assigned', 'closed')
      and not is_bot
),

review_actions as (
    select
        repo_id,
        pr_number as number,
        true as is_pull_request,
        author_login as actor_login,
        submitted_at as acted_at,
        false as is_first_comment
    from {{ ref('reviews') }}
    where not author_is_bot
),

actions as (
    select * from issue_comment_actions
    union all
    select * from issue_triage_actions
    union all
    select * from review_actions
),

maintainer_actions as (
    select a.*
    from actions a
    inner join maintainers m on a.repo_id = m.repo_id and a.actor_login = m.login
),

issue_responses as (
    select
        i.item_id,
        i.repo_id,
        'issue' as kind,
        i.created_at,
        min(a.acted_at) as first_response_at,
        arg_min(a.is_first_comment, a.acted_at) as is_exact
    from external_issues i
    left join maintainer_actions a
        on a.repo_id = i.repo_id
        and a.number = i.number
        and not a.is_pull_request
        and a.actor_login is distinct from i.author_login
        and a.acted_at >= i.created_at
    group by i.item_id, i.repo_id, i.created_at
),

pr_responses as (
    select
        p.item_id,
        p.repo_id,
        'pr' as kind,
        p.created_at,
        -- An external PR can only be merged by someone with write access.
        least(min(a.acted_at), p.merged_at) as first_response_at,
        coalesce(arg_min(a.is_first_comment, a.acted_at), false) as is_exact
    from external_prs p
    left join maintainer_actions a
        on a.repo_id = p.repo_id
        and a.number = p.number
        and a.is_pull_request
        and a.actor_login is distinct from p.author_login
        and a.acted_at >= p.created_at
    group by p.item_id, p.repo_id, p.created_at, p.merged_at
),

unioned as (
    select * from issue_responses
    union all
    select * from pr_responses
)

select
    item_id,
    repo_id,
    kind,
    created_at,
    first_response_at,
    {{ hours_between('created_at', 'first_response_at') }} as response_hours,
    coalesce(is_exact, false) as is_exact
from unioned
