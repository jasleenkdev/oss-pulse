-- Repositories worth a REST call. Enrichment decides the archived flag, language and stars, so
-- every repository that can rank has to fall inside the call budget. Raw activity predicts that
-- poorly: ranking turns on observed responses and resolved external PRs, so this orders by the
-- same evidence gate as int_score_components, then by the amount of evidence and by activity.
{{ config(materialized='table') }}

with thresholds as (
    select value as min_evidence_points
    from {{ ref('score_thresholds') }}
    where name = 'min_evidence_points'
),

responses as (
    select repo_id, count(response_hours) as responses
    from {{ ref('int_first_responses') }}
    group by repo_id
),

resolved as (
    select repo_id, count(*) as resolved_external_prs
    from {{ ref('int_pr_facts') }}
    where is_external and (is_merged or outcome = 'closed_unmerged')
    group by repo_id
),

evidence as (
    select
        a.repo_id,
        a.human_events,
        a.meets_min_activity,
        coalesce(p.responses, 0) + coalesce(x.resolved_external_prs, 0) as evidence_points
    from {{ ref('int_repo_activity') }} a
    left join responses p using (repo_id)
    left join resolved x using (repo_id)
)

select
    e.repo_id,
    r.repo_name,
    e.human_events,
    e.meets_min_activity,
    e.evidence_points,
    row_number() over (
        order by
            e.meets_min_activity and e.evidence_points >= t.min_evidence_points desc,
            e.meets_min_activity desc,
            e.evidence_points desc,
            e.human_events desc,
            e.repo_id
    ) as activity_rank
from evidence e
cross join thresholds t
inner join {{ ref('repos') }} r using (repo_id)
