-- Score and rank per repo under every weighting scenario. A missing component does not
-- count as zero: weights are renormalised across the components the repo has evidence
-- for, and repos with too few components are not scored.
{{ config(location=layer_location('gold')) }}

with present as (
    select repo_id, count(*) as components_present
    from {{ ref('int_score_components') }}
    group by repo_id
),

scorable as (
    select repo_id, components_present
    from present
    where components_present >= (
        select value from {{ ref('score_thresholds') }} where name = 'min_components'
    )
),

scored as (
    select
        w.scenario,
        c.repo_id,
        100.0 * sum(w.weight * c.value) / sum(w.weight) as score
    from {{ ref('int_score_components') }} c
    inner join scorable s using (repo_id)
    inner join {{ ref('score_weights') }} w using (component)
    group by w.scenario, c.repo_id
)

select
    scenario,
    repo_id,
    round(score, 2) as score,
    rank() over (partition by scenario order by score desc, repo_id) as score_rank
from scored
