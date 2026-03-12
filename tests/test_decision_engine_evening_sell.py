"""Tests for evening sell decision engine logic."""
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
    CONF_EVENING_MAX_PRICE_HOUR_SENSOR,
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR,
    CONF_EVENING_SECOND_MAX_PRICE_SENSOR,
    CONF_EXPORT_POWER_ENTITY,
    CONF_MAX_EXPORT_POWER,
    CONF_MAX_SELL_ENERGY_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_PROG5_SOC_ENTITY,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_TEST_MODE,
    CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR,
    CONF_WORK_MODE_ENTITY,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.evening_sell import (
    async_run_evening_sell,
)
from custom_components.energy_optimizer.decision_engine.sell_base import SellRequest
from custom_components.energy_optimizer.utils.logging import DecisionOutcome

pytestmark = pytest.mark.enable_socket

SELL_BASE = "custom_components.energy_optimizer.decision_engine.sell_base"
EVENING = "custom_components.energy_optimizer.decision_engine.evening_sell"


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
            }
        }
    }
    return hass


def _base_config() -> dict[str, object]:
    return {
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_PROG5_SOC_ENTITY: "number.prog5_soc",
        CONF_EVENING_MAX_PRICE_SENSOR: "sensor.evening_price",
        CONF_MIN_ARBITRAGE_PRICE: 400.0,
        CONF_MAX_EXPORT_POWER: 12000,
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
        "number.prog5_soc": "50",
        "sensor.evening_price": "700",
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
    class _StoreStub:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def async_save(self, _data: dict[str, object]) -> None:
            return None

        async def async_load(self) -> dict[str, object] | None:
            return None

    monkeypatch.setattr(
        f"{SELL_BASE}.Store",
        _StoreStub,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.utcnow",
        lambda: datetime(2026, 2, 24, 16, 0, 0),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.as_local",
        lambda _dt: SimpleNamespace(hour=17),
    )
    monkeypatch.setattr(
        f"{EVENING}.build_hourly_usage_array",
        lambda config, get_state, daily_load_fallback=None: [0.0] * 24,
    )
    monkeypatch.setattr(
        f"{EVENING}.resolve_tariff_start_hour",
        lambda hass, config, default_hour=22: 22,
    )
    monkeypatch.setattr(
        f"{EVENING}.resolve_tariff_end_hour",
        lambda hass, config, default_hour=13: 13,
    )


class _CountingStoreStub:
    save_calls: list[dict[str, object]] = []
    load_data: dict[str, object] | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def async_save(self, data: dict[str, object]) -> None:
        self.__class__.save_calls.append(dict(data))

    async def async_load(self) -> dict[str, object] | None:
        return self.__class__.load_data


def _sell_request(surplus_kwh: float) -> SellRequest:
    return SellRequest(
        surplus_kwh=surplus_kwh,
        build_outcome_fn=lambda target, surplus, export: DecisionOutcome(
            scenario="Evening Peak Sell",
            action_type="sell",
            summary=f"Sell {surplus:.1f} kWh",
            details={"target_soc": target, "surplus_kwh": surplus, "export_power_w": export},
        ),
        build_no_action_fn=lambda surplus: DecisionOutcome(
            scenario="Evening Peak Sell",
            action_type="no_action",
            summary="No evening peak sell action",
            reason="No sellable surplus remaining",
            details={"surplus_kwh": surplus},
        ),
    )


@pytest.mark.asyncio
async def test_evening_sell_high_sell_action_type(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_surplus_energy",
        lambda reserve, required, pv: 5.0,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.calculate_export_power",
        lambda *args, **kwargs: 1200.0,
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "high_sell"


@pytest.mark.asyncio
async def test_evening_sell_high_sell_no_surplus_no_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 2.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_surplus_energy",
        lambda reserve, required, pv: 0.0,
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert "No surplus energy available" in (outcomes[-1].reason or "")


@pytest.mark.asyncio
async def test_evening_sell_surplus_sell_no_sufficiency_uses_full_tariff_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.evening_price"] = "350"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 12.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 1.0, 13, False),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"


@pytest.mark.asyncio
async def test_evening_sell_skips_when_tomorrow_morning_price_is_higher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR] = "sensor.tomorrow_morning_price"
    states = _base_states()
    states["sensor.evening_price"] = "700"
    states["sensor.tomorrow_morning_price"] = "750"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    set_work_mode_mock = AsyncMock()
    set_program_soc_mock = AsyncMock()
    set_export_power_mock = AsyncMock()
    monkeypatch.setattr(
        f"{SELL_BASE}.set_work_mode",
        set_work_mode_mock,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_program_soc",
        set_program_soc_mock,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_export_power",
        set_export_power_mock,
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert "not higher than tomorrow morning" in (outcomes[-1].reason or "").lower()
    set_work_mode_mock.assert_not_awaited()
    set_program_soc_mock.assert_not_awaited()
    set_export_power_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_evening_sell_surplus_sell_success(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.evening_price"] = "350"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(hass, config, start_hour, end_hour):
        if start_hour == 0:
            return 1.0, {}
        return 1.0, {}

    def _pv(hass, config, start_hour, end_hour, **kwargs):
        if start_hour == 0:
            return 3.0, {}
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        _pv,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 12.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 2.0, 5, True),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.calculate_export_power",
        lambda *args, **kwargs: 1500.0,
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    assert outcomes[-1].details["sufficiency_hour"] == 5


@pytest.mark.asyncio
async def test_evening_sell_surplus_sell_no_surplus(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.evening_price"] = "350"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (1.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 5.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 2.0, 8, True),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert "No surplus energy" in (outcomes[-1].reason or "")


@pytest.mark.asyncio
async def test_evening_sell_surplus_no_action_required_uses_sufficiency_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.evening_price"] = "350"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (0.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 5.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 2.0, 8, True),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].details["required_kwh"] == 9.0


@pytest.mark.asyncio
async def test_evening_sell_max_sell_energy_clamp_and_fail_open(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = _base_config()
    config[CONF_MAX_SELL_ENERGY_ENTITY] = "sensor.max_sell_energy"
    states = _base_states()
    states["sensor.max_sell_energy"] = "3.0"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{EVENING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(f"{EVENING}.get_pv_forecast_window", lambda *args, **kwargs: (2.0, {}))
    monkeypatch.setattr(f"{EVENING}.calculate_losses", lambda *args, **kwargs: (0.0, 0.0))
    monkeypatch.setattr(f"{EVENING}.calculate_battery_reserve", lambda *args, **kwargs: 10.0)
    monkeypatch.setattr(f"{EVENING}.calculate_surplus_energy", lambda reserve, required, pv: 7.0)
    monkeypatch.setattr(f"{SELL_BASE}.calculate_export_power", lambda *args, **kwargs: 1200.0)

    kwh_calls: list[float] = []

    def _kwh_to_soc(kwh: float, capacity_ah: float, voltage: float) -> float:
        kwh_calls.append(kwh)
        return 10.0

    monkeypatch.setattr(f"{SELL_BASE}.kwh_to_soc", _kwh_to_soc)

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert kwh_calls[-1] == 3.0

    caplog.clear()
    kwh_calls.clear()
    del states["sensor.max_sell_energy"]

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert kwh_calls[-1] == 7.0


@pytest.mark.asyncio
async def test_evening_sell_a_first_splits_primary_then_secondary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_EVENING_MAX_PRICE_HOUR_SENSOR] = "sensor.evening_hour"
    config[CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR] = "sensor.evening_second_hour"
    config[CONF_EVENING_SECOND_MAX_PRICE_SENSOR] = "sensor.evening_second_price"
    config[CONF_MAX_EXPORT_POWER] = 9000
    states = _base_states()
    states["sensor.evening_hour"] = "18"
    states["sensor.evening_second_hour"] = "19"
    states["sensor.evening_second_price"] = "600"
    states["sensor.pv_today"] = "20"
    states["sensor.tomorrow_morning"] = "500"
    config[CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR] = "sensor.tomorrow_morning"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _compute_base(self):
        return _sell_request(12.0 if self._is_primary else 3.0)

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)
    monkeypatch.setattr(f"{SELL_BASE}.calculate_export_power", lambda *args, **kwargs: 1100.0)
    _CountingStoreStub.save_calls = []
    _CountingStoreStub.load_data = None
    monkeypatch.setattr(f"{SELL_BASE}.Store", _CountingStoreStub)

    kwh_calls: list[float] = []

    def _kwh_to_soc(kwh: float, capacity_ah: float, voltage: float) -> float:
        kwh_calls.append(kwh)
        return 10.0

    monkeypatch.setattr(f"{SELL_BASE}.kwh_to_soc", _kwh_to_soc)

    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=True,
        is_first=True,
    )
    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=False,
        is_first=False,
    )

    assert kwh_calls == [9.0, 3.0]
    assert len(_CountingStoreStub.save_calls) == 1


@pytest.mark.asyncio
async def test_evening_sell_b_first_sells_only_overflow_before_primary_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_EVENING_MAX_PRICE_HOUR_SENSOR] = "sensor.evening_hour"
    config[CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR] = "sensor.evening_second_hour"
    config[CONF_EVENING_SECOND_MAX_PRICE_SENSOR] = "sensor.evening_second_price"
    config[CONF_MAX_EXPORT_POWER] = 9000
    states = _base_states()
    states["sensor.evening_hour"] = "19"
    states["sensor.evening_second_hour"] = "18"
    states["sensor.evening_second_price"] = "600"
    states["sensor.pv_today"] = "20"
    states["sensor.tomorrow_morning"] = "500"
    config[CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR] = "sensor.tomorrow_morning"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _compute_base(self):
        if not self._is_primary and self._is_first:
            return _sell_request(12.0)
        return _sell_request(9.0)

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)
    monkeypatch.setattr(f"{SELL_BASE}.calculate_export_power", lambda *args, **kwargs: 900.0)
    _CountingStoreStub.save_calls = []
    _CountingStoreStub.load_data = None
    monkeypatch.setattr(f"{SELL_BASE}.Store", _CountingStoreStub)

    kwh_calls: list[float] = []

    def _kwh_to_soc(kwh: float, capacity_ah: float, voltage: float) -> float:
        kwh_calls.append(kwh)
        return 10.0

    monkeypatch.setattr(f"{SELL_BASE}.kwh_to_soc", _kwh_to_soc)

    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=False,
        is_first=True,
    )
    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=True,
        is_first=False,
    )

    assert kwh_calls == [3.0, 9.0]
    assert len(_CountingStoreStub.save_calls) == 1


