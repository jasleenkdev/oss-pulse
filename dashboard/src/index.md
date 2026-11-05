---
title: Overview
---

```js
import {hours, integer, percent, tile} from "./components.js";
const meta = await FileAttachment("data/meta.json").json();
const bots = await FileAttachment("data/bots.json").json();
const repos = await FileAttachment("data/repos.json").json();
const {pipeline: p, network: n} = meta;
const day = (value) => value.slice(0, 10);
const lastDay = new Date(new Date(p.window_end).getTime() - 864e5).toISOString().slice(0, 10);
```

# How newcomer-friendly is open source?

OSS Pulse reads public GitHub activity from GH Archive and measures how projects treat people
from outside: how fast maintainers respond, how often outside pull requests land, and whether
good first issues get picked up.

<p class="caveat">
Window: ${day(p.window_start)} to ${lastDay}. The feed now carries only about
<strong>${percent(p.estimated_capture_rate)}</strong> of GitHub events, so counts are a sample and
per-repo figures rest on small numbers. Sample sizes are shown next to each metric.
</p>

<div class="tiles">
  ${tile("Events processed", integer(p.rows_read), `${integer(p.rows_kept)} relevant`)}
  ${tile("Repositories seen", integer(p.repos_seen), `${integer(p.repos_with_human_activity)} with human activity`)}
  ${tile("Repositories ranked", integer(p.repos_scored), "passed the evidence gate")}
  ${tile("Bot share of events", percent(p.bot_share), `${integer(p.bot_events)} events`)}
</div>

<div class="tiles">
  ${tile("External PR merge rate", percent(n.external_pr_merge_rate), `${integer(n.external_prs_merged + n.external_prs_closed_unmerged)} resolved PRs`)}
  ${tile("Median time to merge", hours(n.time_to_merge_median_h), `${integer(n.time_to_merge_samples)} PRs, mostly same-repo`)}
  ${tile("Open good first issues", integer(n.open_good_first_issues), `in ${integer(n.repos_with_good_first_issues)} repositories`)}
  ${tile("Friendliest repository", html`<span style="font-size:1.15rem">${repos[0]?.repo_name ?? "n/a"}</span>`, repos[0] ? `score ${repos[0].score}` : "")}
</div>

## Who is doing the work

```js
Plot.plot({
  marginLeft: 210,
  height: 34 + bots.accounts.length * 24,
  x: {label: "Events in the window", grid: true},
  y: {label: null},
  marks: [
    Plot.barX(bots.accounts, {
      x: "total_events",
      y: "login",
      sort: {y: "-x"},
      fill: "var(--series-1)",
      rx: 2,
      tip: true,
      title: (d) => `${d.login}\n${integer(d.total_events)} events`
    }),
    Plot.ruleX([0], {stroke: "var(--recessive)"})
  ]
})
```

Automation accounts ranked by events. Bots stay in silver, because their comments reveal PR
metadata, and are filtered out of every metric.
