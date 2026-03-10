"""Tests for export blocking/unblocking control based on price."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_INVERTER_EXPORT_SURPLUS_SWITCH,
    CONF_PRICE_SENSOR,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.export_block_control import (
    async_run_export_block_control,
)

pytestmark = pytest.mark.enable_socket

_ENTRY_ID = "entry-export"
_PRICE_ENTITY = "sensor.price"
_EXPORT_SURPLUS_SWITCH = "switch.inverter_export_surplus"
_SUN_ENTITY = "sun.sun"


def _state(value: str, attributes: dict | None = None) -> MagicMock:
    state = MagicMock()
    state.state = value
    state.attributes = attributes or {}
    return state


def _setup_hass(
    *,
    price: str,
    export_surplus_switch_state: str,
    sun_state: str = "above_horizon",
) -> MagicMock:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = _ENTRY_ID
    entry.domain = DOMAIN
    entry.options = {}
    entry.data = {
        CONF_PRICE_SENSOR: _PRICE_ENTITY,
        CONF_INVERTER_EXPORT_SURPLUS_SWITCH: _EXPORT_SURPLUS_SWITCH,
    }
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry

    states = {
        _PRICE_ENTITY: _state(price),
        _EXPORT_SURPLUS_SWITCH: _state(export_surplus_switch_state),
        _SUN_ENTITY: _state(sun_state),
    }
    hass.states.get.side_effect = lambda entity_id: states.get(entity_id)
    hass.services.async_call = AsyncMock()
    hass.data = {DOMAIN: {_ENTRY_ID: {}}}
    return hass


@pytest.mark.asyncio
async def test_blocks_export_when_price_negative_and_not_blocked() -> None:
    """Turn switch off when price is negative and export is enabled."""
    hass = _setup_hass(price="-50", export_surplus_switch_state="on")

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once_with(
        "switch",
        "turn_off",
        {"entity_id": _EXPORT_SURPLUS_SWITCH},
        blocking=True,
        context=hass.services.async_call.call_args.kwargs.get("context"),
    )


@pytest.mark.asyncio
async def test_unblocks_export_when_price_positive_and_blocked() -> None:
    """Turn switch on when price is positive and export is blocked."""
    hass = _setup_hass(price="50", export_surplus_switch_state="off")

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once_with(
        "switch",
        "turn_on",
        {"entity_id": _EXPORT_SURPLUS_SWITCH},
        blocking=True,
        context=hass.services.async_call.call_args.kwargs.get("context"),
    )


@pytest.mark.asyncio
async def test_no_action_when_negative_and_already_blocked() -> None:
    """Do nothing when price is negative and export is already blocked."""
    hass = _setup_hass(price="-20", export_surplus_switch_state="off")

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_no_action_when_positive_and_already_unblocked() -> None:
    """Do nothing when price is positive and export is already unblocked."""
    hass = _setup_hass(price="20", export_surplus_switch_state="on")

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_no_action_when_sun_not_above_horizon() -> None:
    """Do nothing when sun is below horizon."""
    hass = _setup_hass(
        price="-20",
        export_surplus_switch_state="on",
        sun_state="below_horizon",
    )

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_not_called()
