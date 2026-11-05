-- Every weighting scenario must total 1.
select scenario, sum(weight) as total
from {{ ref('score_weights') }}
group by scenario
having abs(sum(weight) - 1) > 0.001
