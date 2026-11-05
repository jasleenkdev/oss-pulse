# Interview preparation

Twelve questions this project prepares you for, with answers grounded in what it actually does.

## 1. What makes this pipeline idempotent?

Each hour maps to exactly one partition path. A run writes to a temporary file and renames it
atomically, so a crash leaves the old or new partition, never a partial one. Bronze excludes
ingestion timestamps, which live in the audit table. Silver and gold are pure functions of bronze
and seeds. I proved it by force re-ingesting all 168 partitions and comparing checksums, which were
byte-identical. I also treat "idempotent" as not losing data: a 404 on re-run keeps the existing
partition.

## 2. How do you run a backfill, and what can go wrong?

`make backfill DAYS=14` runs the hours in a thread pool, skipping partitions already `ok`, or
Dagster runs partition backfills through the same `ingest_hour`. Downstream models rebuild from
bronze, so nothing needs a special backfill mode. The risks are upstream rate limits, partial
windows, and metrics computed before the backfill finishes. Scoped retries and the audit table
handle the first two, and dependencies in Dagster handle the third. The subtle one here was schema
drift: a backfill across October 2025 mixes two payload shapes, so staging normalises both.

## 3. Why partition by date and hour?

It matches the source's unit of delivery, so a partition is the unit of retry, audit and overwrite.
Reads can prune by date, and retention is deleting a directory. Hourly fits GH Archive, though it
creates small files, about 4 MB here. At greater volume I would keep hourly ingestion and compact
into daily files, because many small files slow scans on object storage.

## 4. How do you handle late or missing data?

Missing hours retry with backoff, then are recorded as `missing` instead of failing the run, since
one absent hour shouldn't block a whole day. An asset check fails when gaps exceed 5%, so the
decision is explicit. A later run re-attempts anything not `ok`. Lateness also exists at window
edges: a PR opened on the last day has had no time to merge. So I used terminal events for merge
rate instead of an opened cohort, and I described the bias instead of pretending it isn't there.

## 5. What is a data contract, and why have one here?

It is a versioned agreement on columns, types, nullability and meaning between producer and
consumer. `contracts/firstpr_export_v1.yml` covers the FirstPR export. A pytest and a blocking
Dagster check validate the file, so a breaking change fails before publishing. Tests cover a missing
column, an undeclared column, a type change, nulls, range and duplicates. It also carries semantics
a schema can't, such as response times being upper bounds. Additive changes bump the minor version,
and breaking changes get a new file, so FirstPR migrates on its own schedule.

## 6. What is your testing strategy?

Layers, each catching something different. pytest unit tests cover parsing, retries and corrupt
files. Fixture tests push synthetic events with known answers through the real pipeline, for
example a 2-hour response must come out as 2.0. dbt tests check keys, relationships and invariants
on real data. Asset checks cover what dbt can't see, such as gaps and reject rates. REST validation
checks the assumptions themselves. The most valuable test found a real bug: Dagster dependencies
written as bare strings had created phantom assets, so checks weren't running on the real tables
even though the job reported success.

## 7. How would you scale this?

Move Parquet to object storage with the same layout, ideally Iceberg for atomic swaps. Swap
dbt-duckdb for BigQuery or Snowflake, where most SQL ports with small changes. Make silver
incremental with a lookback window instead of rebuilding it, and run partitions as Dagster tasks on
a cluster. I'd type hot JSON fields at ingestion. The audit table and contract stay the same, which
is why they're separate from the engine. I would not do this for today's volume, under 1 GB a week.

## 8. How do you handle failures?

Failure types get different responses. Transient network errors retry with exponential backoff.
Missing hours are recorded. Corrupt gzip re-downloads, then records the partition as `corrupt`.
Malformed lines go to a rejects table with a reason, so one bad line can't lose an hour. Writes are
atomic, so a failed run leaves no partial state. Blocking asset checks stop a bad export from
publishing. The rule is to fail loudly where a human must decide, and keep going where the system
can account for the gap.

## 9. Tell me about a time the data wasn't what you expected.

The feed had lost `author_association` and most PR fields, so I inspected real payloads before
writing parsers. Then the numbers looked wrong: the "merged by" actor equalled the PR author 99% of
the time, and dependabot appeared to merge its own PRs. Checking 146 events against REST showed the
actor on `merged` is the author. That broke the obvious maintainer rule, so I replaced it with a
stronger signal, because a same-repo branch needs push access. It also helped: every merged PR now
has a known author without pairing events. I keep that validation as a script and report its
precision, including the rule that scored badly.

## 10. How do you know your proxy metrics are valid?

I score them against ground truth where it exists. The removed fields are still in the REST API, so
a script samples rows deterministically and compares. Maintainer inference has 85.4% precision.
About 37% of sampled comments from people not inferred were really maintainers, so recall is the
weak side, and I documented that "external" includes some insiders. The external merge rate reads
88.7% from events and 77.3% from REST. I publish both, because a proxy without a measured error
is just a guess.

## 11. How did you optimise memory?

DuckDB hit 12.7 GB on 680,000 events. Rather than raising limits, I isolated it: one JSON expression
was fine and 46 weren't, because each `json_extract` re-parses the document. A single call with a
list of paths parses once. Ranking only ids for de-duplication meant payloads were never buffered.
It then ran in seconds under a 5 GB cap, which also makes it fit a free runner.

## 12. Why did you choose these tools?

DuckDB because the data fits on one machine and a warehouse would add cost and no capability. dbt
for tests and lineage. Dagster because software-defined assets and partitions map directly onto an
hourly source, and its asset checks tie quality to data rather than tasks. Observable Framework
because the site builds from static JSON with no database. I'd reconsider DuckDB once several
writers or much larger data enter the picture, and that move is mostly a dbt adapter change.
