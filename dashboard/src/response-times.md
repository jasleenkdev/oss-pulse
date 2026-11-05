---
title: Response times
---

```js
import {hours, integer, percent, tile} from "./components.js";
const distribution = await FileAttachment("data/response_distribution.json").json();
const summary = await FileAttachment("data/response_summary.json").json();
const repos = await FileAttachment("data/repos.json").json();
const issue = summary.find((d) => d.kind === "issue");
const pr = summary.find((d) => d.kind === "pr");
const names = {issue: "Issues", pr: "Pull requests"};
```

# How long outsiders wait for a maintainer

Time from an issue or fork PR being opened by a non-maintainer to the first maintainer action
seen in the feed. Most responses are not captured, so these are upper bounds.

<div class="tiles">
  ${tile("Issues: median", hours(issue.median_h), `${integer(issue.items_with_response)} responses`)}
  ${tile("Issues: p90", hours(issue.p90_h))}
  ${tile("Pull requests: median", hours(pr.median_h), `${integer(pr.items_with_response)} responses`)}
  ${tile("Pull requests: p90", hours(pr.p90_h))}
</div>

## Distribution

```js
Plot.plot({
  height: 300,
  marginLeft: 50,
  fx: {label: null, tickFormat: (kind) => names[kind]},
  x: {
    label: null,
    domain: ["under 1h", "1-6h", "6-24h", "1-3d", "3d+"],
    padding: 0.2
  },
  y: {label: "Share of responses", percent: true, grid: true},
  marks: [
    Plot.barY(
      distribution,
      Plot.normalizeY("sum", {
        fx: "kind",
        z: "kind",
        x: "bucket",
        y: "responses",
        fill: "var(--series-1)",
        rx: 2,
        tip: true,
        title: (d) => `${names[d.kind]}, ${d.bucket}\n${integer(d.responses)} responses`
      })
    ),
    Plot.ruleY([0], {stroke: "var(--recessive)"})
  ]
})
```

## The first comment, exactly

When an event's comment counter says it was the first comment on the thread, the time is exact
even though most events are missing. That subset is smaller but free of sampling error.

```js
Inputs.table(summary, {
  columns: ["kind", "items", "items_with_response", "observed_response_share", "median_h", "exact_items", "exact_median_h"],
  header: {
    kind: "Kind",
    items: "Items raised",
    items_with_response: "With a response",
    observed_response_share: "Share observed",
    median_h: "Median",
    exact_items: "Exact sample",
    exact_median_h: "Exact median"
  },
  format: {
    kind: (kind) => names[kind],
    observed_response_share: (value) => percent(value),
    median_h: hours,
    exact_median_h: hours
  },
  select: false
})
```

A response that never reached the feed looks like no response, so "share observed" is a floor.

## Slowest and fastest ranked repositories

```js
const withIssues = d3.sort(
  repos.filter((d) => d.issue_first_response_median_h != null && d.issue_responses >= 3),
  (d) => d.issue_first_response_median_h
);
display(
  Inputs.table(withIssues, {
    columns: ["repo_name", "issue_first_response_median_h", "issue_responses"],
    header: {
      repo_name: "Repository",
      issue_first_response_median_h: "Median issue response",
      issue_responses: "Responses"
    },
    format: {issue_first_response_median_h: hours},
    rows: 12,
    select: false
  })
);
```
