"""Tests for forecast-aware export blocking."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_SOC_SENSOR,
    CONF_BEV_CHARGING_BINARY_SENSOR,
    CONF_BEV_CHARGING_POWER_SENSOR,
    CONF_INVERTER_EXPORT_SURPLUS_SWITCH,
    CONF_INVERTER_OFFGRID_SWITCH,
    CONF_LOAD_USAGE_12_16,
    CONF_PRICE_SENSOR,
    CONF_PV_FORECAST_TODAY,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.export_block_control import (
    async_run_export_block_control,
)

_ENTRY_ID = "entry-export"
_PRICE_ENTITY = "sensor.price"
_PV_ENTITY = "sensor.pv_forecast_today"
_LOAD_ENTITY = "sensor.load_usage_12_16"
_SOC_ENTITY = "sensor.battery_soc"
_EXPORT_SURPLUS_SWITCH = "switch.inverter_export_surplus"
_OFFGRID_SWITCH = "switch.inverter_offgrid"
_BEV_CHARGING_SENSOR = "binary_sensor.bev_charging"
_BEV_POWER_SENSOR = "sensor.bev_charging_power"
_SUN_ENTITY = "sun.sun"
_NOW = datetime(2026, 8, 1, 12, 1, tzinfo=ZoneInfo("Europe/Warsaw"))


def _state(value: str, attributes: dict | None = None) -> SimpleNamespace:
    """Build a minimal Home Assistant state."""
    return SimpleNamespace(state=value, attributes=attributes or {})


def _setup_hass(
    *,
    price: str = "-1.0",
    pv_kwh: float = 20.0,
    export_switch_state: str = "on",
    offgrid_switch_state: str = "off",
    bev_charging: str | None = None,
    bev_power_w: float | None = None,
    include_forecast: bool = True,
) -> MagicMock:
    """Build hass with a valid current-hour energy balance at 12:00."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = _ENTRY_ID
    entry.domain = DOMAIN
    entry.options = {}
    entry.data = {
        CONF_PRICE_SENSOR: _PRICE_ENTITY,
        CONF_PV_FORECAST_TODAY: _PV_ENTITY,
        CONF_LOAD_USAGE_12_16: _LOAD_ENTITY,
        CONF_BATTERY_SOC_SENSOR: _SOC_ENTITY,
        CONF_INVERTER_EXPORT_SURPLUS_SWITCH: _EXPORT_SURPLUS_SWITCH,
        CONF_INVERTER_OFFGRID_SWITCH: _OFFGRID_SWITCH,
    }
    if bev_charging is not None:
        entry.data[CONF_BEV_CHARGING_BINARY_SENSOR] = _BEV_CHARGING_SENSOR
    if bev_power_w is not None:
        entry.data[CONF_BEV_CHARGING_POWER_SENSOR] = _BEV_POWER_SENSOR

    forecast = (
        [{"period_start": _NOW.isoformat(), "pv_estimate": pv_kwh}]
        if include_forecast
        else None
    )
    states = {
        _SUN_ENTITY: _state("above_horizon"),
        _PRICE_ENTITY: _state(price),
        _PV_ENTITY: _state("0", {"detailedHourly": forecast}),
        _LOAD_ENTITY: _state("1.0"),
        _SOC_ENTITY: _state("50"),
        _EXPORT_SURPLUS_SWITCH: _state(export_switch_state),
        _OFFGRID_SWITCH: _state(offgrid_switch_state),
    }
    if bev_charging is not None:
        states[_BEV_CHARGING_SENSOR] = _state(bev_charging)
    if bev_power_w is not None:
        states[_BEV_POWER_SENSOR] = _state(str(bev_power_w))

    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry
    hass.states.get.side_effect = states.get
    hass.services.async_call = AsyncMock()
    hass.data = {
        DOMAIN: {
            _ENTRY_ID: {
                "export_block_offgrid_threshold": SimpleNamespace(native_value=3.5),
            }
        }
    }
    return hass


def _service_calls(hass: MagicMock) -> list[tuple[str, str, str]]:
    """Return simplified switch service calls."""
    return [
        (
            service_call.args[0],
            service_call.args[1],
            service_call.args[2]["entity_id"],
        )
        for service_call in hass.services.async_call.call_args_list
    ]


