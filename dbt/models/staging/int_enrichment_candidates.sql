-- Repositories worth a REST call: those that can be scored first, then by activity.
{{ config(materialized='table') }}

select
    a.repo_id,
    r.repo_name,
    a.human_events,
    a.meets_min_activity,
    row_number() over (
        order by a.meets_min_activity desc, a.human_events desc, a.repo_id
    ) as activity_rank
from {{ ref('int_repo_activity') }} a
inner join {{ ref('repos') }} r using (repo_id)
