"""Bronze ingestion: one GH Archive hour in, one idempotent Parquet partition out.

The hour is streamed line by line, so memory stays flat regardless of file size.
Every partition produces an audit row, including hours that are missing upstream.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from oss_pulse.config import GHARCHIVE_BASE_URL, KEPT_EVENT_TYPES, Settings

log = logging.getLogger(__name__)

BATCH_ROWS = 20_000
MAX_REJECT_LINE_CHARS = 2_000

BRONZE_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("event_type", pa.string()),
        ("created_at", pa.timestamp("s")),
        ("actor_id", pa.int64()),
        ("actor_login", pa.string()),
        ("repo_id", pa.int64()),
        ("repo_name", pa.string()),
        ("org_id", pa.int64()),
        ("org_login", pa.string()),
        ("is_public", pa.bool_()),
        ("payload", pa.string()),
    ]
)

REJECT_SCHEMA = pa.schema(
    [
        ("source_file", pa.string()),
        ("line_number", pa.int64()),
        ("reason", pa.string()),
        ("raw_line", pa.string()),
    ]
)

AUDIT_SCHEMA = pa.schema(
    [
        ("partition_date", pa.string()),
        ("partition_hour", pa.int32()),
        ("status", pa.string()),
        ("rows_read", pa.int64()),
        ("rows_kept", pa.int64()),
        ("rows_filtered", pa.int64()),
        ("rows_rejected", pa.int64()),
        ("rows_duplicate", pa.int64()),
        ("rows_out_of_hour", pa.int64()),
        ("bytes_compressed", pa.int64()),
        ("bytes_uncompressed", pa.int64()),
        ("attempts", pa.int32()),
        ("duration_s", pa.float64()),
        ("ingested_at", pa.string()),
    ]
)


class HourMissing(Exception):
    """The hour does not exist upstream, after retries."""


class HourCorrupt(Exception):
    """The hour downloaded but could not be decompressed, after retries."""


@dataclass
class Audit:
    partition_date: str
    partition_hour: int
    status: str = "ok"  # ok | missing | corrupt
    rows_read: int = 0
    rows_kept: int = 0
    rows_filtered: int = 0
    rows_rejected: int = 0
    rows_duplicate: int = 0
    rows_out_of_hour: int = 0
    bytes_compressed: int = 0
    bytes_uncompressed: int = 0
    attempts: int = 0
    duration_s: float = 0.0
    ingested_at: str = ""


def gharchive_filename(hour: datetime) -> str:
    """GH Archive does not zero-pad the hour: 2026-11-03-7.json.gz."""
    return f"{hour:%Y-%m-%d}-{hour.hour}.json.gz"


def partition_subdir(hour: datetime) -> str:
    return f"date={hour:%Y-%m-%d}/hour={hour.hour:02d}"


def bronze_path(settings: Settings, hour: datetime) -> Path:
    return settings.bronze_dir / partition_subdir(hour) / "events.parquet"


def rejects_path(settings: Settings, hour: datetime) -> Path:
    return settings.rejects_dir / partition_subdir(hour) / "rejects.parquet"


def audit_path(settings: Settings, hour: datetime) -> Path:
    return settings.audit_dir / partition_subdir(hour) / "audit.parquet"


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def parse_line(line: str) -> tuple[dict | None, str | None]:
    """Return (event, None) for a usable line and (None, reason) otherwise."""
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        return None, "invalid_json"
    if not isinstance(event, dict):
        return None, "not_an_object"
    for field in ("id", "type", "created_at"):
        if not event.get(field):
            return None, f"missing_{field}"
    actor, repo = event.get("actor"), event.get("repo")
    if not isinstance(actor, dict) or actor.get("id") is None:
        return None, "missing_actor"
    if not isinstance(repo, dict) or repo.get("id") is None or not repo.get("name"):
        return None, "missing_repo"
    try:
        parse_timestamp(event["created_at"])
    except (TypeError, ValueError):
        return None, "bad_created_at"
    return event, None


def to_row(event: dict) -> dict:
    org = event.get("org") or {}
    return {
        "event_id": str(event["id"]),
        "event_type": event["type"],
        "created_at": parse_timestamp(event["created_at"]),
        "actor_id": event["actor"]["id"],
        "actor_login": event["actor"].get("login"),
        "repo_id": event["repo"]["id"],
        "repo_name": event["repo"]["name"],
        "org_id": org.get("id"),
        "org_login": org.get("login"),
        "is_public": event.get("public"),
        # ASCII escaping keeps lone surrogates in user text representable as UTF-8.
        "payload": json.dumps(event.get("payload") or {}, separators=(",", ":")),
    }


def process_lines(
    lines: Iterable[str],
    hour: datetime,
    audit: Audit,
    source_file: str,
    bronze_writer: Callable[[list[dict]], None],
    rejects: list[dict],
) -> None:
    """Filter, validate and de-duplicate a stream of raw lines into bronze batches."""
    seen: set[str] = set()
    batch: list[dict] = []
    for line_number, line in enumerate(lines, start=1):
        audit.rows_read += 1
        audit.bytes_uncompressed += len(line.encode("utf-8", "surrogatepass"))
        if not line.strip():
            audit.rows_rejected += 1
            rejects.append(_reject(source_file, line_number, "blank_line", line))
            continue
        event, reason = parse_line(line)
        if event is None:
            audit.rows_rejected += 1
            rejects.append(_reject(source_file, line_number, reason, line))
            continue
        if event["type"] not in KEPT_EVENT_TYPES:
            audit.rows_filtered += 1
            continue
        event_id = str(event["id"])
        if event_id in seen:
            audit.rows_duplicate += 1
            continue
        seen.add(event_id)
        row = to_row(event)
        created = row["created_at"]
        if (created.date(), created.hour) != (hour.date(), hour.hour):
            audit.rows_out_of_hour += 1
        batch.append(row)
        audit.rows_kept += 1
        if len(batch) >= BATCH_ROWS:
            bronze_writer(batch)
            batch = []
    if batch:
        bronze_writer(batch)


def _reject(source_file: str, line_number: int, reason: str | None, line: str) -> dict:
    return {
        "source_file": source_file,
        "line_number": line_number,
        "reason": reason,
        "raw_line": line[:MAX_REJECT_LINE_CHARS].encode("utf-8", "replace").decode("utf-8"),
    }


def download(url: str, dest: Path, timeout: int = 120) -> None:
    """Stream a URL to dest. Raises FileNotFoundError on 404."""
    if url.startswith("file://"):
        source = Path(url.removeprefix("file://"))
        if not source.exists():
            raise FileNotFoundError(url)
        shutil.copyfile(source, dest)
        return
    with requests.get(url, stream=True, timeout=timeout) as response:
        if response.status_code == 404:
            raise FileNotFoundError(url)
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)


def _write_table_atomic(table: pa.Table, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    os.close(fd)
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, target)


def write_audit(settings: Settings, hour: datetime, audit: Audit) -> None:
    table = pa.Table.from_pylist([asdict(audit)], schema=AUDIT_SCHEMA)
    _write_table_atomic(table, audit_path(settings, hour))


def read_audit(settings: Settings, hour: datetime) -> Audit | None:
    path = audit_path(settings, hour)
    if not path.exists():
        return None
    return Audit(**pq.read_table(path).to_pylist()[0])


def fetch_with_retries(
    url: str,
    dest: Path,
    max_attempts: int = 4,
    backoff_s: float = 2.0,
    fetch: Callable[[str, Path], None] = download,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Download with exponential backoff. Returns attempts used.

    A 404 may only mean the hour is delayed, so it is retried too, then surfaced
    as HourMissing so the caller can record the gap rather than fail the run.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            fetch(url, dest)
            return attempt
        except FileNotFoundError as error:
            last_error = error
            log.warning("404 for %s (attempt %d/%d)", url, attempt, max_attempts)
        except requests.RequestException as error:
            last_error = error
            log.warning("error for %s (attempt %d/%d): %s", url, attempt, max_attempts, error)
        if attempt < max_attempts:
            sleep(backoff_s * 2 ** (attempt - 1))
    if isinstance(last_error, FileNotFoundError):
        raise HourMissing(url)
    raise last_error  # type: ignore[misc]


def ingest_hour(
    settings: Settings,
    hour: datetime,
    base_url: str = GHARCHIVE_BASE_URL,
    retain_raw: bool = False,
    skip_existing: bool = False,
    max_attempts: int = 4,
    backoff_s: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Audit:
    """Ingest one hour. Re-running overwrites the partition with identical rows."""
    if skip_existing:
        existing = read_audit(settings, hour)
        if existing and existing.status == "ok" and bronze_path(settings, hour).exists():
            return existing

    started = time.monotonic()
    audit = Audit(partition_date=f"{hour:%Y-%m-%d}", partition_hour=hour.hour)
    filename = gharchive_filename(hour)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = settings.raw_dir / filename

    for attempt_group in range(1, max_attempts + 1):
        try:
            audit.attempts += fetch_with_retries(
                f"{base_url.rstrip('/')}/{filename}",
                raw_file,
                max_attempts=max_attempts,
                backoff_s=backoff_s,
                sleep=sleep,
            )
        except HourMissing:
            return _finish_gap(settings, hour, audit, "missing", started)

        try:
            audit.bytes_compressed = raw_file.stat().st_size
            _stream_to_bronze(settings, hour, raw_file, filename, audit)
            break
        except (EOFError, gzip.BadGzipFile, OSError) as error:
            # Truncated download: reset counters and fetch the hour again.
            log.warning("corrupt gzip for %s (try %d): %s", filename, attempt_group, error)
            attempts = audit.attempts
            audit = Audit(partition_date=audit.partition_date, partition_hour=audit.partition_hour)
            audit.attempts = attempts
    else:
        raw_file.unlink(missing_ok=True)
        return _finish_gap(settings, hour, audit, "corrupt", started)

    if not retain_raw:
        raw_file.unlink(missing_ok=True)
    audit.duration_s = round(time.monotonic() - started, 3)
    audit.ingested_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_audit(settings, hour, audit)
    return audit


def _finish_gap(
    settings: Settings, hour: datetime, audit: Audit, status: str, started: float
) -> Audit:
    audit.status = status
    audit.duration_s = round(time.monotonic() - started, 3)
    audit.ingested_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Never replace good data with a gap: a transient upstream problem must not
    # erase a partition that was already ingested.
    if bronze_path(settings, hour).exists():
        log.warning("%s for %s, keeping existing partition", status, hour)
        previous = read_audit(settings, hour)
        return previous or audit
    write_audit(settings, hour, audit)
    log.warning("recorded %s partition %s", status, hour)
    return audit


def _stream_to_bronze(
    settings: Settings, hour: datetime, raw_file: Path, filename: str, audit: Audit
) -> None:
    target = bronze_path(settings, hour)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    rejects: list[dict] = []
    writer = pq.ParquetWriter(tmp, BRONZE_SCHEMA, compression="zstd")

    def write_batch(rows: list[dict]) -> None:
        writer.write_table(pa.Table.from_pylist(rows, schema=BRONZE_SCHEMA))

    try:
        with gzip.open(raw_file, "rt", encoding="utf-8", errors="replace") as lines:
            process_lines(
                (line.rstrip("\n") for line in lines), hour, audit, filename, write_batch, rejects
            )
        writer.close()
    except BaseException:
        writer.close()
        tmp.unlink(missing_ok=True)
        raise

    os.replace(tmp, target)
    reject_target = rejects_path(settings, hour)
    if rejects:
        _write_table_atomic(pa.Table.from_pylist(rejects, schema=REJECT_SCHEMA), reject_target)
    else:
        reject_target.unlink(missing_ok=True)
