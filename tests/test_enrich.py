from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pyarrow.parquet as pq

from oss_pulse.enrich import (
    enrich,
    fetch_repo,
    metadata_path,
    rate_limit_wait,
    read_cache,
    to_row,
)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        return self.responses.pop(0)


def response(status=200, headers=None, body=None):
    def as_json():
        return body or {}

    def raise_for_status():
        return None

    return SimpleNamespace(
        status_code=status,
        headers=headers or {},
        json=as_json,
        raise_for_status=raise_for_status,
    )


def test_no_wait_while_quota_remains():
    assert rate_limit_wait({"X-RateLimit-Remaining": "100"}, 1000.0) == 0.0
    assert rate_limit_wait({}, 1000.0) == 0.0


def test_waits_for_the_reset_when_quota_runs_out():
    headers = {"X-RateLimit-Remaining": "2", "X-RateLimit-Reset": "1060"}
    assert rate_limit_wait(headers, 1000.0) == 61.0


def test_fetch_honours_retry_after_and_retries():
    waits = []
    session = FakeSession(
        [response(403, {"Retry-After": "30"}), response(200, body={"full_name": "a/b"})]
    )
    body = fetch_repo(session, "a/b", sleep=waits.append, clock=lambda: 0.0)
    assert body == {"full_name": "a/b"}
    assert waits == [30.0]


def test_missing_repo_returns_none():
    assert fetch_repo(FakeSession([response(404)]), "a/b") is None


def test_row_flattens_license_and_sorts_topics():
    row = to_row(1, {"full_name": "a/b", "license": {"spdx_id": "MIT"}, "topics": ["z", "a"]})
    assert row["license"] == "MIT"
    assert row["topics"] == ["a", "z"]
    assert row["archived"] is False


def test_row_tolerates_a_missing_license():
    assert to_row(1, {"license": None})["license"] is None


def test_cache_expires(tmp_path):
    path = tmp_path / "1.json"
    now = datetime(2026, 1, 8, tzinfo=UTC)
    path.write_text('{"fetched_at": "2026-01-07T00:00:00+00:00", "body": {}}')
    assert read_cache(path, now) is not None
    assert read_cache(path, now + timedelta(days=7)) is None


def test_no_token_writes_an_empty_table(settings, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OSS_PULSE_OFFLINE", raising=False)
    result = enrich(settings)
    assert result.skipped_reason == "GITHUB_TOKEN is not set"
    assert pq.read_table(metadata_path(settings)).num_rows == 0


def test_offline_flag_skips_even_with_a_token(settings, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "unused")
    monkeypatch.setenv("OSS_PULSE_OFFLINE", "1")
    assert enrich(settings).skipped_reason == "offline run"
