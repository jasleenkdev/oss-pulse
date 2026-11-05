-- A merged pull request must have a closed timestamp and the merged outcome.
select pr_key
from {{ ref('pull_requests') }}
where merged_at is not null and (closed_at is null or outcome <> 'merged')
