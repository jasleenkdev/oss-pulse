-- Network-wide spread of first maintainer response times, for all observed responses
-- and for the subset known to be the first comment on the thread.
{{ config(location=layer_location('gold')) }}

with labelled as (
    select
        kind,
        response_hours,
        is_exact,
        case
            when response_hours < 1 then 1
            when response_hours < 6 then 2
            when response_hours < 24 then 3
            when response_hours < 72 then 4
            else 5
        end as bucket_order
    from {{ ref('int_first_responses') }}
    where response_hours is not null
),

names(bucket_order, bucket) as (
    values (1, 'under 1h'), (2, '1-6h'), (3, '6-24h'), (4, '1-3d'), (5, '3d+')
)

select
    l.kind,
    n.bucket_order,
    n.bucket,
    count(*) as responses,
    count(*) filter (where l.is_exact) as exact_responses
from labelled l
inner join names n using (bucket_order)
group by 1, 2, 3