@pytest.mark.asyncio
async def test_evening_sell_second_window_early_exit_restores_active_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_EVENING_MAX_PRICE_HOUR_SENSOR] = "sensor.evening_hour"
    config[CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR] = "sensor.evening_second_hour"
    config[CONF_EVENING_SECOND_MAX_PRICE_SENSOR] = "sensor.evening_second_price"
    config[CONF_MAX_EXPORT_POWER] = 9000
    states = _base_states()
    states["sensor.evening_hour"] = "18"
    states["sensor.evening_second_hour"] = "19"
    states["sensor.evening_second_price"] = "400"
    states["sensor.tomorrow_morning"] = "500"
    config[CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR] = "sensor.tomorrow_morning"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _compute_base(self):
        return _sell_request(8.0)

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)
    monkeypatch.setattr(f"{SELL_BASE}.calculate_export_power", lambda *args, **kwargs: 800.0)

    restore_mock = AsyncMock()
    monkeypatch.setattr(f"{EVENING}.async_handle_sell_restore", restore_mock)

    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=True,
        is_first=True,
    )
    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=False,
        is_first=False,
    )

    assert restore_mock.await_count == 1
    assert outcomes[-1].action_type == "sell_restore"


@pytest.mark.asyncio
async def test_evening_sell_second_window_zero_surplus_restores_active_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_EVENING_MAX_PRICE_HOUR_SENSOR] = "sensor.evening_hour"
    config[CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR] = "sensor.evening_second_hour"
    config[CONF_EVENING_SECOND_MAX_PRICE_SENSOR] = "sensor.evening_second_price"
    config[CONF_MAX_EXPORT_POWER] = 9000
    states = _base_states()
    states["sensor.evening_hour"] = "18"
    states["sensor.evening_second_hour"] = "19"
    states["sensor.evening_second_price"] = "600"
    states["sensor.tomorrow_morning"] = "500"
    config[CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR] = "sensor.tomorrow_morning"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _compute_base(self):
        if self._is_primary:
            return _sell_request(8.0)
        return DecisionOutcome(
            scenario="Evening Peak Sell",
            action_type="no_action",
            summary="No evening peak sell action",
            reason="No surplus energy available for selling",
            details={},
        )

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)
    monkeypatch.setattr(f"{SELL_BASE}.calculate_export_power", lambda *args, **kwargs: 800.0)

    restore_mock = AsyncMock()
    monkeypatch.setattr(f"{EVENING}.async_handle_sell_restore", restore_mock)

    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=True,
        is_first=True,
    )
    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=False,
        is_first=False,
    )

    assert restore_mock.await_count == 1
    assert outcomes[-1].action_type == "sell_restore"