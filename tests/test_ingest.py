import gzip
import json
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import requests

from oss_pulse import ingest
from oss_pulse.ingest import (
    Audit,
    HourMissing,
    bronze_path,
    fetch_with_retries,
    gharchive_filename,
    ingest_hour,
    parse_line,
    process_lines,
    read_audit,
    rejects_path,
)
from oss_pulse.reports import prune_old_partitions

HOUR = datetime(2026, 3, 3, 10)


def event(event_id="1", kind="WatchEvent", created="2026-03-03T10:00:01Z") -> dict:
    return {
        "id": event_id,
        "type": kind,
        "actor": {"id": 7, "login": "ana"},
        "repo": {"id": 9, "name": "acme/widgets"},
        "payload": {"action": "started"},
        "public": True,
        "created_at": created,
    }


def write_hour(directory: Path, lines: list[str], hour: datetime = HOUR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / gharchive_filename(hour), "wt") as handle:
        handle.write("\n".join(lines) + "\n")


def no_sleep(_seconds: float) -> None:
    pass


def test_filename_does_not_pad_the_hour():
    assert gharchive_filename(datetime(2026, 3, 3, 7)) == "2026-03-03-7.json.gz"


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("{broken", "invalid_json"),
        ("[1, 2]", "not_an_object"),
        (json.dumps({**event(), "id": None}), "missing_id"),
        (json.dumps({k: v for k, v in event().items() if k != "repo"}), "missing_repo"),
        (json.dumps({**event(), "repo": {"id": 9, "name": None}}), "missing_repo"),
        (json.dumps({k: v for k, v in event().items() if k != "actor"}), "missing_actor"),
        (json.dumps({**event(), "created_at": "yesterday"}), "bad_created_at"),
    ],
)
def test_bad_lines_get_a_reason(line, reason):
    parsed, found = parse_line(line)
    assert parsed is None
    assert found == reason


def test_process_lines_filters_dedupes_and_counts():
    lines = [
        json.dumps(event("1")),
        json.dumps(event("1")),
        json.dumps(event("2", "PushEvent")),
        "{broken",
        "",
        json.dumps(event("3", created="2026-03-03T11:00:00Z")),
    ]
    audit, batches, rejects = Audit("2026-03-03", 10), [], []
    process_lines(lines, HOUR, audit, "f.json.gz", batches.append, rejects)
    assert [row["event_id"] for row in batches[0]] == ["1", "3"]
    assert audit.rows_read == 6
    assert audit.rows_kept == 2
    assert audit.rows_duplicate == 1
    assert audit.rows_filtered == 1
    assert audit.rows_rejected == 2
    assert audit.rows_out_of_hour == 1
    assert {reject["reason"] for reject in rejects} == {"invalid_json", "blank_line"}


def test_raw_payload_is_preserved():
    audit, batches, rejects = Audit("2026-03-03", 10), [], []
    process_lines([json.dumps(event())], HOUR, audit, "f", batches.append, rejects)
    assert json.loads(batches[0][0]["payload"]) == {"action": "started"}


def test_rerun_overwrites_a_partition_exactly(settings, tmp_path):
    source = tmp_path / "source"
    write_hour(source, [json.dumps(event("1")), json.dumps(event("2"))])
    base = f"file://{source}"
    ingest_hour(settings, HOUR, base_url=base)
    first = pq.read_table(bronze_path(settings, HOUR))
    ingest_hour(settings, HOUR, base_url=base)
    second = pq.read_table(bronze_path(settings, HOUR))
    assert first.equals(second)
    assert first.num_rows == 2


def test_download_is_deleted_unless_retained(settings, tmp_path):
    source = tmp_path / "source"
    write_hour(source, [json.dumps(event())])
    raw = settings.raw_dir / gharchive_filename(HOUR)
    ingest_hour(settings, HOUR, base_url=f"file://{source}")
    assert not raw.exists()
    ingest_hour(settings, HOUR, base_url=f"file://{source}", retain_raw=True)
    assert raw.exists()


def test_rejects_are_quarantined(settings, tmp_path):
    source = tmp_path / "source"
    write_hour(source, [json.dumps(event()), "{broken"])
    audit = ingest_hour(settings, HOUR, base_url=f"file://{source}")
    assert audit.rows_rejected == 1
    assert pq.read_table(rejects_path(settings, HOUR)).column("reason").to_pylist() == [
        "invalid_json"
    ]


def test_clean_rerun_clears_old_rejects(settings, tmp_path):
    source = tmp_path / "source"
    write_hour(source, [json.dumps(event()), "{broken"])
    ingest_hour(settings, HOUR, base_url=f"file://{source}")
    write_hour(source, [json.dumps(event())])
    ingest_hour(settings, HOUR, base_url=f"file://{source}")
    assert not rejects_path(settings, HOUR).exists()


