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

- **The feed is a sparse sample.** Comment counters show about 1.4% of events are captured
  (`estimated_capture_rate` in `gold_pipeline_summary`). Only 1,261 PRs have both their `opened`
  and `merged` events, against 116,652 opened and 94,877 merged, which is what independent
  capture at that rate predicts.
- **Volume is unstable.** Hour sizes went from about 21 MB in July to 60-90 MB for three days in
  September and 3-6 MB in November. July's bigger files were mostly pushes, with fewer PR events
  than November (314 against 1,300-1,900 in the sampled hours).
- **Window:** 2026-10-29 to 2026-11-04, the most recent 7 complete days, unchanged from the brief.
  Per-repo samples are thin at this capture rate. `--days` extends the window if needed.
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
- **GitHub timestamps are wrong around the US DST change.** On 2026-11-01 embedded `created_at`
  values from 08:00-08:59 UTC appear as 09:00-09:59. No issue has a `created_at` in the 08:00 hour
  and the 09:00 hour has about double the usual count. REST returns the same values, so issues
  look closed before they were created. Envelope timestamps are correct. Silver caps `created_at`
  at the first observed event and the close, and flags the row with `has_timestamp_anomaly`.
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
  as outsiders. Requiring a fork gives 5.05 hours.
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
