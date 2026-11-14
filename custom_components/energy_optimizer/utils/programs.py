"""Program time helpers for Energy Optimizer."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta, timezone
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
    does not overlap it. A single program is active all day. Boundaries are
    compared as UTC instants, so a repeated DST hour is handled correctly.
    """
    reference = max(now, window_start).astimezone(timezone.utc)
    window_end_utc = window_end.astimezone(timezone.utc)
    tzinfo = max(now, window_start).tzinfo
    ordered = sorted(programs, key=lambda program: program[1])
    overlaps: list[tuple[datetime, _K]] = []
    for index, (key, start) in enumerate(ordered):
        next_start = ordered[(index + 1) % len(ordered)][1]
        end_offset = timedelta(days=0 if next_start > start else 1)
        day = reference.astimezone(tzinfo).date() - timedelta(days=1)
        while day <= window_end.date():
            interval_start = datetime.combine(day, start, tzinfo=tzinfo).astimezone(
                timezone.utc
            )
            interval_end = datetime.combine(
                day + end_offset, next_start, tzinfo=tzinfo
            ).astimezone(timezone.utc)
            if interval_start < window_end_utc and interval_end > reference:
                overlaps.append((max(interval_start, reference), key))
            day += timedelta(days=1)
    return [key for _, key in sorted(overlaps, key=lambda overlap: overlap[0])]
