# Decisions

Choices made while building OSS Pulse, in the order they came up. Every number here was
measured during the build.

## Step 0: location and environment

- **Location:** `~/oss-pulse`. `git -C ~ rev-parse --show-toplevel` found no parent repository.
- **Disk:** 32 GB free at the start, above the 30 GB threshold, so the window was not shrunk.
  The window needed under 1 GB.
- **Python 3.11 via uv.** The default interpreter on the machine is 3.10.
- **dbt 1.12 and protobuf.** Left alone, the resolver picked dbt 1.7. Forcing a current dbt pins
  protobuf below 7, while the newest `grpcio-health-checking` needs protobuf 7, so that package
  is pinned to 1.76.0 in `pyproject.toml`.
- **GITHUB_TOKEN** was set, so it went to a gitignored `.env` (mode 600) and step 4 runs.

## Step 1: what the feed actually contains

An hour from 2026-11-03 was inspected before any parser was written, then compared with hours
from July 2026 and September 2025.

| Field | Sep 2025 | Nov 2026 |
| --- | --- | --- |
| `author_association` | present on all types | **absent from every event type** |
| PR `user`, `created_at`, `merged_at`, `merged`, `labels` | present | **absent**: `id`, `number`, `head`, `base` only |
| Merge signal | `closed` with `merged: true` | **new action `merged`**; `closed` now means closed unmerged |
| Issue `user`, `labels`, timestamps, `state` | present | present |
| Comment `issue` object, including `pull_request.merged_at` | present | present |
| Review `user`, `state`, `submitted_at` | present | present |
| `labeled`, `assigned` actions | not in feed | **present** |
| PushEvent | about 65% of volume | absent in most hours |
| Hourly size | about 100 MB | about 4 MB |

- **The feed is a sparse sample.** Comment counters show about 1.2% of events are captured over
  the 30-day window, and 1.4% over the first 7 days
  (`estimated_capture_rate` in `gold_pipeline_summary`). Only 1,261 PRs have both their `opened`
  and `merged` events, against 116,652 opened and 94,877 merged, which is what independent
  capture at that rate predicts.
- **Volume is unstable.** Hour sizes went from about 21 MB in July to 60-90 MB for three days in
  September and 3-6 MB in November. July's bigger files were mostly pushes, with fewer PR events
  than November (314 against 1,300-1,900 in the sampled hours).
- **Window:** first built on 2026-10-29 to 2026-11-04, the most recent 7 complete days, then
  extended to 30 days. See "Filter removal and the 30-day window".
- **Payload strings are stored with ASCII escaping** so lone surrogates in user text stay
  representable in Parquet.
- **Bronze has no ingestion timestamp.** It would stop a re-run from being byte-for-byte
  equivalent, so that lives in the audit table instead.
- **A 404 keeps existing data.** A transient upstream gap must never delete a good partition.

## Step 2: silver

- **The actor on a `merged` event is the PR author, not the merger.** REST ground truth for 97
  sampled events: actor equals the author in 96, and in 36 of those somebody else merged it. So
  "whoever merged is a maintainer", the obvious fallback, would label contributors as maintainers.
  In exchange, the author of every merged PR is known without pairing events.
- **PR rows are assembled from all evidence**, since one PR rarely has two captured events. Any
  comment on a PR, even from a bot, gives author, `created_at` and `merged_at`. Bots are therefore
  kept in silver as metadata carriers and filtered in gold.
- **`IssuesEvent` actors are reliable.** REST confirmed labeled 39/39, closed 38/38 and assigned
  34/40. `assigned` is therefore not used as maintainer evidence.
- **GitHub timestamps are wrong around the US DST change.** On 2026-11-01, resource `created_at`
  values from 08:00-08:59 UTC appear as 09:00-09:59. No issue has a `created_at` in the 08:00 hour
  and the 09:00 hour has about double the usual count. REST returns the same values, so issues
  look closed before they were created. Event times for `IssuesEvent`, `WatchEvent` and
  `PullRequestReviewEvent` are correct, but comment and fork events inherit the shift, with none
  in hour 08 and double in hour 09. Silver caps `created_at` at the first observed event and the
  close, and flags the row with `has_timestamp_anomaly`. The cap fixes ordering, not the remaining
  one-hour error on unflagged rows, which is immaterial to medians over the window.
