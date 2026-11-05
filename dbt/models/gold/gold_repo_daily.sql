-- Daily activity for scored repos, for per-repo trend lines.
{{ config(location=layer_location('gold')) }}

select
    e.repo_id,
    e.event_date,
    count(*) as human_events,
    count(*) filter (where e.event_type = 'WatchEvent') as stars,
    count(*) filter (where e.event_type = 'ForkEvent') as forks,
    count(*) filter (where e.event_type = 'PullRequestEvent' and e.action = 'opened') as prs_opened,
    count(*) filter (where e.event_type = 'IssuesEvent' and e.action = 'opened') as issues_opened
from {{ ref('events') }} e
inner join {{ ref('gold_repo_scores') }} s using (repo_id)
where not e.is_bot
group by e.repo_id, e.event_date
