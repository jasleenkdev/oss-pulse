# Metric definitions

All metrics cover a rolling window of complete UTC days. Bots are excluded unless stated. Models
are in `dbt/models/gold`, and thresholds are in `dbt/seeds/score_thresholds.csv`.

## What the feed provides

Since late 2025 events have lost most PR fields and `author_association`, and only about 1.2% of
events are captured. Three consequences shape every definition:

1. **Pairing events rarely works.** An `opened` and a `merged` event for the same PR both appear
   about as often as independent capture predicts, which is rarely. Metrics are built from single
   events where possible.
2. **A missed event looks like nothing happened.** Rates of "had a response" are floors, and
   durations from first observed actions are upper bounds.
3. **Fallbacks are measured, not assumed.** `scripts/validate_fallbacks.py` scores them against the
   REST API, which still returns the removed fields.

## People

| Term | Definition |
| --- | --- |
| Bot | Login ends in `[bot]`, or appears in `dbt/seeds/known_bots.csv`. |
| Maintainer | `author_association` of OWNER, MEMBER or COLLABORATOR when present. Otherwise the repo owner, the author of a PR from a same-repo branch, or someone who labelled, unlabelled or closed another person's issue. |
| External contributor | A human who engaged with a repo and is not a maintainer. Stars and forks don't count. |
| External PR | Fork PR from a non-maintainer. Same-repo branches need push access and are never external. Unknown fork status is not external. |
| First-time contributor (proxy) | External, and no earlier observed activity from this person in the repo during the window. `FIRST_TIME_CONTRIBUTOR` and `FIRST_TIMER` win when present. |

Merge events are not maintainer evidence, because the actor on a `merged` event is the PR author.
`assigned` is excluded because REST showed its actor is less reliable than `labeled` and `closed`.

## Repository metrics

| Metric | Definition | Sample size column |
| --- | --- | --- |
| `issues_opened` | Non-bot issues with `created_at` in the window, from any event that mentions them | none |
| `issues_closed` | Non-bot issues with `closed_at` in the window | none |
| `issue_first_response_median_h`, `_p90_h` | Hours from creation to first observed maintainer comment, label, assignment or close, on issues from non-maintainers created in the window | `issue_responses` |
| `pr_first_response_median_h`, `_p90_h` | Hours from creation to first observed maintainer comment or review, or the merge, on external PRs created in the window | `pr_responses` |
| `pr_merge_rate` | merged / (merged + closed unmerged), human-authored PRs | `prs_merged`, `prs_closed_unmerged` |
| `external_pr_merge_rate` | The same for external PRs | `external_prs_merged`, `external_prs_closed_unmerged` |
| `first_time_pr_merge_rate` | The same for first-time contributors (proxy) | `first_time_prs_merged`, `first_time_prs_closed_unmerged` |
| `time_to_merge_median_h` | Hours from creation to merge for human PRs merged in the window, however old | `time_to_merge_samples` |
| `open_good_first_issues` | Good first issues open at last observation | none |
| `gfi_pickup_median_h` | Hours from labelling to first contributor action, for issues labelled in the window | `gfi_pickups` |
| `stars_gained`, `forks_gained` | Observed WatchEvent and ForkEvent. About 1.2% of the true count. | none |
| `active_days` | Days with a non-bot event | none |
| `distinct_maintainers_acting` | Maintainers with an event in the window. A bus factor proxy. | none |

## Newcomer friendliness score

Six components, each a percentile from 0 to 1 among eligible repos, where higher is friendlier:

| Component | Baseline weight | Source |
| --- | --- | --- |
| `issue_response` | 0.20 | Inverted percentile of the median issue response |
| `pr_response` | 0.20 | Inverted percentile of the median PR response |
| `external_merge_rate` | 0.25 | Percentile of the shrunk external merge rate |
| `time_to_merge` | 0.10 | Inverted percentile of the median time to merge |
| `gfi_supply` | 0.10 | Percentile of open good first issues, missing when there are none |
| `activity_health` | 0.15 | Mean percentile of active days and acting maintainers |

**Why percentiles:** they are unit-free, and a single extreme repo cannot stretch the scale.

**Missing evidence:** weights are renormalised over the components a repo has evidence for, so
absence of evidence is not treated as a bad score.

**Shrinkage:** external merge rates are pulled toward the global rate with 5 pseudo-PRs, so one
lucky merge can't outrank fifty.

**Eligibility:** at least 15 human events, 3 external contributors, 3 active days, 5 evidence points
(responses plus resolved external PRs) and 3 components, and not archived.

**Sensitivity:** `gold_score_scenarios` ranks all repos under six weightings from
`dbt/seeds/score_weights.csv`. `gold_score_sensitivity` reports Spearman correlation with the
baseline, top-N overlap and median rank shift. `best_rank` and `worst_rank` show each repo's range.

## Edge cases

| Case | Handling |
| --- | --- |
| Bots | Kept in silver, because their comments carry PR metadata, and removed from gold. Automation registered as an ordinary user is caught by the seed and by the 60-second rule. |
| Bot comments on PRs | Never count as a response, but can supply author and timestamps. |
| Self-merges | Can't be detected, because the merger is not in the feed. External PRs exclude most of them, since a fork PR author without push access can't merge. |
| Deleted users | GitHub reassigns them to `ghost`, which is treated as an ordinary non-maintainer. |
| Events outside the window | Bronze can hold more days, and staging filters to the window. Items created earlier are excluded from response time so that an unobserved earlier answer can't count as first. They still count for time to merge, or long-lived PRs would disappear. |
| Unanswered items | Excluded from the medians, so medians describe answered items. Read them with the observed share. |
| Reopened PRs | A close before a later `reopened` is ignored. A merge always wins. |
| Older payloads | `closed` with `merged: true` is normalised to `merged`, and the payload author is used, because there the actor is the merger. |
| Actions under 60 seconds | Skipped, and the next action counts. |
| Timestamps around the DST change | `created_at` is capped at the first observed event and the close, and the row is flagged `has_timestamp_anomaly`. Flagged rows are left out of time to merge. |
| Renamed repos | Keyed by `repo_id`. The latest observed name wins. |
| Transferred issues | Treated as new issues in the destination, since `issue_id` changes. |
| Old good first issues | Pickup time needs a label time inside the window, or a comment today on a years-old issue would count as a years-long pickup. |
| Linked PRs | PR bodies are gone, so links come from branch names such as `fix-123`. They are rare and imprecise. |
| Good first issue state | Only as last observed. A closure in a missed event leaves the issue open here. |
