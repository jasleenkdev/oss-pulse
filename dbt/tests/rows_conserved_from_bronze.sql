-- Every line read must be accounted for: kept, filtered, rejected or duplicate.
select partition_date, partition_hour
from {{ ref('gold_partition_health') }}
where rows_read <> rows_kept + rows_filtered + rows_rejected + rows_duplicate
