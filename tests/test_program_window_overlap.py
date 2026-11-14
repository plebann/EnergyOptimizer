"""Selection of the Morning Charge Program Set from program start times."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from custom_components.energy_optimizer.utils.programs import (
    programs_overlapping_window,
)

UTC = timezone.utc

# Program layout used in the examples: P6 22:00, P1 01:30, P2 04:00, P3 06:00.
LAYOUT = [
    ("p6", time(22, 0)),
    ("p1", time(1, 30)),
    ("p2", time(4, 0)),
    ("p3", time(6, 0)),
]


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def test_window_across_midnight_covers_programs_overlapping_it() -> None:
    """23-04: P6 and P1 overlap; P2 starts exactly when the window ends."""
    result = programs_overlapping_window(
        LAYOUT,
        window_start=_at(10, 23),
        window_end=_at(11, 4),
        now=_at(10, 22, 30),
    )

    assert result == ["p6", "p1"]


def test_window_inside_one_program_and_the_next() -> None:
    """03-06: P1 is active at 03:00, then P2 starts; P3 starts at the end."""
    result = programs_overlapping_window(
        LAYOUT,
        window_start=_at(11, 3),
        window_end=_at(11, 6),
        now=_at(11, 2, 50),
    )

    assert result == ["p1", "p2"]


def test_window_ending_inside_second_program() -> None:
    """01-03: P6 until 01:30, then P1; P2 starts after the window ends."""
    result = programs_overlapping_window(
        LAYOUT,
        window_start=_at(11, 1),
        window_end=_at(11, 3),
        now=_at(11, 0, 50),
    )

    assert result == ["p6", "p1"]


def test_program_starting_before_window_end_is_included() -> None:
    result = programs_overlapping_window(
        [("p6", time(22, 0)), ("p1", time(1, 30)), ("p2", time(3, 30))],
        window_start=_at(10, 23),
        window_end=_at(11, 4),
        now=_at(10, 22, 30),
    )

    assert result == ["p6", "p1", "p2"]


def test_late_run_skips_programs_that_already_ended() -> None:
    """Run at 02:00 inside a 23-04 window: P6 ended at 01:30."""
    result = programs_overlapping_window(
        LAYOUT,
        window_start=_at(10, 23),
        window_end=_at(11, 4),
        now=_at(11, 2),
    )

    assert result == ["p1"]


def test_single_program_is_active_for_any_window() -> None:
    result = programs_overlapping_window(
        [("p2", time(4, 0))],
        window_start=_at(11, 1),
        window_end=_at(11, 3),
        now=_at(11, 0, 50),
    )

    assert result == ["p2"]


def test_repeated_hour_at_the_end_of_dst_includes_a_program_in_the_first_pass() -> None:
    """Warsaw 2026-10-25: 02:00 CEST to 02:00 CET contains the first 02:30."""
    from zoneinfo import ZoneInfo

    warsaw = ZoneInfo("Europe/Warsaw")
    window_start = datetime(2026, 10, 25, 0, 0, tzinfo=UTC).astimezone(warsaw)
    window_end = datetime(2026, 10, 25, 1, 0, tzinfo=UTC).astimezone(warsaw)

    result = programs_overlapping_window(
        [("p1", time(1, 30)), ("p2", time(2, 30)), ("p3", time(4, 0))],
        window_start=window_start,
        window_end=window_end,
        now=window_start - timedelta(minutes=5),
    )

    assert result == ["p1", "p2"]


def test_program_sharing_a_start_with_another_has_an_empty_interval() -> None:
    """P1 and P2 both at 04:00: only one of them is active after 04:00."""
    programs = [("p6", time(22, 0)), ("p1", time(4, 0)), ("p2", time(4, 0))]

    before_four = programs_overlapping_window(
        programs,
        window_start=_at(10, 23),
        window_end=_at(11, 3),
        now=_at(10, 22, 30),
    )
    across_four = programs_overlapping_window(
        programs,
        window_start=_at(10, 23),
        window_end=_at(11, 5),
        now=_at(10, 22, 30),
    )

    assert before_four == ["p6"]
    assert across_four == ["p6", "p2"]
