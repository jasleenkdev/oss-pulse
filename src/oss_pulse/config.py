"""Paths and settings shared by the CLI, the Dagster code and the tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = REPO_ROOT / "dbt"
DASHBOARD_DIR = REPO_ROOT / "dashboard"
EXTRACTS_DIR = DASHBOARD_DIR / "src" / "data"
CONTRACTS_DIR = REPO_ROOT / "contracts"
REPORTS_DIR = REPO_ROOT / "reports"

GHARCHIVE_BASE_URL = "https://data.gharchive.org"

KEPT_EVENT_TYPES = frozenset(
    {
        "IssuesEvent",
        "IssueCommentEvent",
        "PullRequestEvent",
        "PullRequestReviewEvent",
        "PullRequestReviewCommentEvent",
        "WatchEvent",
        "ForkEvent",
        "CreateEvent",
    }
)


@dataclass(frozen=True)
class Settings:
    """Filesystem layout for one pipeline instance (real run or fixture run)."""

    data_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("OSS_PULSE_DATA_DIR") or str(REPO_ROOT / "data")
        return cls(data_dir=Path(raw).expanduser().resolve())

    @property
    def bronze_dir(self) -> Path:
        return self.data_dir / "bronze"

    @property
    def rejects_dir(self) -> Path:
        return self.data_dir / "rejects"

    @property
    def audit_dir(self) -> Path:
        return self.data_dir / "audit"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def silver_dir(self) -> Path:
        return self.data_dir / "silver"

    @property
    def gold_dir(self) -> Path:
        return self.data_dir / "gold"

    @property
    def enrichment_dir(self) -> Path:
        return self.data_dir / "enrichment"

    @property
    def warehouse_path(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    def ensure(self) -> None:
        for path in (
            self.bronze_dir,
            self.rejects_dir,
            self.audit_dir,
            self.silver_dir,
            self.gold_dir,
            self.enrichment_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
