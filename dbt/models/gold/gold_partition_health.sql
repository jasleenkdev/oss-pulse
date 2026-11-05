-- Ingestion audit per hourly partition.
{{ config(location=layer_location('gold')) }}

select
    cast(partition_date as date) as partition_date,
    partition_hour,
    status,
    rows_read,
    rows_kept,
    rows_filtered,
    rows_rejected,
    rows_duplicate,
    rows_out_of_hour,
    bytes_compressed,
    bytes_uncompressed,
    attempts
from {{ source('bronze', 'audit') }}
