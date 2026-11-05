# Design decisions

The build log, with evidence, is in `DECISIONS.md`. This covers the choices worth defending.

## Medallion layout

**Bronze** is one Parquet file per hour with the raw payload preserved. Nothing is interpreted, so
when a parser turns out to be wrong, which happened here, silver is rebuilt without touching the
network. **Silver** conforms shapes and types, and keeps bots, because bot comments carry PR
metadata. **Gold** applies definitions. Separating silver from gold keeps "what happened" apart
from "what we think it means", so metric changes never reach raw data.

The audit and rejects tables sit beside bronze. Every line read is accounted for as kept, filtered,
rejected or duplicate, and a dbt test enforces that sum.

## Why DuckDB and dbt

The whole window is under 1 GB of Parquet, so a warehouse service would add cost and no capability.
DuckDB reads Parquet in place, runs in a free CI runner and needs no server. dbt adds tests,
lineage and docs. `dbt-duckdb` external materialisation writes Parquet directly, so the warehouse
file is disposable: delete it and rebuild.

The limit to know: DuckDB is single-node and one process holds the write lock, so Dagster runs dbt
serially, and Parquet-based checks avoid the warehouse file.

## Idempotency

Each hour maps to one partition path, and writes go to a temporary file followed by an atomic
rename, so a crash leaves the old partition or the new one, never half of one. Bronze holds no
ingestion timestamp, since that would make re-runs differ. A forced re-ingest of all 168 partitions
gave a byte-identical checksum.

Silver and gold are pure functions of bronze and seeds. Extracts are rounded and sorted and hold no
wall-clock values, so a rebuild leaves git clean. De-duplication happens twice: by event id within
an hour during ingestion, and across partitions in staging.

One asymmetry is deliberate: a 404 never replaces a good partition. Re-running must not turn a
transient upstream problem into data loss.

## Late and missing data

GH Archive files are immutable once published, so "late" here mostly means delayed or missing. 404s
retry with backoff, then the hour is recorded as `missing` instead of failing, and an asset check
fails when gaps pass 5%. A later run picks up the hour, because only `ok` partitions are skipped.

Within the data, lateness means a window edge: PRs opened at the end have had less time to merge.
That is why merge rate uses terminal events and response time counts only items created in the
window. Comparing the start and end of a window still needs care.

## Sampling is the hardest constraint

The obvious design joins `opened` to `merged`, which keeps 1% of PRs at this capture rate. The design
here treats any event as evidence about an entity and takes each field from wherever it appears, so
one comment by a bot supplies a PR's author, creation time and merge time. Ratios use numerator
and denominator from the same event type, which is unbiased if loss is uniform. REST validation
shows it is not quite uniform for `closed`, and that gap is published instead of hidden.

## Memory

One `json_extract` per field parses the document once per field, and this hit 12.7 GB. A single
call with a list of paths parses once. De-duplication ranks ids only, so payloads aren't buffered.
This took staging from out-of-memory to seconds under a 5 GB limit.

## Scaling to a cloud warehouse

The current feed is small, but the design has to hold up if volume returns to 100 MB an hour or
more, or the window grows.

| Component | Today | At larger scale |
| --- | --- | --- |
| Storage | Local Parquet | S3 or GCS, same layout, or Iceberg for atomic partition swaps |
| Warehouse | DuckDB | BigQuery, Snowflake or Databricks through another dbt adapter |
| Silver and gold | Full rebuild | Incremental models keyed on partition date, with a lookback for late data |
| Ingestion | Threads | Dagster partitions on a cluster, one partition per task |
| JSON | Parsed in dbt | Typed at ingestion for hot fields |
| Orchestration | Local Dagster | Dagster Cloud or a self-hosted deployment |

Most models would port with small changes to JSON functions and `arg_max`. The partition contract,
the audit table and the export contract stay the same, which is the point of having them.

## What I would do next

- Extend the window. Per-repo samples are thin at 7 days, and 30 days costs about 3 GB.
- Calibrate merge rates with a REST sample per repo, since the bias is measured.
- Use `MemberEvent`, not in the required types, as further maintainer evidence.
