"""Tests for morning sell decision engine logic."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_EXPORT_POWER_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MIN_SOC,
    CONF_MIN_SOC_PV,
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
    entry.options = {}
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
                "battery_space_sensor": SimpleNamespace(
                    entity_id="sensor.energy_optimizer_battery_space"
                ),
            }
        }
    }
    return hass


def _base_config() -> dict[str, object]:
    return {
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_PROG3_SOC_ENTITY: "number.prog3_soc",
        CONF_MORNING_MAX_PRICE_SENSOR: "sensor.morning_price",
        CONF_EVENING_MAX_PRICE_SENSOR: "sensor.evening_price",
        CONF_MIN_ARBITRAGE_PRICE: 400.0,
        CONF_WORK_MODE_ENTITY: "select.work_mode",
        CONF_EXPORT_POWER_ENTITY: "number.export_power",
        CONF_PV_PRODUCTION_SENSOR: "sensor.pv_today",
        CONF_BATTERY_CAPACITY_AH: 37,
        CONF_BATTERY_VOLTAGE: 640,
        CONF_BATTERY_EFFICIENCY: 0.9,
        CONF_MIN_SOC: 20,
        CONF_MIN_SOC_PV: 12,
        CONF_TEST_MODE: False,
    }


def _base_states() -> dict[str, str]:
    return {
        "sensor.battery_soc": "90",
        "number.prog3_soc": "50",
        "sensor.morning_price": "250",
        "sensor.evening_price": "200",
        "sensor.pv_today": "8",
        "sensor.energy_optimizer_battery_space": "3",
    }


def _patch_common(monkeypatch: pytest.MonkeyPatch, outcomes: list) -> None:
    async def _capture_log(hass, entry, outcome, context, logger):
        outcomes.append(outcome)

    class _FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

    monkeypatch.setattr(
        f"{SELL_BASE}.log_decision_unified",
        _capture_log,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.Store",
        _FakeStore,
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
    states["sensor.evening_price"] = "50"
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
async def test_morning_sell_surplus_above_free_space_but_morning_not_higher_no_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.morning_price"] = "100"
    states["sensor.evening_price"] = "150"
    states["sensor.energy_optimizer_battery_space"] = "3"
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

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].details["surplus_selection_reason"] == "pv_fit_fallback_from_free_space"


@pytest.mark.asyncio
async def test_morning_sell_surplus_below_free_space_and_to_22_not_above_no_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.energy_optimizer_battery_space"] = "8"
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
        lambda **kwargs: (3.0, 2.0, 1.0, kwargs["end_hour"], False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    surplus_calls = iter([5.0, 6.0])
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: next(surplus_calls),
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].details["surplus_selection_reason"] == "surplus_to_sunset_not_above_free_space"


@pytest.mark.asyncio
async def test_morning_sell_surplus_below_free_space_and_to_22_above_sells_min_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.energy_optimizer_battery_space"] = "8"
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
        lambda **kwargs: (3.0, 2.0, 1.0, kwargs["end_hour"], False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    surplus_calls = iter([5.0, 9.5])
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: next(surplus_calls),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.calculate_export_power",
        lambda *args, **kwargs: 600.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    assert outcomes[-1].details["selected_surplus_kwh"] == 1.5
    assert outcomes[-1].details["surplus_selection_reason"] == "surplus_to_sunset_above_free_space"


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
    assert "No eligible surplus energy" in (outcomes[-1].reason or "")


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
    assert outcomes[-1].details["end_hour"] == 13
    assert outcomes[-1].details["sufficiency_hour"] == 10


@pytest.mark.asyncio
async def test_morning_sell_uses_min_soc_pv_for_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    captured: dict[str, float] = {}

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{MORNING}.get_heat_pump_forecast_window", _hp)
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

    def _capture_reserve(current_soc, min_soc, *args, **kwargs):
        captured["min_soc"] = min_soc
        return 3.0

    monkeypatch.setattr(f"{MORNING}.calculate_battery_reserve", _capture_reserve)
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 0.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert captured["min_soc"] == 12.0


@pytest.mark.asyncio
async def test_morning_sell_clamps_target_soc_to_min_soc_when_sufficiency_not_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.battery_soc"] = "50"
    hass = _setup_hass(config, states)
    outcomes: list = []

    set_work_mode = AsyncMock()
    set_program_soc = AsyncMock()
    set_export_power = AsyncMock()

    async def _capture_log(hass, entry, outcome, context, logger):
        outcomes.append(outcome)

    class _FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

    monkeypatch.setattr(f"{SELL_BASE}.log_decision_unified", _capture_log)
    monkeypatch.setattr(f"{SELL_BASE}.Store", _FakeStore)
    monkeypatch.setattr(f"{SELL_BASE}.set_work_mode", set_work_mode)
    monkeypatch.setattr(f"{SELL_BASE}.set_program_soc", set_program_soc)
    monkeypatch.setattr(f"{SELL_BASE}.set_export_power", set_export_power)
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

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{MORNING}.get_heat_pump_forecast_window", _hp)
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
        lambda reserve, required, pv: 8.0,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.calculate_export_power",
        lambda *args, **kwargs: 1200.0,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.kwh_to_soc",
        lambda *args, **kwargs: 50.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    set_program_soc.assert_any_await(
        hass,
        "number.prog3_soc",
        20.0,
        entry=hass.config_entries.async_get_entry.return_value,
        logger=ANY,
        context=ANY,
    )


@pytest.mark.asyncio
async def test_morning_sell_clamps_target_soc_to_min_soc_pv_when_sufficiency_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.battery_soc"] = "50"
    hass = _setup_hass(config, states)
    outcomes: list = []

    set_work_mode = AsyncMock()
    set_program_soc = AsyncMock()
    set_export_power = AsyncMock()

    async def _capture_log(hass, entry, outcome, context, logger):
        outcomes.append(outcome)

    class _FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

    monkeypatch.setattr(f"{SELL_BASE}.log_decision_unified", _capture_log)
    monkeypatch.setattr(f"{SELL_BASE}.Store", _FakeStore)
    monkeypatch.setattr(f"{SELL_BASE}.set_work_mode", set_work_mode)
    monkeypatch.setattr(f"{SELL_BASE}.set_program_soc", set_program_soc)
    monkeypatch.setattr(f"{SELL_BASE}.set_export_power", set_export_power)
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

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{MORNING}.get_heat_pump_forecast_window", _hp)
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
        lambda **kwargs: (3.0, 2.0, 1.0, 13, True),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 8.0,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.calculate_export_power",
        lambda *args, **kwargs: 1200.0,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.kwh_to_soc",
        lambda *args, **kwargs: 50.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    set_program_soc.assert_any_await(
        hass,
        "number.prog3_soc",
        12.0,
        entry=hass.config_entries.async_get_entry.return_value,
        logger=ANY,
        context=ANY,
    )


