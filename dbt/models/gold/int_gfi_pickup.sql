-- Good first issues and the first contributor action on each.
--
-- labelled_at comes from a captured `labeled` event when there is one and otherwise
-- falls back to issue creation, which can only lengthen the measured time. Pickup time is
-- only measured when labelled_at is inside the window: otherwise a comment today on a
-- years-old issue reads as a pickup that took years.
-- A contributor action is a comment or assignment from someone who is neither the
-- author nor a maintainer, or a PR whose branch name cites the issue number. PR bodies
-- are no longer in the feed, so branch names are the only available link.
{{ config(materialized='table', location=none) }}

with gfi as (
    select * from {{ ref('issues') }} where is_good_first_issue and not author_is_bot
),

gfi_keys as (
    select label_key from {{ ref('label_mappings') }} where category = 'good_first_issue'
),

label_events as (
    select e.repo_id, e.issue_number, min(e.created_at) as labelled_at
    from {{ ref('stg_events') }} e
    inner join gfi_keys k on {{ label_key('e.label_name') }} = k.label_key
    where e.event_type = 'IssuesEvent' and e.action = 'labeled'
    group by 1, 2
),

base as (
    select
        g.*,
        coalesce(l.labelled_at, g.created_at) as labelled_at,
        case when l.labelled_at is null then 'issue_created' else 'labeled_event' end
            as labelled_at_source
    from gfi g
    left join label_events l using (repo_id, issue_number)
),

comment_actions as (
    select repo_id, issue_number, author_login as contributor, created_at as acted_at, 'comment' as how
    from {{ ref('issue_comments') }}
    where not is_pull_request and not author_is_bot
),

assign_actions as (
    select repo_id, issue_number, assignee_login, created_at, 'assignment'
    from {{ ref('stg_events') }}
    where event_type = 'IssuesEvent' and action = 'assigned' and assignee_login is not null
),

linked_prs as (
    select
        repo_id,
        try_cast(regexp_extract(lower(head_ref), '(?:issue|issues|fix|fixes|close|closes|gh|bug)[-_/#]*(\d+)', 1) as bigint)
            as issue_number,
        coalesce(author_login, closed_actor_login) as contributor,
        coalesce(created_at, merged_at, closed_at) as acted_at,
        'linked_pr' as how
    from {{ ref('pull_requests') }}
    where head_ref is not null and not author_is_bot
),

actions as (
    select * from comment_actions
    union all
    select * from assign_actions
    union all
    select * from linked_prs where issue_number is not null and acted_at is not null
),

contributor_actions as (
    select
        b.issue_id,
        a.acted_at,
        a.how
    from base b
    inner join actions a
        on a.repo_id = b.repo_id
        and a.issue_number = b.issue_number
        and a.acted_at >= b.labelled_at
        and a.contributor is distinct from b.author_login
        and not {{ is_bot('a.contributor') }}
    left join {{ ref('int_maintainers') }} m
        on a.repo_id = m.repo_id and a.contributor = m.login
    where m.login is null
),

first_action as (
    select issue_id, min(acted_at) as picked_up_at, arg_min(how, (acted_at, how)) as pickup_kind
    from contributor_actions
    group by issue_id
)

select
    b.issue_id,
    b.repo_id,
    b.repo_name,
    b.issue_number,
    b.title,
    b.url,
    b.state,
    b.labels,
    b.created_at,
    b.closed_at,
    b.last_seen_at,
    b.comment_count,
    b.labelled_at,
    b.labelled_at_source,
    f.picked_up_at,
    f.pickup_kind,
    b.labelled_at >= (select window_start from {{ ref('window_bounds') }}) as is_measurable,
    case
        when b.labelled_at >= (select window_start from {{ ref('window_bounds') }})
            then {{ hours_between('b.labelled_at', 'f.picked_up_at') }}
    end as pickup_hours
from base b
left join first_action f using (issue_id)
