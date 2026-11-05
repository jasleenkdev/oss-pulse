-- The metric window: the newest ingested day and the preceding window_days - 1 days.
{{ config(materialized='table') }}

with bounds as (
    select max(cast(partition_date as date)) as last_day
    from {{ source('bronze', 'audit') }}
    where status = 'ok'
)

select
    cast(last_day - interval ({{ var('window_days') }} - 1) day as timestamp) as window_start,
    cast(last_day + interval 1 day as timestamp) as window_end,
    {{ var('window_days') }} as window_days
from bounds