@pytest.mark.asyncio
async def test_high_surplus_blocks_export_then_enters_offgrid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """High predicted surplus blocks export before off-grid activation."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.export_block_control.dt_util.now",
        lambda: _NOW,
    )
    hass = _setup_hass()

    decision = await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    assert _service_calls(hass) == [
        ("switch", "turn_off", _EXPORT_SURPLUS_SWITCH),
        ("switch", "turn_on", _OFFGRID_SWITCH),
    ]
    assert decision["action"] == "block_export_offgrid"
    assert decision["forecast_export_surplus_kwh"] > 3.5


@pytest.mark.asyncio
async def test_low_surplus_blocks_export_but_keeps_grid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Low surplus uses only the export switch and reconnects the grid."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.export_block_control.dt_util.now",
        lambda: _NOW,
    )
    hass = _setup_hass(
        pv_kwh=13.0,
        export_switch_state="on",
        offgrid_switch_state="on",
    )

    decision = await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    assert _service_calls(hass) == [
        ("switch", "turn_off", _EXPORT_SURPLUS_SWITCH),
        ("switch", "turn_off", _OFFGRID_SWITCH),
    ]
    assert decision["action"] == "block_export_with_grid"


@pytest.mark.asyncio
async def test_bev_absorbing_surplus_keeps_export_and_grid_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active BEV charging never uses off-grid and can permit export."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.export_block_control.dt_util.now",
        lambda: _NOW,
    )
    hass = _setup_hass(
        bev_charging="on",
        bev_power_w=8000.0,
        export_switch_state="off",
        offgrid_switch_state="on",
    )

    decision = await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    assert _service_calls(hass) == [
        ("switch", "turn_off", _OFFGRID_SWITCH),
        ("switch", "turn_on", _EXPORT_SURPLUS_SWITCH),
    ]
    assert decision["reason"] == "bev_absorbs_surplus"
    assert decision["bev_charging_kwh"] == 8.0


@pytest.mark.asyncio
async def test_bev_with_high_surplus_never_enters_offgrid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active BEV charging falls back to the export switch for high surplus."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.export_block_control.dt_util.now",
        lambda: _NOW,
    )
    hass = _setup_hass(bev_charging="on", bev_power_w=0.0)

    decision = await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    assert _service_calls(hass) == [("switch", "turn_off", _EXPORT_SURPLUS_SWITCH)]
    assert decision["action"] == "block_export_with_grid"
    assert decision["bev_charging"] is True


@pytest.mark.asyncio
async def test_incomplete_balance_keeps_export_and_grid_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing forecast data restores normal operation instead of restricting it."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.export_block_control.dt_util.now",
        lambda: _NOW,
    )
    hass = _setup_hass(
        include_forecast=False,
        export_switch_state="off",
        offgrid_switch_state="on",
    )

    decision = await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    assert _service_calls(hass) == [
        ("switch", "turn_off", _OFFGRID_SWITCH),
        ("switch", "turn_on", _EXPORT_SURPLUS_SWITCH),
    ]
    assert decision["reason"] == "incomplete_energy_balance"


@pytest.mark.asyncio
async def test_positive_price_restores_grid_before_export() -> None:
    """A positive price restores grid operation before enabling export."""
    hass = _setup_hass(
        price="0.05",
        export_switch_state="off",
        offgrid_switch_state="on",
    )

    decision = await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    assert _service_calls(hass) == [
        ("switch", "turn_off", _OFFGRID_SWITCH),
        ("switch", "turn_on", _EXPORT_SURPLUS_SWITCH),
    ]
    assert decision["reason"] == "positive_sell_price"


@pytest.mark.asyncio
async def test_effectively_zero_price_uses_export_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A price that rounds to zero remains eligible for blocking."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.export_block_control.dt_util.now",
        lambda: _NOW,
    )
    hass = _setup_hass(price="0.04")

    decision = await async_run_export_block_control(hass, entry_id=_ENTRY_ID)

    assert decision["action"] == "block_export_offgrid"
    assert hass.services.async_call.await_count == 2
