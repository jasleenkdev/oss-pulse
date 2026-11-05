-- How much the ranking depends on the weights: for each scenario, the Spearman rank
-- correlation with the baseline and the overlap of the top 10, 25 and 50.
{{ config(location=layer_location('gold')) }}

with baseline as (
    select repo_id, score_rank from {{ ref('gold_score_scenarios') }} where scenario = 'baseline'
),

paired as (
    select s.scenario, s.repo_id, s.score_rank, b.score_rank as baseline_rank
    from {{ ref('gold_score_scenarios') }} s
    inner join baseline b using (repo_id)
)

select
    scenario,
    count(*) as repos_scored,
    round(corr(score_rank, baseline_rank), 4) as spearman_with_baseline,
    count(*) filter (where score_rank <= 10 and baseline_rank <= 10) as top10_overlap,
    count(*) filter (where score_rank <= 25 and baseline_rank <= 25) as top25_overlap,
    count(*) filter (where score_rank <= 50 and baseline_rank <= 50) as top50_overlap,
    round(median(abs(score_rank - baseline_rank)), 1) as median_rank_shift
from paired
group by scenario
