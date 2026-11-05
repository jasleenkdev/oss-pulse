---
title: Trends
---

```js
import {hours, integer, legend} from "./components.js";
const daily = (await FileAttachment("data/daily.json").json()).map((d) => ({
  ...d,
  date: new Date(d.event_date)
}));

const series = (keys) =>
  keys.flatMap(([key, name]) => daily.map((d) => ({date: d.date, name, value: d[key]})));

function lines(keys, colors, {label, format = integer}) {
  const names = keys.map((d) => d[1]);
  return Plot.plot({
    height: 240,
    marginLeft: 60,
    color: {domain: names, range: colors},
    x: {type: "utc", label: null, ticks: "day", tickFormat: "%b %d"},
    y: {label, grid: true, zero: true},
    marks: [
      Plot.lineY(series(keys).filter((d) => d.value != null), {
        x: "date",
        y: "value",
        stroke: "name",
        strokeWidth: 2,
        marker: "circle"
      }),
      Plot.tip(
        series(keys).filter((d) => d.value != null),
        Plot.pointer({
          x: "date",
          y: "value",
          title: (d) => `${d.name}\n${d.date.toISOString().slice(0, 10)}\n${format(d.value)}`
        })
      )
    ]
  });
}

const blue = "var(--series-1)";
const orange = "var(--series-2)";
```

# Trends

Daily totals across the feed. Each chart uses one axis, and every series starts at zero.

## Humans and bots

```js
display(legend([["Human events", blue], ["Bot events", orange]]));
display(lines([["human_events", "Human events"], ["bot_events", "Bot events"]], [blue, orange], {label: "Events"}));
```

## Pull requests

```js
display(legend([["Opened", blue], ["Merged", orange]]));
display(lines([["prs_opened", "Opened"], ["prs_merged", "Merged"]], [blue, orange], {label: "Human PR events"}));
```

Merged close to opened is expected here: most PRs are same-repo work merged within the hour.

## Issues

```js
display(legend([["Opened", blue], ["Closed", orange]]));
display(lines([["issues_opened", "Opened"], ["issues_closed", "Closed"]], [blue, orange], {label: "Human issue events"}));
```

## Attention

```js
display(legend([["Stars", blue], ["Forks", orange]]));
display(lines([["stars", "Stars"], ["forks", "Forks"]], [blue, orange], {label: "Events"}));
```

## Median first response, by the day it happened

```js
display(legend([["Issues", blue], ["Pull requests", orange]]));
display(lines([["issue_response_median_h", "Issues"], ["pr_response_median_h", "Pull requests"]], [blue, orange], {label: "Hours", format: hours}));
```

The window is a fixed length, so responses late in the window can be longer than early ones.
