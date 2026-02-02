"""Program time helpers for Energy Optimizer."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from ..helpers import get_active_program_entity as _get_active_program_entity

_LOGGER = logging.getLogger(__name__)


def get_active_program_entity(
    hass: Any, config: dict[str, Any], current_time: datetime
) -> str | None:
    """Return active program SOC entity for current time.

    Delegates to legacy helper for now.
    """
    _LOGGER.debug("Resolving active program entity via legacy helper")
    return _get_active_program_entity(hass, config, current_time)