- **Label matching uses a punctuation-free key**, which folds `good-first-issue`,
  `Good First Issue` and emoji prefixes into one seed row. `help wanted`, `easy` and
  `hacktoberfest` are mapped as `adjacent`, not as good first issues.
- **Memory.** One `json_extract` per field re-parses the document each time and hit 12.7 GB. A
  single call with a list of paths parses once. De-duplication ranks ids only, so payloads are
  never buffered. The DuckDB limit is 5 GB, which fits a free runner.

## Step 3: gold

- **Maintainer fallback.** Used when `author_association` is absent: repo owner, author of a PR
  from a same-repo branch (needs push access), or someone who labelled or closed another person's
  issue. `reports/fallback_validation.json` measures these rules against REST.
- **Merge rate uses terminal events only:** merged / (merged + closed unmerged). A cohort rate
  would need `opened` and the outcome for the same PR, which almost never happens. Under
  independent capture the numerator and denominator lose events at the same rate.
- **External requires observed fork status.** Treating unknown as external produced a 3-minute
  median response, because about 94% of PRs are same-repo and solo developers were being counted
  as outsiders. Requiring a fork gave about 5 hours.
- **A fork PR with an unknown author still counts.** `closed` does not identify the author, so
  requiring one would drop most rejections and inflate merge rates.
- **First-time is a proxy:** external, with no earlier observed activity in the repo during the
  window. `FIRST_TIME_CONTRIBUTOR` is gone. Capture is low, so this overstates first-timers.
- **First response is "first observed", so it is an upper bound.** The `is_exact` subset, where
  the comment counter proves it was the first comment, is reported alongside.
- **Time to merge is measured over PRs merged in the window**, including PRs opened earlier.
  Restricting to PRs opened in the window would drop long-lived PRs.
- **Score:** percentile ranks, so a single outlier repo cannot stretch the scale. Weights are
  renormalised over components a repo has evidence for, because absence of evidence is not a bad
  score at this capture rate. Merge rates are shrunk toward the global rate with 5 pseudo-PRs.
- **Minimum activity:** 15 human events, 3 external contributors, 3 active days, 5 evidence
  points and 3 components. Looser gates put repos with 2 contributors at the top of the ranking.

## Step 4: enrichment

- **Runs between silver and gold**, because the archived flag and language feed the score. It reads
  `int_enrichment_candidates`, which puts repos that pass the score's activity and evidence gates
  first, so ranked repos get a language, stars and an archived flag.
- **Calls are sequential.** About 0.6 seconds each, which also stays clear of secondary rate limits.
  The cache lasts 7 days, so rebuilds cost nothing.

## Step 5: quality and validation

- **Fallbacks were scored against REST** (`scripts/validate_fallbacks.py`, about 900 calls). See
  `reports/fallback_validation.json`. The merged actor was the author in 139 of 139 checkable
  events. Maintainer precision is 84.1%, and 28.9% of sampled comments from people not inferred as
  maintainers really were from maintainers, because 1.2% capture misses their evidence.
- **The same-repo-branch rule agrees with REST `author_association` 48% of the time.** The rest
  report `CONTRIBUTOR`, even though a same-repo branch needs push access. Private organisation
  membership shown to a third-party token would explain this, but that was not verified.
- **Event-based merge rates read high.** True outcomes for 207 resolved external PRs give 74.9%,
  against 87.0% from events. Rankings use the event rate. The gap is published.
- **The contract check is plain Python, not dbt model contracts**, so FirstPR can run the same file
  against any Parquet it receives.

## Step 6: orchestration

- **`bronze_audit` and `bronze_rejects` are separate assets** written by one hourly multi-asset,
  so each dbt source has one upstream asset.
- **dbt is split into two asset groups**, silver and gold, so enrichment can sit between them
  without a cycle.
- **Backfills have two paths.** `make backfill` uses threads and is the fast path for a first
  load. Dagster partition backfills use the same `ingest_hour`.
