-- Good first issues still open at their last observed state.
{{ config(location=layer_location('gold')) }}

select
    p.issue_id,
    p.repo_id,
    p.repo_name,
    m.language,
    p.issue_number,
    p.title,
    p.url,
    p.labels,
    p.created_at,
    p.last_seen_at,
    p.comment_count,
    p.picked_up_at,
    p.pickup_kind
from {{ ref('int_gfi_pickup') }} p
left join {{ ref('gold_repo_metrics') }} m using (repo_id)
where p.state = 'open'
  and coalesce(m.archived, false) = false
