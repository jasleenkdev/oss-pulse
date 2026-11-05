"""Shared fixtures. The session fixture runs the whole offline pipeline once."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import duckdb
import pytest

from oss_pulse.config import REPO_ROOT, REPORTS_DIR, Settings

VENV_BIN = REPO_ROOT / ".venv" / "bin"


def tool(name: str) -> str:
    candidate = VENV_BIN / name
    return str(candidate) if candidate.exists() else name


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    instance = Settings(data_dir=tmp_path / "data")
    instance.ensure()
    return instance


@pytest.fixture(scope="session")
def pipeline(tmp_path_factory) -> Settings:
    """Bronze to gold over tests/fixtures, offline, in a throwaway data directory."""
    data_dir = tmp_path_factory.mktemp("pipeline") / "data"
    data_dir.mkdir()
    env = {
        **os.environ,
        "OSS_PULSE_DATA_DIR": str(data_dir),
        "OSS_PULSE_OFFLINE": "1",
        "OSS_PULSE_DBT_TARGET": "ci",
        "DBT_PROFILES_DIR": str(REPO_ROOT / "dbt"),
    }
    completed = subprocess.run(
        ["sh", "scripts/run_fixture_pipeline.sh", tool("python"), tool("dbt")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout[-3000:] + completed.stderr[-3000:]
    return Settings(data_dir=data_dir)


@pytest.fixture(scope="session")
def query(pipeline):
    def run(sql: str) -> list[tuple]:
        connection = duckdb.connect()
        connection.execute(f"set file_search_path = '{pipeline.data_dir}'")
        return connection.execute(sql).fetchall()

    return run


def pytest_sessionfinish(session, exitstatus):
    if not os.environ.get("OSS_PULSE_RECORD_TESTS"):
        return
    path = REPORTS_DIR / "test_summary.json"
    summary = json.loads(path.read_text()) if path.exists() else {}
    collected = session.testscollected
    failed = session.testsfailed
    summary["pytest"] = {"collected": collected, "failed": failed, "passed": collected - failed}
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
