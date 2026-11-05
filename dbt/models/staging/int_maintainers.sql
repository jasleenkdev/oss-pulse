-- Who counts as a maintainer of a repo. author_association has not been in the feed
-- since late 2025, so it is used when present and otherwise inferred from behaviour
-- that needs repository permissions:
--
--   owner_namespace  the login is the repo's owner
--   push_branch_pr   opened or merged a PR from a branch of the repo itself, which
--                    needs push access (a fork PR does not)
--   issue_triage     labelled, unlabelled or closed somebody else's issue
--
-- Merge events are deliberately not evidence of a maintainer. REST ground truth
-- showed the actor on a `merged` event is the PR author, not the person who merged.
-- scripts/validate_fallbacks.py measures these rules against REST author_association.
{{ config(materialized='table') }}

with events as (
    select * from {{ ref('stg_events') }} where not is_bot
),

evidence as (
    select repo_id, actor_login as login, 'owner_namespace' as evidence
    from events
    where actor_login = repo_owner

    union all
    select repo_id, actor_login, 'push_branch_pr'
    from events
    where event_type = 'PullRequestEvent'
      and action in ('opened', 'merged')
      and pr_head_repo_id = pr_base_repo_id
      and pr_user_login is null

    union all
    select repo_id, coalesce(pr_user_login, actor_login), 'push_branch_pr'
    from events
    where event_type = 'PullRequestEvent'
      and action = 'opened'
      and pr_head_repo_id = pr_base_repo_id
      and pr_user_login is not null

    union all
    select repo_id, actor_login, 'issue_triage'
    from events
    where event_type = 'IssuesEvent'
      and action in ('labeled', 'unlabeled', 'closed')
      and actor_login is distinct from issue_user_login

    union all
    select repo_id, comment_user_login, 'author_association'
    from events
    where comment_author_association in ('OWNER', 'MEMBER', 'COLLABORATOR')

    union all
    select repo_id, review_user_login, 'author_association'
    from events
    where review_author_association in ('OWNER', 'MEMBER', 'COLLABORATOR')

    union all
    select repo_id, issue_user_login, 'author_association'
    from events
    where issue_author_association in ('OWNER', 'MEMBER', 'COLLABORATOR')

    union all
    select repo_id, pr_user_login, 'author_association'
    from events
    where pr_author_association in ('OWNER', 'MEMBER', 'COLLABORATOR')
)

select
    repo_id,
    login,
    bool_or(evidence = 'owner_namespace') as is_owner,
    bool_or(evidence = 'push_branch_pr') as has_push_evidence,
    bool_or(evidence = 'issue_triage') as has_triage_evidence,
    bool_or(evidence = 'author_association') as has_association_evidence
from evidence
where login is not null
group by 1, 2