- **Extracts carry third-party text unchanged.** Repo names, issue titles and bot accounts are
  data. An earlier row filter was removed, see "Filter removal and the 30-day window".

## Step 7: dashboard

- **Observable Framework over Evidence.** Pages are Markdown plus JavaScript over static JSON, so
  the site builds without a database connector or the warehouse. Evidence needs a source layer and
  a heavier toolchain for the same result, and the language filter is simple client-side code here.
- **Rendering caught what the build could not.** Screenshots showed a 0-minute median response on
  the top-ranked repo. See below.
- **Automation accounts registered as normal users.** `yugabyte-ci` and `elasticsearchmachine` have
  no `[bot]` suffix and were scoring as instant maintainers. They were added to the seed, and any
  action within 60 seconds of creation no longer counts as a response, which also covers accounts
  no list can enumerate.
- **Good first issue pickup needs a label time inside the window.** Falling back to creation time
  on old issues gave a p90 of 556 days. Restricted to the window, the median was 21 hours at 7 days and is 41 hours at 30.

## Step 8: CI/CD

- **The daily refresh ingests one day, as specified, but metrics need 30.** Partitions are
  carried between runs with `actions/cache`. A second backfill over 30 days is a no-op unless
  the cache was evicted, when it rebuilds the window from source.
- **The `data` branch is an orphan branch of JSON only**, so bot commits never mix with `main`
  history. Pages deploys from the workflow artifact, not from a branch.
- **The refresh does not fail on a partition gap.** Gaps are recorded and surfaced on the health
  page. The contract and dbt tests are what stop a publish.

## Filter removal and the 30-day window

- **The word filter is gone from the extracts.** Third-party repo names, issue titles and bot
  accounts are data, not attribution. The 7 repos, 3 issues and 1 bot account it dropped are back
  on the dashboard and in the extracts, and the withheld-rows notice is removed.
- **The per-account table left the data quality report.** That report is tracked prose under
  `docs/`, which stays inside the wording check, and one bot account name would fail it. Account
  volumes are on the dashboard overview instead.
- **Window is 30 days:** 2026-10-06 to 2026-11-04. Ranked repos went from 83 to 646. The forced
  re-ingest reproduced all 168 existing partitions byte for byte.
- **Creation events arrive in bursts.** `CreateEvent` runs from 0 to about 227,000 a day, and lines
  read from about 81,000 to 2.0 million, while PR, issue and comment events stay within about 2.5
  times. Ranking is not exposed: creation events are 8.2% of human events on ranked repos, and one
  of 647 repos needed them to clear the gate. Daily totals and overall bot share are exposed, so
  the trends page and README say so.
- **Enrichment now follows the evidence gate.** Ordering by activity with a 500 cap left 251 of 647
  ranked repos with a language, and let 2 archived repos rank. Activity proxies reached at most 442
  of 647 within 950 calls. Exact evidence selects 837 repos, so `int_first_responses` and
  `int_pr_facts` moved to staging, ahead of enrichment, and the cap rose to 900, under the Actions
  token's 1,000 calls an hour. Language now covers 636 of 646 ranked repos and stars 644.
- **`refresh.yml` timeout rose to 240 minutes.** A cold 30-day ingest took 73 minutes on 6 workers,
  and the runner has 4. The 30-day build passes under the runner's 4 GB DuckDB cap in 48 seconds.
- **Dagster gets an explicit dbt path.** `make test` calls the virtualenv's pytest without putting
  `dbt` on `PATH`, which failed the orchestration tests in a clean shell.
- **`DAYS` alone does not change the metric window.** It sets what is ingested, and dbt reads
  `window_days`. The README had this wrong and now says to set both.

## Generated data is excluded from the wording check

Verification check 2 scans every tracked file except generated data, which holds third-party text
from the feed:

```sh
git grep -i <word> -- . ':!dashboard/src/data'
```

| Exempted path | Contents |
| --- | --- |
| `dashboard/src/data/` | JSON extracts written by `oss-pulse extracts` |

Checks on file names, commit messages and authors are unchanged, and code, docs and README text
stay inside the scan.
