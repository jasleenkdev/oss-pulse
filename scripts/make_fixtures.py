"""Generate the synthetic GH Archive fixtures used by pytest and CI.

Events follow the payload shapes seen in November 2026, plus one repository with the older
shape that still has author_association. Nothing here comes from real accounts. Output is
deterministic, so the committed .json.gz files only change when this script does.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "gharchive"
DAYS = [datetime(2026, 3, day) for day in (2, 3, 4, 5)]

WIDGETS = (101, "acme/widgets")
ENGINE = (102, "acme/engine")
NOTES = (103, "solo-dev/notes")
OLDSTACK = (104, "legacy/oldstack")
LINTER = (105, "bright/linter")
SERVER = (106, "bright/server")

USERS = {
    login: index
    for index, login in enumerate(
        [
            "maya",
            "omar",
            "ines",
            "tao",
            "priya",
            "sam",
            "solo-dev",
            "lena",
            "ext-ana",
            "ext-ben",
            "ext-cleo",
            "ext-dan",
            "ext-eve",
            "ext-finn",
            "dependabot[bot]",
            "vercel[bot]",
            "Copilot",
            "ghost",
        ],
        start=1,
    )
}
EXTERNALS = ["ext-ana", "ext-ben", "ext-cleo", "ext-dan", "ext-eve", "ext-finn"]


class Builder:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.next_id = 90_000_000
        self.next_item = 5_000

    def item_id(self) -> int:
        self.next_item += 1
        return self.next_item

    def add(self, kind: str, at: datetime, actor: str, repo: tuple, payload: dict) -> dict:
        self.next_id += 7
        event = {
            "id": str(self.next_id),
            "type": kind,
            "actor": {"id": USERS[actor], "login": actor, "url": "https://example.invalid"},
            "repo": {"id": repo[0], "name": repo[1]},
            "payload": payload,
            "public": True,
            "created_at": stamp(at),
        }
        if repo[1].startswith("acme/"):
            event["org"] = {"id": 900, "login": "acme"}
        self.events.append(event)
        return event


def stamp(at: datetime | None) -> str | None:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ") if at else None


def user(login: str, kind: str = "User") -> dict:
    return {"id": USERS[login], "login": login, "type": kind}


def issue_object(
    repo, number, item_id, author, created, labels=(), state="open", closed=None, comments=0,
    pull_request=None, title=None, association=None,
) -> dict:
    body = {
        "id": item_id,
        "number": number,
        "title": title or f"Item {number} in {repo[1]}",
        "html_url": f"https://github.com/{repo[1]}/issues/{number}",
        "user": user(author),
        "labels": [{"name": label} for label in labels],
        "state": state,
        "comments": comments,
        "created_at": stamp(created),
        "closed_at": stamp(closed),
    }
    if pull_request is not None:
        body["pull_request"] = pull_request
    if association:
        body["author_association"] = association
    return body


def pr_stub(repo, number, pr_id, head_repo_id, ref) -> dict:
    return {
        "id": pr_id,
        "number": number,
        "head": {"ref": ref, "repo": {"id": head_repo_id}},
        "base": {"ref": "main", "repo": {"id": repo[0]}},
    }


def pr_snapshot(repo, number, merged=None) -> dict:
    return {
        "url": f"https://api.github.com/repos/{repo[1]}/pulls/{number}",
        "merged_at": stamp(merged),
    }


def comment_object(comment_id, login, created, association=None, kind="User") -> dict:
    body = {"id": comment_id, "user": user(login, kind), "created_at": stamp(created)}
    if association:
        body["author_association"] = association
    return body


def active_repo(b: Builder, repo: tuple, maintainers: list[str], friendly: bool) -> None:
    """A repo with maintainers, outside contributors, issues, reviews and good first issues."""
    response_delay = timedelta(hours=2 if friendly else 7)
    for day_index, day in enumerate(DAYS):
        maintainer = maintainers[day_index % len(maintainers)]
        other = maintainers[(day_index + 1) % len(maintainers)]
        base = day + timedelta(hours=9)

        # Maintainer PR from a branch in the repo: proves push access.
        number = 100 + day_index * 10
        pr_id = b.item_id()
        stub = pr_stub(repo, number, pr_id, repo[0], f"feature/{day_index}")
        b.add("PullRequestEvent", base, maintainer, repo,
              {"action": "opened", "number": number, "pull_request": stub})
        b.add("PullRequestEvent", base + timedelta(hours=3), maintainer, repo,
              {"action": "merged", "number": number, "pull_request": stub})

        # Outside contributor PR from a fork, with a maintainer response and a bot comment.
        contributor = EXTERNALS[day_index % len(EXTERNALS)]
        number += 1
        opened = base + timedelta(minutes=30)
        pr_id = b.item_id()
        stub = pr_stub(repo, number, pr_id, 7000 + day_index, f"patch-{day_index}")
        snapshot_item = b.item_id()
        b.add("PullRequestEvent", opened, contributor, repo,
              {"action": "opened", "number": number, "pull_request": stub})
        b.add("IssueCommentEvent", opened + timedelta(minutes=2), "vercel[bot]", repo, {
            "action": "created",
            "issue": issue_object(repo, number, snapshot_item, contributor, opened, comments=1,
                                  pull_request=pr_snapshot(repo, number)),
            "comment": comment_object(b.item_id(), "vercel[bot]", opened + timedelta(minutes=2),
                                      kind="Bot"),
        })
        reviewed = opened + response_delay
        b.add("PullRequestReviewEvent", reviewed, maintainer, repo, {
            "action": "created",
            "pull_request": stub,
            "review": {"id": b.item_id(), "user": user(maintainer), "state": "approved",
                       "submitted_at": stamp(reviewed)},
        })
        finish = reviewed + timedelta(hours=1)
        if friendly or day_index == 0:
            # The actor on a merged event is the PR author, as in the live feed.
            b.add("PullRequestEvent", finish, contributor, repo,
                  {"action": "merged", "number": number, "pull_request": stub})
        else:
            b.add("PullRequestEvent", finish, maintainer, repo,
                  {"action": "closed", "number": number, "pull_request": stub})

        # Outside issue with triage and a first comment.
        number += 1
        reporter = EXTERNALS[(day_index + 2) % len(EXTERNALS)]
        issue_id = b.item_id()
        issue_at = base + timedelta(minutes=45)
        b.add("IssuesEvent", issue_at, reporter, repo, {
            "action": "opened",
            "issue": issue_object(repo, number, issue_id, reporter, issue_at, labels=["bug"]),
        })
        labelled = issue_at + response_delay
        b.add("IssuesEvent", labelled, other, repo, {
            "action": "labeled",
            "label": {"name": "needs-triage"},
            "issue": issue_object(repo, number, issue_id, reporter, issue_at,
                                  labels=["bug", "needs-triage"]),
        })
        answered = labelled + timedelta(minutes=20)
        b.add("IssueCommentEvent", answered, maintainer, repo, {
            "action": "created",
            "issue": issue_object(repo, number, issue_id, reporter, issue_at,
                                  labels=["bug", "needs-triage"], comments=1),
            "comment": comment_object(b.item_id(), maintainer, answered),
        })
        if friendly:
            closed = answered + timedelta(hours=1)
            b.add("IssuesEvent", closed, maintainer, repo, {
                "action": "closed",
                "issue": issue_object(repo, number, issue_id, reporter, issue_at, labels=["bug"],
                                      state="closed", closed=closed, comments=1),
            })

        # Good first issue from a maintainer. Friendly repos get a contributor comment.
        number += 1
        gfi_id = b.item_id()
        gfi_labels = ["Good First Issue "] if day_index % 2 else ["good-first-issue"]
        gfi_at = base + timedelta(hours=1)
        b.add("IssuesEvent", gfi_at, maintainer, repo, {
            "action": "opened",
            "issue": issue_object(repo, number, gfi_id, maintainer, gfi_at, labels=gfi_labels,
                                  title=f"Small task {number}"),
        })
        tagged = gfi_at + timedelta(minutes=10)
        b.add("IssuesEvent", tagged, maintainer, repo, {
            "action": "labeled",
            "label": {"name": gfi_labels[0]},
            "issue": issue_object(repo, number, gfi_id, maintainer, gfi_at, labels=gfi_labels,
                                  title=f"Small task {number}"),
        })
        if friendly:
            picked = tagged + timedelta(hours=4)
            helper = EXTERNALS[(day_index + 3) % len(EXTERNALS)]
            b.add("IssueCommentEvent", picked, helper, repo, {
                "action": "created",
                "issue": issue_object(repo, number, gfi_id, maintainer, gfi_at, labels=gfi_labels,
                                      comments=1, title=f"Small task {number}"),
                "comment": comment_object(b.item_id(), helper, picked),
            })

        # Stars, forks, and bot noise that must not count as human activity.
        b.add("WatchEvent", base + timedelta(hours=2), EXTERNALS[day_index], repo,
              {"action": "started"})
        b.add("ForkEvent", base + timedelta(hours=2, minutes=5), EXTERNALS[-1 - day_index], repo,
              {"action": "forked"})
        dependency_pr = 900 + day_index
        bot_stub = pr_stub(repo, dependency_pr, b.item_id(), repo[0], f"dependabot/npm/{day_index}")
        b.add("PullRequestEvent", base + timedelta(hours=4), "dependabot[bot]", repo,
              {"action": "opened", "number": dependency_pr, "pull_request": bot_stub})
        b.add("PullRequestEvent", base + timedelta(hours=5), "dependabot[bot]", repo,
              {"action": "merged", "number": dependency_pr, "pull_request": bot_stub})
        copilot_pr = 950 + day_index
        copilot_stub = pr_stub(repo, copilot_pr, b.item_id(), repo[0], f"copilot/fix-{day_index}")
        b.add("PullRequestEvent", base + timedelta(hours=4, minutes=30), "Copilot", repo,
              {"action": "opened", "number": copilot_pr, "pull_request": copilot_stub})


def solo_repo(b: Builder) -> None:
    """One person working alone. Busy, but nothing to say about newcomers."""
    for day_index, day in enumerate(DAYS):
        for offset in range(3):
            number = 10 + day_index * 3 + offset
            stub = pr_stub(NOTES, number, b.item_id(), NOTES[0], f"work-{number}")
            at = day + timedelta(hours=10, minutes=offset * 10)
            b.add("PullRequestEvent", at, "solo-dev", NOTES,
                  {"action": "opened", "number": number, "pull_request": stub})
            b.add("PullRequestEvent", at + timedelta(minutes=2), "solo-dev", NOTES,
                  {"action": "merged", "number": number, "pull_request": stub})


def legacy_pr(repo, number, pr_id, author, association, created, merged, head_repo) -> dict:
    return {
        "id": pr_id,
        "number": number,
        "user": user(author),
        "author_association": association,
        "created_at": stamp(created),
        "merged_at": stamp(merged),
        "merged": merged is not None,
        "head": {"ref": f"topic-{number}", "repo": {"id": head_repo}},
        "base": {"ref": "main", "repo": {"id": repo[0]}},
    }


def legacy_repo(b: Builder) -> None:
    """The older payload shape: merges are closed + merged, with author_association."""
    repo = OLDSTACK
    for day_index, day in enumerate(DAYS):
        base = day + timedelta(hours=11)
        contributor = EXTERNALS[(day_index + 1) % len(EXTERNALS)]
        number = 300 + day_index * 3
        created = base
        merged = base + timedelta(hours=6)
        pr_id = b.item_id()
        association = "FIRST_TIME_CONTRIBUTOR" if day_index == 0 else "CONTRIBUTOR"
        b.add("PullRequestEvent", created, contributor, repo, {
            "action": "opened", "number": number,
            "pull_request": legacy_pr(repo, number, pr_id, contributor, association, created,
                                      None, 8000 + day_index),
        })
        b.add("IssueCommentEvent", base + timedelta(hours=2), "lena", repo, {
            "action": "created",
            "issue": issue_object(repo, number, b.item_id(), contributor, created, comments=1,
                                  pull_request=pr_snapshot(repo, number), association=association),
            "comment": comment_object(b.item_id(), "lena", base + timedelta(hours=2),
                                      association="MEMBER"),
        })
        # In the older shape the actor on a merge is the merger.
        b.add("PullRequestEvent", merged, "lena", repo, {
            "action": "closed", "number": number,
            "pull_request": legacy_pr(repo, number, pr_id, contributor, association, created,
                                      merged, 8000 + day_index),
        })
        number += 1
        issue_id = b.item_id()
        reporter = EXTERNALS[(day_index + 4) % len(EXTERNALS)]
        issue_at = base + timedelta(minutes=30)
        b.add("IssuesEvent", issue_at, reporter, repo, {
            "action": "opened",
            "issue": issue_object(repo, number, issue_id, reporter, issue_at, association="NONE"),
        })
        replied = issue_at + timedelta(hours=3)
        b.add("IssueCommentEvent", replied, "lena", repo, {
            "action": "created",
            "issue": issue_object(repo, number, issue_id, reporter, issue_at, comments=1,
                                  association="NONE"),
            "comment": comment_object(b.item_id(), "lena", replied, association="OWNER"),
        })
        b.add("WatchEvent", base + timedelta(hours=1), EXTERNALS[day_index], repo,
              {"action": "started"})


def edge_cases(b: Builder) -> list[str]:
    """Rows that exercise cleaning. Returns raw lines to add to the 2026-03-03 10:00 file."""
    # Created after it closed, as GitHub reported around the DST change.
    number, issue_id = 700, b.item_id()
    closed = DAYS[2] + timedelta(hours=9, minutes=5)
    created = DAYS[2] + timedelta(hours=9, minutes=50)
    b.add("IssuesEvent", closed, "maya", WIDGETS, {
        "action": "closed",
        "issue": issue_object(WIDGETS, number, issue_id, "ghost", created, state="closed",
                              closed=closed),
    })
    pushed = b.add("WatchEvent", DAYS[1] + timedelta(hours=10), "ext-ana", WIDGETS,
                   {"action": "started"})
    duplicate = json.dumps(pushed)
    filtered = {**pushed, "id": "80000001", "type": "PushEvent", "payload": {}}
    no_repo = {**pushed, "id": "80000002"}
    no_repo.pop("repo")
    return [
        duplicate,
        json.dumps(filtered),
        "{not valid json",
        json.dumps(no_repo),
        json.dumps({**pushed, "id": "80000003", "created_at": "yesterday"}),
        "",
    ]


def write(path: Path, lines: list[str]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as handle:
            handle.write(("\n".join(lines) + "\n").encode("utf-8"))


def main() -> None:
    builder = Builder()
    active_repo(builder, WIDGETS, ["maya", "omar"], friendly=True)
    active_repo(builder, ENGINE, ["ines", "tao"], friendly=False)
    active_repo(builder, LINTER, ["priya"], friendly=True)
    active_repo(builder, SERVER, ["sam", "priya"], friendly=False)
    solo_repo(builder)
    legacy_repo(builder)
    extra_lines = edge_cases(builder)

    by_hour: dict[datetime, list[str]] = defaultdict(list)
    for event in builder.events:
        moment = datetime.strptime(event["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        by_hour[moment.replace(minute=0, second=0)].append(json.dumps(event))
    by_hour[DAYS[1] + timedelta(hours=10)].extend(extra_lines)

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json.gz"):
        stale.unlink()
    for hour, lines in sorted(by_hour.items()):
        write(OUT / f"{hour:%Y-%m-%d}-{hour.hour}.json.gz", lines)
    print(f"wrote {sum(map(len, by_hour.values()))} lines to {len(by_hour)} files in {OUT}")


if __name__ == "__main__":
    main()
