---
title: Pipeline health
---

```js
import {integer, percent, tile} from "./components.js";
const meta = await FileAttachment("data/meta.json").json();
const partitions = await FileAttachment("data/partitions.json").json();
const bots = await FileAttachment("data/bots.json").json();
const p = meta.pipeline;
const latest = p.latest_event_at.replace("T", " ").replace("Z", " UTC");
const size = (bytes) => `${(bytes / 1e9).toFixed(2)} GB`;
```

# Pipeline health

<div class="tiles">
  ${tile("Partitions ingested", `${integer(p.partitions_ok)} of ${integer(p.partitions_total)}`, `${integer(p.partitions_missing)} missing, ${integer(p.partitions_corrupt)} corrupt`)}
  ${tile("Lines rejected", integer(p.rows_rejected), `of ${integer(p.rows_read)} read`)}
  ${tile("Duplicates removed", integer(p.rows_duplicate_within_partition + p.rows_duplicate_across_partitions))}
  ${tile("Latest event", html`<span style="font-size:1.05rem">${latest}</span>`, "data freshness")}
  ${tile("Downloaded", size(p.bytes_compressed), `${size(p.bytes_uncompressed)} uncompressed`)}
  ${tile("Capture estimate", percent(p.estimated_capture_rate, 2), "from comment counters")}
</div>

## Rows kept per partition

Each cell is one hourly partition. A red cross marks an hour that is missing or corrupt.

```js
Plot.plot({
  height: 40 + 7 * 34,
  marginLeft: 90,
  padding: 0.06,
  color: {type: "linear", scheme: "blues", legend: true, label: "Rows kept"},
  x: {label: "Hour (UTC)", tickFormat: (d) => String(d).padStart(2, "0")},
  y: {label: null},
  marks: [
    Plot.cell(partitions, {
      x: "partition_hour",
      y: "partition_date",
      fill: "rows_kept",
      inset: 0.5,
      rx: 2,
      tip: true,
      title: (d) =>
        `${d.partition_date} ${String(d.partition_hour).padStart(2, "0")}:00\n${d.status}\n${integer(d.rows_kept)} kept of ${integer(d.rows_read)}\n${integer(d.rows_rejected)} rejected`
    }),
    Plot.dot(
      partitions.filter((d) => d.status !== "ok"),
      {x: "partition_hour", y: "partition_date", symbol: "times", stroke: "#e34948"}
    )
  ]
})
```

## Bot share by event type

```js
Plot.plot({
  marginLeft: 230,
  height: 40 + bots.by_type.length * 26,
  x: {domain: [0, 1], percent: true, label: "Share of events from bots", grid: true},
  y: {label: null},
  marks: [
    Plot.barX(bots.by_type, {
      x: "bot_share",
      y: "event_type",
      sort: {y: "-x"},
      fill: "var(--series-1)",
      rx: 2,
      tip: true,
      title: (d) => `${d.event_type}\n${percent(d.bot_share)} of ${integer(d.total_events)} events`
    }),
    Plot.ruleX([0], {stroke: "var(--recessive)"})
  ]
})
```

## Volume by event type

```js
Inputs.table(bots.by_type, {
  columns: ["event_type", "total_events", "bot_events", "bot_share"],
  header: {event_type: "Event type", total_events: "Events", bot_events: "Bot events", bot_share: "Bot share"},
  format: {total_events: integer, bot_events: integer, bot_share: (value) => percent(value)},
  select: false
})
```
