-- Pull requests classified by who wrote them.
--
--   external          a fork PR from somebody who is not a maintainer. A same-repo branch
--                     needs push access, so it is never external. Fork status has to be
--                     observed: about 94% of PRs are same-repo, so treating unknown as
--                     external sweeps in solo developers merging their own work. A fork
--                     PR with no known author still counts, because the `closed` event
--                     does not identify the author and dropping those would remove most
--                     rejections and inflate merge rates.
--   first_time_proxy  external, and the contributor has no earlier observed activity in
--                     the repo during the window. author_association wins when present.
{{ config(materialized='table', location=none) }}

with first_activity as (
    select repo_id, actor_login as login, min(created_at) as first_seen_at
    from {{ ref('events') }}
    group by 1, 2
),

classified as (
    select
        pr.*,
        coalesce(pr.author_login, pr.closed_actor_login) as contributor_login,
        pr.author_login is not null and m.login is not null as author_is_maintainer
    from {{ ref('pull_requests') }} pr
    left join {{ ref('int_maintainers') }} m
        on pr.repo_id = m.repo_id and pr.author_login = m.login
),

flagged as (
    select
        c.*,
        (
            not c.author_is_bot
            and not c.author_is_maintainer
            and c.author_association is distinct from 'OWNER'
            and c.author_association is distinct from 'MEMBER'
            and c.author_association is distinct from 'COLLABORATOR'
            and coalesce(c.is_fork, false)
        ) as is_external,
        f.first_seen_at as contributor_first_seen_at
    from classified c
    left join first_activity f
        on c.repo_id = f.repo_id and c.contributor_login = f.login
)

select
    *,
    is_external
    and contributor_login is not null
    and not {{ is_bot('contributor_login') }}
    and (
        author_association in ('FIRST_TIME_CONTRIBUTOR', 'FIRST_TIMER')
        or (
            author_association is null
            and contributor_first_seen_at
                >= coalesce(created_at, least(merged_at, closed_at), contributor_first_seen_at)
        )
    ) as is_first_time_proxy
from flagged
