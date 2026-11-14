"""Regression: options flow must prefill grid_charge_current_entity.

The field is ``vol.Required`` in the control_entities step; without a
``default`` the edit form rendered it empty on every reopen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import voluptuous as vol

from custom_components.energy_optimizer.config_flow import EnergyOptimizerOptionsFlow
from custom_components.energy_optimizer.const import CONF_GRID_CHARGE_CURRENT_ENTITY


@pytest.mark.asyncio
async def test_options_control_entities_prefills_grid_charge_current_entity() -> None:
    entry = MagicMock(spec=["data", "options"])
    entry.data = {CONF_GRID_CHARGE_CURRENT_ENTITY: "number.grid_charge_current"}
    entry.options = {}

    result = await EnergyOptimizerOptionsFlow(entry).async_step_control_entities()

    marker = next(
        key
        for key in result["data_schema"].schema
        if key == CONF_GRID_CHARGE_CURRENT_ENTITY
    )
    assert isinstance(marker, vol.Required)
    assert marker.default() == "number.grid_charge_current"
