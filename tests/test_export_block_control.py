"""Tests for export blocking/unblocking control based on price."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_INVERTER_EXPORT_SURPLUS_SWITCH,
    CONF_INVERTER_OFFGRID_SWITCH,
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
_OFFGRID_SWITCH = "switch.inverter_offgrid"
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


def _setup_hass_with_offgrid(
    *,
    price: str,
    offgrid_switch_state: str | None,
    export_surplus_switch_state: str = "on",
    include_export_surplus_switch: bool = True,
    sun_state: str = "above_horizon",
) -> MagicMock:
    hass = _setup_hass(
        price=price,
        export_surplus_switch_state=export_surplus_switch_state,
        sun_state=sun_state,
    )
    entry = hass.config_entries.async_entries.return_value[0]
    entry.data[CONF_INVERTER_OFFGRID_SWITCH] = _OFFGRID_SWITCH
    if not include_export_surplus_switch:
        entry.data.pop(CONF_INVERTER_EXPORT_SURPLUS_SWITCH)

    states = {
        _PRICE_ENTITY: _state(price),
        _SUN_ENTITY: _state(sun_state),
    }
    if include_export_surplus_switch:
        states[_EXPORT_SURPLUS_SWITCH] = _state(export_surplus_switch_state)
    if offgrid_switch_state is not None:
        states[_OFFGRID_SWITCH] = _state(offgrid_switch_state)
    hass.states.get.side_effect = lambda entity_id: states.get(entity_id)
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


@pytest.mark.asyncio
async def test_offgrid_turns_on_when_price_zero_and_switch_off() -> None:
    """Turn off-grid switch on when price is effectively zero."""
    hass = _setup_hass_with_offgrid(price="0.0", offgrid_switch_state="off")

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once_with(
        "switch",
        "turn_on",
        {"entity_id": _OFFGRID_SWITCH},
        blocking=True,
        context=hass.services.async_call.call_args.kwargs.get("context"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("price", "offgrid_switch_state", "expected_service"),
    [
        ("0.04", "off", "turn_on"),  # rounds to 0.0 at 1dp
        ("0.05", "on", "turn_off"),  # rounds above 0.0 at 1dp
    ],
)
async def test_offgrid_zero_price_threshold_boundary(
    price: str, offgrid_switch_state: str, expected_service: str
) -> None:
    """Validate rounding-based zero-price threshold behavior."""
    hass = _setup_hass_with_offgrid(price=price, offgrid_switch_state=offgrid_switch_state)

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once_with(
        "switch",
        expected_service,
        {"entity_id": _OFFGRID_SWITCH},
        blocking=True,
        context=hass.services.async_call.call_args.kwargs.get("context"),
    )


@pytest.mark.asyncio
async def test_offgrid_no_action_when_price_zero_and_already_on() -> None:
    """Do nothing when price is effectively zero and off-grid is already on."""
    hass = _setup_hass_with_offgrid(price="0.0", offgrid_switch_state="on")

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_offgrid_surplus_switch_not_touched_when_offgrid_configured() -> None:
    """Use only off-grid switch when both off-grid and surplus switches exist."""
    hass = _setup_hass_with_offgrid(
        price="0.0",
        offgrid_switch_state="off",
        export_surplus_switch_state="on",
    )

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once()
    call_args = hass.services.async_call.call_args
    assert call_args.args[:3] == (
        "switch",
        "turn_on",
        {"entity_id": _OFFGRID_SWITCH},
    )


@pytest.mark.asyncio
async def test_offgrid_turns_on_without_export_surplus_switch_configured() -> None:
    """Use off-grid path when legacy surplus switch is not configured."""
    hass = _setup_hass_with_offgrid(
        price="0.0",
        offgrid_switch_state="off",
        include_export_surplus_switch=False,
    )

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once_with(
        "switch",
        "turn_on",
        {"entity_id": _OFFGRID_SWITCH},
        blocking=True,
        context=hass.services.async_call.call_args.kwargs.get("context"),
    )


@pytest.mark.asyncio
async def test_offgrid_turns_off_when_price_positive_and_switch_on() -> None:
    """Turn off-grid switch off when price is positive."""
    hass = _setup_hass_with_offgrid(price="50", offgrid_switch_state="on")

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once_with(
        "switch",
        "turn_off",
        {"entity_id": _OFFGRID_SWITCH},
        blocking=True,
        context=hass.services.async_call.call_args.kwargs.get("context"),
    )


@pytest.mark.asyncio
async def test_offgrid_no_action_when_price_positive_and_already_off() -> None:
    """Do nothing when price is positive and off-grid is already off."""
    hass = _setup_hass_with_offgrid(price="50", offgrid_switch_state="off")

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_offgrid_entity_unavailable_skip() -> None:
    """Do nothing when configured off-grid switch is unavailable."""
    hass = _setup_hass_with_offgrid(price="0.0", offgrid_switch_state=None)

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_offgrid_no_action_when_sun_not_above_horizon() -> None:
    """Do nothing when sun is below horizon and off-grid switch is configured."""
    hass = _setup_hass_with_offgrid(
        price="0.0",
        offgrid_switch_state="off",
        sun_state="below_horizon",
    )

    await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_not_called()
