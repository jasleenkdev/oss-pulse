from datetime import date, datetime

import pytest

from oss_pulse.window import last_complete_day, resolve_window


def test_window_covers_seven_complete_days():
    window = resolve_window(7, now=datetime(2026, 11, 5, 12, 0))
    assert (window.start, window.end) == (date(2026, 10, 29), date(2026, 11, 4))
    assert len(window.hours()) == 168
    assert window.hours()[0] == datetime(2026, 10, 29, 0)
    assert window.hours()[-1] == datetime(2026, 11, 4, 23)


def test_default_window_is_thirty_complete_days():
    window = resolve_window(now=datetime(2026, 11, 5, 12, 0))
    assert (window.start, window.end) == (date(2026, 10, 6), date(2026, 11, 4))
    assert len(window.hours()) == 720


def test_previous_day_is_not_complete_just_after_midnight():
    assert last_complete_day(datetime(2026, 11, 5, 1, 0)) == date(2026, 11, 3)
    assert last_complete_day(datetime(2026, 11, 5, 2, 0)) == date(2026, 11, 4)


def test_explicit_end_date_wins():
    assert resolve_window(2, date(2026, 1, 2)).start == date(2026, 1, 1)


def test_rejects_empty_window():
    with pytest.raises(ValueError):
        resolve_window(0)
