"""Tests for morning sell decision engine logic."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_EXPORT_POWER_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MORNING_MAX_PRICE_SENSOR,
    CONF_PROG3_SOC_ENTITY,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_TEST_MODE,
    CONF_WORK_MODE_ENTITY,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.morning_sell import (
    async_run_morning_sell,
)

pytestmark = pytest.mark.enable_socket

SELL_BASE = "custom_components.energy_optimizer.decision_engine.sell_base"
MORNING = "custom_components.energy_optimizer.decision_engine.morning_sell"


def _state(value: str) -> MagicMock:
    state = MagicMock()
    state.state = value
    state.attributes = {}
    return state


def _setup_hass(config: dict[str, object], states: dict[str, str]) -> MagicMock:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.domain = DOMAIN
    entry.data = config
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry
    hass.states.get.side_effect = lambda entity_id: (
        _state(states[entity_id]) if entity_id in states else None
    )
    hass.services.async_call = AsyncMock()

    mock_opt_sensor = MagicMock()
    mock_opt_sensor.log_optimization = MagicMock()
    mock_hist_sensor = MagicMock()
    mock_hist_sensor.add_entry = MagicMock()

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                "last_optimization_sensor": mock_opt_sensor,
                "optimization_history_sensor": mock_hist_sensor,
            }
        }
    }
    return hass


def _base_config() -> dict[str, object]:
    return {
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_PROG3_SOC_ENTITY: "number.prog3_soc",
        CONF_MORNING_MAX_PRICE_SENSOR: "sensor.morning_price",
        CONF_MIN_ARBITRAGE_PRICE: 400.0,
        CONF_WORK_MODE_ENTITY: "select.work_mode",
        CONF_EXPORT_POWER_ENTITY: "number.export_power",
        CONF_PV_PRODUCTION_SENSOR: "sensor.pv_today",
        CONF_BATTERY_CAPACITY_AH: 37,
        CONF_BATTERY_VOLTAGE: 640,
        CONF_BATTERY_EFFICIENCY: 0.9,
        CONF_TEST_MODE: False,
    }


def _base_states() -> dict[str, str]:
    return {
        "sensor.battery_soc": "90",
        "number.prog3_soc": "50",
        "sensor.morning_price": "250",
        "sensor.pv_today": "8",
    }


def _patch_common(monkeypatch: pytest.MonkeyPatch, outcomes: list) -> None:
    async def _capture_log(hass, entry, outcome, context, logger):
        outcomes.append(outcome)

    monkeypatch.setattr(
        f"{SELL_BASE}.log_decision_unified",
        _capture_log,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_work_mode",
        AsyncMock(),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_program_soc",
        AsyncMock(),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_export_power",
        AsyncMock(),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.utcnow",
        lambda: datetime(2026, 2, 24, 7, 0, 0),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.as_local",
        lambda _dt: SimpleNamespace(hour=7),
    )
    monkeypatch.setattr(
        f"{MORNING}.build_hourly_usage_array",
        lambda config, get_state, daily_load_fallback=None: [0.0] * 24,
    )
    monkeypatch.setattr(
        f"{MORNING}.resolve_tariff_end_hour",
        lambda hass, config, default_hour=13: 13,
    )


@pytest.mark.asyncio
async def test_morning_sell_executes_with_surplus_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.morning_price"] = "100"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 5.0,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.calculate_export_power",
        lambda *args, **kwargs: 1200.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"


@pytest.mark.asyncio
async def test_morning_sell_no_surplus_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (1.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 3.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 0.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert "No surplus energy" in (outcomes[-1].reason or "")


@pytest.mark.asyncio
async def test_morning_sell_caps_window_by_sufficiency(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {8: 1.0, 9: 1.0, 10: 1.0, 11: 1.0, 12: 1.0}

    def _pv(*args, **kwargs):
        return 5.0, {8: 0.5, 9: 1.0, 10: 1.0, 11: 1.0, 12: 1.5}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        _pv,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (5.0, 2.0, 1.0, 10, True),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 4.0,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.calculate_export_power",
        lambda *args, **kwargs: 1400.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    assert outcomes[-1].full_details["end_hour"] == 10


