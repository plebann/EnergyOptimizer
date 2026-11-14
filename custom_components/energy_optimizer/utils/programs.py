"""Program time helpers for Energy Optimizer."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
import logging
from typing import Any, TypeVar

from ..helpers import get_active_program_entity as _get_active_program_entity

_LOGGER = logging.getLogger(__name__)

_K = TypeVar("_K")


def get_active_program_entity(
    hass: Any, config: dict[str, Any], current_time: datetime
) -> str | None:
    """Return active program SOC entity for current time.

    Delegates to legacy helper for now.
    """
    _LOGGER.debug("Resolving active program entity via legacy helper")
    return _get_active_program_entity(hass, config, current_time)


def programs_overlapping_window(
    programs: Sequence[tuple[_K, time]],
    *,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> list[_K]:
    """Return program keys active at some point of the window, in time order.

    A program is active from its start time up to the next program's start
    time (wrapping past midnight). The window is measured from the later of
    ``now`` and ``window_start``; a program starting exactly at the window end
    does not overlap it. A single program is active all day.
    """
    reference = max(now, window_start)
    ordered = sorted(programs, key=lambda program: program[1])
    overlaps: list[tuple[datetime, _K]] = []
    for index, (key, start) in enumerate(ordered):
        next_start = ordered[(index + 1) % len(ordered)][1]
        length = (
            timedelta(hours=next_start.hour, minutes=next_start.minute)
            - timedelta(hours=start.hour, minutes=start.minute)
        )
        if length <= timedelta(0):
            length += timedelta(days=1)
        day = reference.date() - timedelta(days=1)
        while day <= window_end.date():
            interval_start = datetime.combine(day, start, tzinfo=reference.tzinfo)
            interval_end = interval_start + length
            if interval_start < window_end and interval_end > reference:
                overlaps.append((max(interval_start, reference), key))
            day += timedelta(days=1)
    return [key for _, key in sorted(overlaps, key=lambda overlap: overlap[0])]
