"""Optional repository metadata from the GitHub REST API.

Runs between silver and gold. Responses are cached on disk, and rate limits are read
from the response headers. Without a token the step writes an empty table, so the
gold models run either way.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from oss_pulse.config import Settings

log = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
CACHE_TTL = timedelta(days=7)
MAX_RATE_LIMIT_WAIT_S = 900
RATE_LIMIT_FLOOR = 5

METADATA_SCHEMA = pa.schema(
    [
        ("repo_id", pa.int64()),
        ("repo_name", pa.string()),
        ("language", pa.string()),
        ("topics", pa.list_(pa.string())),
        ("license", pa.string()),
        ("description", pa.string()),
        ("archived", pa.bool_()),
        ("stargazers_count", pa.int64()),
    ]
)


@dataclass
class EnrichResult:
    requested: int = 0
    cache_hits: int = 0
    fetched: int = 0
    not_found: int = 0
    skipped_reason: str | None = None


def metadata_path(settings: Settings) -> Path:
    return settings.enrichment_dir / "repo_metadata.parquet"


def write_metadata(settings: Settings, rows: list[dict]) -> None:
    target = metadata_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: row["repo_id"])
    table = pa.Table.from_pylist(rows, schema=METADATA_SCHEMA)
    tmp = target.with_suffix(".tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, target)


def ensure_empty_metadata(settings: Settings) -> None:
    if not metadata_path(settings).exists():
        write_metadata(settings, [])


def to_row(repo_id: int, body: dict) -> dict:
    return {
        "repo_id": repo_id,
        "repo_name": body.get("full_name"),
        "language": body.get("language"),
        "topics": sorted(body.get("topics") or []),
        "license": (body.get("license") or {}).get("spdx_id"),
        "description": body.get("description"),
        "archived": bool(body.get("archived")),
        "stargazers_count": body.get("stargazers_count"),
    }


def rate_limit_wait(headers: dict, now: float) -> float:
    """Seconds to pause after a response, from its rate limit headers."""
    remaining = headers.get("X-RateLimit-Remaining")
    if remaining is None or int(remaining) > RATE_LIMIT_FLOOR:
        return 0.0
    reset = float(headers.get("X-RateLimit-Reset", now))
    return max(0.0, reset - now) + 1.0


def fetch_repo(
    session: requests.Session,
    repo_name: str,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    max_attempts: int = 3,
) -> dict | None:
    """Return the repo body, or None when it is gone. Respects rate limit headers."""
    for attempt in range(1, max_attempts + 1):
        response = session.get(f"{API_ROOT}/repos/{repo_name}", timeout=30)
        pause = rate_limit_wait(response.headers, clock())
        if response.status_code in (403, 429):
            retry_after = float(response.headers.get("Retry-After", 0))
            pause = max(pause, retry_after, 2.0**attempt)
            if pause > MAX_RATE_LIMIT_WAIT_S:
                raise RuntimeError(f"rate limited for {pause:.0f}s, stopping enrichment")
            log.warning("rate limited on %s, waiting %.0fs", repo_name, pause)
            sleep(pause)
            continue
        if pause:
            if pause > MAX_RATE_LIMIT_WAIT_S:
                raise RuntimeError(f"rate limit resets in {pause:.0f}s, stopping enrichment")
            log.info("rate limit nearly used, waiting %.0fs", pause)
            sleep(pause)
        if response.status_code in (404, 451):
            return None
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"giving up on {repo_name} after {max_attempts} attempts")


def read_cache(path: Path, now: datetime) -> dict | None:
    if not path.exists():
        return None
    entry = json.loads(path.read_text())
    fetched_at = datetime.fromisoformat(entry["fetched_at"])
    return entry if now - fetched_at < CACHE_TTL else None


def top_repos(settings: Settings, top_n: int) -> list[tuple[int, str]]:
    connection = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        return connection.execute(
            """
            select repo_id, repo_name
            from staging.int_enrichment_candidates
            where activity_rank <= ?
            order by activity_rank
            """,
            [top_n],
        ).fetchall()
    finally:
        connection.close()


def enrich(settings: Settings, top_n: int = 500) -> EnrichResult:
    token = os.environ.get("GITHUB_TOKEN")
    result = EnrichResult()
    if os.environ.get("OSS_PULSE_OFFLINE"):
        result.skipped_reason = "offline run"
    elif not token:
        result.skipped_reason = "GITHUB_TOKEN is not set"
    if result.skipped_reason:
        log.info("skipping enrichment: %s", result.skipped_reason)
        ensure_empty_metadata(settings)
        return result

    cache_dir = settings.enrichment_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    now = datetime.now(UTC)
    rows: list[dict] = []
    targets = top_repos(settings, top_n)
    result.requested = len(targets)
    for repo_id, repo_name in targets:
        cache_file = cache_dir / f"{repo_id}.json"
        entry = read_cache(cache_file, now)
        if entry is not None:
            result.cache_hits += 1
        else:
            body = fetch_repo(session, repo_name)
            result.fetched += 1
            entry = {"fetched_at": now.isoformat(), "body": body}
            cache_file.write_text(json.dumps(entry))
        if entry["body"] is None:
            result.not_found += 1
            continue
        rows.append(to_row(repo_id, entry["body"]))
    write_metadata(settings, rows)
    log.info("enrichment: %s", result)
    return result
