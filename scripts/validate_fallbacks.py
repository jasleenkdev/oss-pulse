"""Score the feed-only fallbacks against REST ground truth.

The event feed lost author_association, the merged flag and PR authors, but the REST API
still returns them. This samples from silver and gold deterministically, asks REST, and
writes aggregate counts to reports/fallback_validation.json. It costs about 900 API calls.
"""

from __future__ import annotations

import collections
import concurrent.futures
import json
import os
import sys
from pathlib import Path

import duckdb
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("OSS_PULSE_DATA_DIR") or ROOT / "data")
OUTPUT = ROOT / "reports" / "fallback_validation.json"
PRIVILEGED = {"OWNER", "MEMBER", "COLLABORATOR"}
API = "https://api.github.com"


def get(session: requests.Session, path: str) -> dict | list | None:
    response = session.get(f"{API}{path}", timeout=30)
    return response.json() if response.status_code == 200 else None


def in_parallel(function, items: list) -> list:
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(function, items))


def merged_actor_semantics(connection, session) -> dict:
    rows = connection.execute(
        """
        select r.repo_name, p.pr_number, e.actor_login
        from silver_events e
        join stg s using (event_id)
        join repos r on r.repo_id = e.repo_id
        join prs p on p.repo_id = e.repo_id and p.pr_number = s.pr_number
        where e.event_type = 'PullRequestEvent' and e.action = 'merged' and not e.is_bot
        order by hash(e.event_id)
        limit 150
        """
    ).fetchall()

    def check(row):
        repo, number, actor = row
        body = get(session, f"/repos/{repo}/pulls/{number}")
        if not body:
            return "unavailable"
        author = (body.get("user") or {}).get("login")
        merger = (body.get("merged_by") or {}).get("login")
        if actor == author and author != merger:
            return "actor_is_author_not_merger"
        if actor == author:
            return "actor_is_author_and_merger"
        if actor == merger:
            return "actor_is_merger_only"
        return "neither"

    return dict(collections.Counter(in_parallel(check, rows)))


def maintainer_classification(connection, session) -> dict:
    """Compare the maintainer rules with the association REST reports on the same comment."""
    rows = connection.execute(
        """
        with comments as (
            select
                c.comment_id, c.author_login, r.repo_name,
                m.login is not null as inferred_maintainer,
                coalesce(m.is_owner, false) as is_owner,
                coalesce(m.has_push_evidence, false) as has_push,
                coalesce(m.has_triage_evidence, false) as has_triage
            from comments_silver c
            join repos r using (repo_id)
            left join maintainers m on m.repo_id = c.repo_id and m.login = c.author_login
            where not c.author_is_bot
        )
        select * from comments
        qualify row_number() over (
            partition by inferred_maintainer order by hash(comment_id)
        ) <= 300
        """
    ).fetchall()

    def check(row):
        comment_id, _, repo, inferred, owner, push, triage = row
        body = get(session, f"/repos/{repo}/issues/comments/{comment_id}")
        association = body.get("author_association") if body else None
        return inferred, owner, push, triage, association

    results = [row for row in in_parallel(check, rows) if row[4] is not None]
    matrix = collections.Counter()
    by_rule: dict[str, collections.Counter] = {
        "owner_namespace": collections.Counter(),
        "push_branch_pr": collections.Counter(),
        "issue_triage": collections.Counter(),
    }
    associations: collections.Counter = collections.Counter()
    for inferred, owner, push, triage, association in results:
        truth = association in PRIVILEGED
        matrix[(inferred, truth)] += 1
        associations[f"{'inferred' if inferred else 'not_inferred'}:{association}"] += 1
        for name, flag in (
            ("owner_namespace", owner),
            ("push_branch_pr", push and not owner),
            ("issue_triage", triage and not owner and not push),
        ):
            if flag:
                by_rule[name][truth] += 1

    true_positive = matrix[(True, True)]
    false_positive = matrix[(True, False)]
    false_negative = matrix[(False, True)]
    true_negative = matrix[(False, False)]
    return {
        "comments_checked": len(results),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision_of_inferred": round(true_positive / (true_positive + false_positive), 4),
        "maintainer_share_among_not_inferred": round(
            false_negative / (false_negative + true_negative), 4
        ),
        "precision_by_first_matching_rule": {
            name: {
                "checked": counts[True] + counts[False],
                "precision": round(counts[True] / (counts[True] + counts[False]), 4)
                if counts[True] + counts[False]
                else None,
            }
            for name, counts in by_rule.items()
        },
        "association_counts": dict(sorted(associations.items())),
    }


def external_pr_outcomes(connection, session) -> dict:
    """True outcomes for fork PRs opened at least three days before the window ended."""
    rows = connection.execute(
        """
        select repo_name, pr_number
        from prs
        where is_fork
          and not author_is_bot
          and not coalesce(author_is_maintainer, false)
          and author_source = 'opened_event'
          and created_at < (select max(created_at) from silver_events) - interval 3 day
        order by hash(pr_key)
        limit 300
        """
    ).fetchall()

    def check(row):
        repo, number = row
        body = get(session, f"/repos/{repo}/pulls/{number}")
        if not body:
            return None
        if body.get("merged_at"):
            return "merged"
        return "closed_unmerged" if body.get("state") == "closed" else "open"

    outcomes = collections.Counter(row for row in in_parallel(check, rows) if row)
    resolved = outcomes["merged"] + outcomes["closed_unmerged"]
    return {
        "prs_checked": sum(outcomes.values()),
        **dict(outcomes),
        "true_merge_rate_of_resolved": round(outcomes["merged"] / resolved, 4),
        "still_open_share": round(outcomes["open"] / sum(outcomes.values()), 4),
    }


def main() -> int:
    load_dotenv(ROOT / ".env")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required for validation", file=sys.stderr)
        return 1
    session = requests.Session()
    session.headers.update(
        {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    )
    warehouse = duckdb.connect(str(DATA / "warehouse.duckdb"), read_only=True)
    connection = warehouse
    connection.execute(
        f"""
        create temp view silver_events as
            select * from read_parquet('{DATA}/silver/events.parquet');
        create temp view repos as select * from read_parquet('{DATA}/silver/repos.parquet');
        create temp view comments_silver as
            select * from read_parquet('{DATA}/silver/issue_comments.parquet');
        create temp view stg as select event_id, pr_number from staging.stg_events;
        create temp view maintainers as select * from staging.int_maintainers;
        create temp view prs as select * from staging.int_pr_facts;
        """
    )
    report = {
        "method": "Deterministic hash sample of pipeline rows, checked against the REST API.",
        "merged_event_actor": merged_actor_semantics(connection, session),
        "maintainer_inference": maintainer_classification(connection, session),
        "external_pr_true_outcomes": external_pr_outcomes(connection, session),
    }
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