def test_missing_hour_is_recorded_not_raised(settings, tmp_path):
    audit = ingest_hour(
        settings, HOUR, base_url=f"file://{tmp_path}/nothing", max_attempts=2, sleep=no_sleep
    )
    assert audit.status == "missing"
    assert audit.attempts == 0
    assert read_audit(settings, HOUR).status == "missing"
    assert not bronze_path(settings, HOUR).exists()


def test_upstream_gap_never_deletes_good_data(settings, tmp_path):
    source = tmp_path / "source"
    write_hour(source, [json.dumps(event())])
    ingest_hour(settings, HOUR, base_url=f"file://{source}")
    audit = ingest_hour(
        settings, HOUR, base_url=f"file://{tmp_path}/gone", max_attempts=1, sleep=no_sleep
    )
    assert audit.status == "ok"
    assert pq.read_table(bronze_path(settings, HOUR)).num_rows == 1


def test_corrupt_gzip_is_recorded_after_retries(settings, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / gharchive_filename(HOUR)).write_bytes(b"\x1f\x8b not really gzip")
    audit = ingest_hour(settings, HOUR, base_url=f"file://{source}", max_attempts=2, sleep=no_sleep)
    assert audit.status == "corrupt"
    assert not bronze_path(settings, HOUR).exists()


def test_truncated_gzip_leaves_no_partial_partition(settings, tmp_path):
    source = tmp_path / "source"
    write_hour(source, [json.dumps(event(str(i))) for i in range(500)])
    target = source / gharchive_filename(HOUR)
    target.write_bytes(target.read_bytes()[:-40])
    audit = ingest_hour(settings, HOUR, base_url=f"file://{source}", max_attempts=1, sleep=no_sleep)
    assert audit.status == "corrupt"
    assert not list(bronze_path(settings, HOUR).parent.glob("*"))


def test_skip_existing_does_not_refetch(settings, tmp_path):
    source = tmp_path / "source"
    write_hour(source, [json.dumps(event())])
    first = ingest_hour(settings, HOUR, base_url=f"file://{source}")
    (source / gharchive_filename(HOUR)).unlink()
    assert (
        ingest_hour(settings, HOUR, base_url=f"file://{source}", skip_existing=True).ingested_at
        == first.ingested_at
    )


def test_backoff_doubles_between_attempts(tmp_path):
    waits, calls = [], []

    def flaky(url, dest):
        calls.append(url)
        if len(calls) < 3:
            raise requests.ConnectionError("reset")

    attempts = fetch_with_retries(
        "http://x", tmp_path / "f", max_attempts=4, backoff_s=2, fetch=flaky, sleep=waits.append
    )
    assert attempts == 3
    assert waits == [2, 4]


def test_404_retries_then_reports_missing(tmp_path):
    waits = []

    def absent(url, dest):
        raise FileNotFoundError(url)

    with pytest.raises(HourMissing):
        fetch_with_retries(
            "http://x",
            tmp_path / "f",
            max_attempts=3,
            backoff_s=1,
            fetch=absent,
            sleep=waits.append,
        )
    assert waits == [1, 2]


def test_persistent_server_errors_are_raised(tmp_path):
    def failing(url, dest):
        raise requests.HTTPError("502")

    with pytest.raises(requests.HTTPError):
        fetch_with_retries(
            "http://x", tmp_path / "f", max_attempts=2, fetch=failing, sleep=no_sleep
        )


def test_batches_flush_at_the_limit(monkeypatch):
    monkeypatch.setattr(ingest, "BATCH_ROWS", 2)
    audit, batches, rejects = Audit("2026-03-03", 10), [], []
    lines = [json.dumps(event(str(i))) for i in range(5)]
    process_lines(lines, HOUR, audit, "f", batches.append, rejects)
    assert [len(batch) for batch in batches] == [2, 2, 1]


def test_prune_keeps_the_newest_days_only(settings):
    for day in ("2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"):
        for root in (settings.bronze_dir, settings.audit_dir, settings.rejects_dir):
            (root / f"date={day}" / "hour=00").mkdir(parents=True)
    (settings.rejects_dir / "_schema").mkdir()
    assert prune_old_partitions(settings, keep_days=2) == 2
    kept = sorted(path.name for path in settings.bronze_dir.glob("date=*"))
    assert kept == ["date=2026-03-03", "date=2026-03-04"]
    assert (settings.rejects_dir / "_schema").exists()


def test_prune_with_nothing_to_do(settings):
    assert prune_old_partitions(settings, keep_days=7) == 0
