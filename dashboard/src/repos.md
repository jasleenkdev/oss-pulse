---
title: Friendliest repos
---

```js
import {hours, percent} from "./components.js";
const repos = await FileAttachment("data/repos.json").json();
const sensitivity = await FileAttachment("data/sensitivity.json").json();
const meta = await FileAttachment("data/meta.json").json();
const withheld = meta.suppressed_rows.repos;
const languages = ["All languages", ...d3.sort(new Set(repos.map((d) => d.language ?? "Unknown")))];
```

# Most newcomer-friendly repositories

The score combines response speed, outside merge rate, time to merge, good first issue supply and
activity health, as percentiles among ranked repositories. Weights live in a seed file.
${withheld > 0 ? `${withheld} of the ${meta.pipeline.repos_scored} ranked repositories are withheld from this public page by a text filter, so rank numbers can skip. They remain in the FirstPR export.` : ""}

```js
const language = view(Inputs.select(languages, {label: "Language"}));
const query = view(Inputs.text({label: "Search", placeholder: "repository name"}));
```

```js
const shown = repos.filter(
  (d) =>
    (language === "All languages" || (d.language ?? "Unknown") === language) &&
    d.repo_name.toLowerCase().includes(query.toLowerCase())
);
```

```js
Plot.plot({
  marginLeft: 230,
  height: 40 + Math.min(shown.length, 20) * 26,
  x: {domain: [0, 100], label: "Score", grid: true},
  y: {label: null},
  marks: [
    Plot.barX(shown.slice(0, 20), {
      x: "score",
      y: "repo_name",
      sort: {y: "-x"},
      fill: "var(--series-1)",
      rx: 2,
      tip: true,
      title: (d) =>
        `${d.repo_name}\nScore ${d.score}, rank ${d.score_rank}\nRank range across weightings: ${d.best_rank} to ${d.worst_rank}\n${d.components_present} of 6 components`
    }),
    Plot.ruleX([0], {stroke: "var(--recessive)"})
  ]
})
```

Best and Worst are the rank range across weightings. Issue and PR are median first responses,
Merge is the outside PR merge rate, and GFIs are open good first issues. Blank means no evidence.

```js
Inputs.table(shown, {
  columns: [
    "score_rank",
    "repo_name",
    "language",
    "score",
    "best_rank",
    "worst_rank",
    "issue_first_response_median_h",
    "pr_first_response_median_h",
    "external_pr_merge_rate",
    "open_good_first_issues"
  ],
  header: {
    score_rank: "Rank",
    repo_name: "Repository",
    language: "Lang",
    score: "Score",
    best_rank: "Best",
    worst_rank: "Worst",
    issue_first_response_median_h: "Issue",
    pr_first_response_median_h: "PR",
    external_pr_merge_rate: "Merge",
    open_good_first_issues: "GFIs"
  },
  format: {
    repo_name: (name) => html`<a href=${`https://github.com/${name}`} target="_blank">${name}</a>`,
    language: (value) => value ?? "Unknown",
    issue_first_response_median_h: hours,
    pr_first_response_median_h: hours,
    external_pr_merge_rate: (value) => percent(value, 0)
  },
  rows: 20,
  width: {repo_name: 250, language: 90}
})
```

## How much the ranking depends on the weights

Each row re-ranks every repository under different weights. A correlation near 1 means the order
barely moves. Compare the best and worst rank columns above for any single repository.

```js
Inputs.table(sensitivity, {
  columns: ["scenario", "spearman_with_baseline", "top10_overlap", "top25_overlap", "median_rank_shift"],
  header: {
    scenario: "Weighting",
    spearman_with_baseline: "Rank correlation",
    top10_overlap: "Shared top 10",
    top25_overlap: "Shared top 25",
    median_rank_shift: "Median rank shift"
  },
  select: false
})
```
