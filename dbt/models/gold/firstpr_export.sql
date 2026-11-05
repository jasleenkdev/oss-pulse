-- Versioned feature table for the FirstPR recommender. See contracts/firstpr_export_v1.yml.
-- Rows: every scored repo, plus any active repo with an open good first issue.
{{ config(location=layer_location('gold')) }}

with open_issues as (
    select
        repo_id,
        list(
            {
                'issue_number': issue_number,
                'title': title,
                'url': url,
                'labels': labels,
                'created_at': created_at,
                'last_seen_at': last_seen_at,
                'comment_count': comment_count,
                'picked_up': picked_up_at is not null
            }
            order by created_at desc, issue_number
        ) as open_good_first_issues
    from {{ ref('gold_open_good_first_issues') }}
    group by repo_id
)

select
    'v1' as export_version,
    m.repo_id,
    m.repo_name,
    m.language,
    coalesce(m.topics, []) as topics,
    m.license,
    m.description,
    coalesce(m.archived, false) as archived,
    m.stargazers_count,
    s.score as friendliness_score,
    s.score_rank as friendliness_rank,
    s.best_rank as friendliness_best_rank,
    s.worst_rank as friendliness_worst_rank,
    coalesce(s.components_present, 0) as score_components_present,
    m.issue_first_response_median_h,
    m.issue_responses,
    m.pr_first_response_median_h,
    m.pr_responses,
    m.external_pr_merge_rate,
    m.external_prs_merged + m.external_prs_closed_unmerged as external_prs_resolved,
    m.first_time_pr_merge_rate,
    m.first_time_prs_merged + m.first_time_prs_closed_unmerged as first_time_prs_resolved,
    m.time_to_merge_median_h,
    m.gfi_pickup_median_h,
    m.gfi_pickups,
    m.stars_gained,
    m.forks_gained,
    m.active_days,
    m.distinct_maintainers_acting,
    m.human_events,
    m.external_contributors,
    m.open_good_first_issues as open_good_first_issue_count,
    coalesce(o.open_good_first_issues, []) as open_good_first_issues,
    m.window_start,
    m.window_end
from {{ ref('gold_repo_metrics') }} m
left join {{ ref('gold_repo_scores') }} s using (repo_id)
left join open_issues o using (repo_id)
where s.repo_id is not null
   or (o.repo_id is not null and coalesce(m.archived, false) = false)
