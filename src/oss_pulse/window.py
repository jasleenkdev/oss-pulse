"""Backfill window arithmetic. All times are UTC."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

# GH Archive publishes an hour shortly after it ends, so the previous day is only
# treated as complete once 02:00 UTC has passed.
PUBLISH_LAG_HOURS = 2


@dataclass(frozen=True)
class Window:
    start: date  # inclusive
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def hours(self) -> list[datetime]:
        return [
            datetime(self.start.year, self.start.month, self.start.day)
            + timedelta(hours=offset)
            for offset in range(self.days * 24)
        ]

    def __str__(self) -> str:
        return f"{self.start} to {self.end} ({self.days} days, {self.days * 24} hours)"


def last_complete_day(now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    return (now - timedelta(hours=PUBLISH_LAG_HOURS)).date() - timedelta(days=1)


def resolve_window(
    days: int = 30, end_date: date | None = None, now: datetime | None = None
) -> Window:
    if days < 1:
        raise ValueError("days must be at least 1")
    end = end_date or last_complete_day(now)
    return Window(start=end - timedelta(days=days - 1), end=end)
