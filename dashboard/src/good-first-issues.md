---
title: Good first issues
---

```js
import {hours, integer, percent, tile} from "./components.js";
const meta = await FileAttachment("data/meta.json").json();
const issues = await FileAttachment("data/open_good_first_issues.json").json();
const n = meta.network;
const kinds = [
  {how: "Comment", count: n.gfi_pickups_by_comment},
  {how: "Assignment", count: n.gfi_pickups_by_assignment},
  {how: "Linked PR", count: n.gfi_pickups_by_linked_pr}
];
const languages = ["All languages", ...d3.sort(new Set(issues.map((d) => d.language ?? "Unknown")))];
```

# Do good first issues get picked up?

An issue counts when its labels map to a good first issue in the seed file, in any spelling.
A pickup is a comment, an assignment, or a PR whose branch names the issue, from someone who is
neither its author nor a maintainer.

<div class="tiles">
  ${tile("Seen in the window", integer(n.good_first_issues_seen), `${integer(n.repos_with_good_first_issues)} repositories`)}
  ${tile("Still open", integer(n.open_good_first_issues), "at last observation")}
  ${tile("Observed pickups", integer(n.gfi_pickups), `${percent(n.gfi_pickup_share)} of ${integer(n.gfi_measurable)} labelled in the window`)}
  ${tile("Median time to pickup", hours(n.gfi_pickup_median_h), `p90 ${hours(n.gfi_pickup_p90_h)}`)}
</div>

<p class="caveat">
Labelling time comes from a captured event for ${integer(n.gfi_with_labeled_event)} of these issues.
The rest use the issue's creation time, which can only lengthen the measured pickup. Pickup time
is only measured for issues labelled inside the window.
</p>

## How pickups happen

```js
Plot.plot({
  marginLeft: 90,
  height: 150,
  x: {label: "Observed pickups", grid: true},
  y: {label: null, domain: kinds.map((d) => d.how)},
  marks: [
    Plot.barX(kinds, {
      x: "count",
      y: "how",
      fill: "var(--series-1)",
      rx: 2,
      tip: true,
      title: (d) => `${d.how}: ${integer(d.count)}`
    }),
    Plot.ruleX([0], {stroke: "var(--recessive)"})
  ]
})
```

## Open issues to start on

Ranked repositories come first. State is as last observed, so check the issue before starting.

```js
const language = view(Inputs.select(languages, {label: "Language"}));
```

```js
Inputs.table(
  issues.filter((d) => language === "All languages" || (d.language ?? "Unknown") === language),
  {
    columns: ["repo_name", "title", "language", "comment_count", "created_at"],
    header: {
      repo_name: "Repository",
      title: "Issue",
      language: "Language",
      comment_count: "Comments",
      created_at: "Opened"
    },
    format: {
      title: (title, index, rows) => html`<a href=${rows[index].url} target="_blank">${title}</a>`,
      language: (value) => value ?? "Unknown",
      created_at: (value) => value.slice(0, 10)
    },
    width: {title: 340, repo_name: 200},
    rows: 16,
    select: false
  }
)
```
