-- Headline response statistics by item kind, with response coverage.
{{ config(location=layer_location('gold')) }}

select
    kind,
    count(*) as items,
    count(response_hours) as items_with_response,
    round(count(response_hours) * 1.0 / count(*), 4) as observed_response_share,
    round(median(response_hours), 3) as median_h,
    round(quantile_cont(response_hours, 0.9), 3) as p90_h,
    count(*) filter (where is_exact and response_hours is not null) as exact_items,
    round(median(response_hours) filter (where is_exact), 3) as exact_median_h
from {{ ref('int_first_responses') }}
group by kind
