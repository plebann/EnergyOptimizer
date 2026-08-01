"""Tests for solar charge block decision logic."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, time, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_SOC_SENSOR,
    CONF_DAYTIME_MIN_PRICE_SENSOR,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MIN_SOC_PV,
    CONF_PROG3_SOC_ENTITY,
    CONF_PV_FORECAST_TODAY,
    CONF_SELL_PRICE_SENSOR,
    CONF_WORK_MODE_ENTITY,
    DEFAULT_MAX_CHARGE_CURRENT,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.solar_charge_block import (
    async_run_solar_charge_block,
)

pytestmark = pytest.mark.enable_socket

_ENTRY_ID = "entry-solar"
_SELL_PRICE_ENTITY = "sensor.sell_price"
_MIDDAY_PRICE_ENTITY = "sensor.midday_price"
_PV_FORECAST_ENTITY = "sensor.pv_forecast"
_MAX_CHARGE_ENTITY = "number.max_charge"


def _state(value: str, attributes: dict | None = None) -> MagicMock:
    state = MagicMock()
    state.state = value
    state.attributes = attributes or {}
    return state


def _setup_hass(
    *,
    now_hour: int = 9,
    now_minute: int = 0,
    sun_state: str = "above_horizon",
    sun_attrs: dict | None = None,
    current_price: float | None = 500.0,
    battery_space_value: float | None = 2.0,
    pv_forecast_available: bool = True,
    max_charge_current_value: float | str | None = DEFAULT_MAX_CHARGE_CURRENT,
) -> MagicMock:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = _ENTRY_ID
    entry.domain = DOMAIN
    entry.options = {}
    entry.data = {
        CONF_SELL_PRICE_SENSOR: _SELL_PRICE_ENTITY,
        CONF_DAYTIME_MIN_PRICE_SENSOR: _MIDDAY_PRICE_ENTITY,
        CONF_MAX_CHARGE_CURRENT_ENTITY: _MAX_CHARGE_ENTITY,
        CONF_PV_FORECAST_TODAY: _PV_FORECAST_ENTITY,
        # These values must not affect the narrowed action.
        CONF_BATTERY_SOC_SENSOR: "sensor.soc",
        CONF_MIN_SOC_PV: 95,
        CONF_WORK_MODE_ENTITY: "select.work_mode",
        CONF_PROG3_SOC_ENTITY: "number.prog3_soc",
    }
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry

    default_sun_attrs = {"next_setting": "2026-03-05T16:00:00+00:00"}
    if sun_attrs is not None:
        default_sun_attrs.update(sun_attrs)

    states = {
        "sun.sun": _state(sun_state, default_sun_attrs),
        _MIDDAY_PRICE_ENTITY: _state("400"),
    }
    if current_price is not None:
        states[_SELL_PRICE_ENTITY] = _state(str(current_price))
    if max_charge_current_value is not None:
        states[_MAX_CHARGE_ENTITY] = _state(str(max_charge_current_value))
    if pv_forecast_available:
        states[_PV_FORECAST_ENTITY] = _state(
            "10",
            {
                "detailedHourly": [
                    {
                        "period_start": "2026-03-05T09:00:00+00:00",
                        "pv_estimate": 3.0,
                    }
                ]
            },
        )
    hass.states.get.side_effect = lambda entity_id: states.get(entity_id)
    hass.services.async_call = AsyncMock()

    battery_space_sensor = MagicMock()
    battery_space_sensor.native_value = battery_space_value
    hass.data = {
        DOMAIN: {
            _ENTRY_ID: {
                "battery_space_sensor": battery_space_sensor,
            }
        }
    }
    hass._mock_now = datetime(
        2026,
        3,
        5,
        now_hour,
        now_minute,
        0,
        tzinfo=timezone.utc,
    )
    return hass


async def _run(
    hass: MagicMock,
    *,
    morning_sell_hour: int = 7,
    morning_sell_price: float | None = 800.0,
    midday_avoidance_price: float | None = 400.0,
    daytime_min_price_time: time = time(12, 0),
    pv_total_kwh: float = 8.0,
    pv_current_hour_kwh: float = 3.0,
    current_hour_demand_kwh: float = 1.0,
) -> None:
    def _window_price(*_args, **kwargs):
        if kwargs["unique_id_suffix"] == "morning_sell_window":
            return morning_sell_price
        return midday_avoidance_price

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.dt_util.now",
                return_value=hass._mock_now,
            )
        )
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.resolve_morning_max_price_hour",
                return_value=morning_sell_hour,
            )
        )
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.resolve_daytime_min_price_time",
                return_value=daytime_min_price_time,
            )
        )
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.get_internal_window_price",
                side_effect=_window_price,
            )
        )
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.get_pv_forecast_window",
                side_effect=[
                    (pv_total_kwh, {}),
                    (pv_current_hour_kwh, {}),
                ],
            )
        )
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.build_hourly_usage_array",
                return_value=[0.0] * 24,
            )
        )
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.get_heat_pump_forecast_window",
                new=AsyncMock(return_value=(0.0, {})),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.calculate_losses",
                return_value=({}, 0.0),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.energy_optimizer.decision_engine.solar_charge_block.hourly_demand",
                return_value=current_hour_demand_kwh,
            )
        )
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)


def _assert_charge_current(hass: MagicMock, value: float) -> None:
    hass.services.async_call.assert_called_once_with(
        "number",
        "set_value",
        {"entity_id": _MAX_CHARGE_ENTITY, "value": value},
        blocking=True,
        context=ANY,
    )


@pytest.mark.asyncio
async def test_before_morning_sell_window_makes_no_changes() -> None:
    """Do not take ownership of inverter state before the morning sell window."""
    hass = _setup_hass(now_hour=6)

    await _run(hass, morning_sell_hour=7)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_sun_below_horizon_makes_no_changes() -> None:
    """Do not act when the daylight guard is unavailable."""
    hass = _setup_hass(sun_state="below_horizon")

    await _run(hass)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("morning_price", "midday_price", "current_price"),
    [
        (800.0, 400.0, 480.0),
        (100.0, 0.0, 20.0),
        (50.0, -50.0, -30.0),
    ],
)
async def test_blocks_at_or_above_dynamic_threshold(
    morning_price: float,
    midday_price: float,
    current_price: float,
) -> None:
    """Set only maximum charge current to zero when every block guard is true."""
    hass = _setup_hass(current_price=current_price)

    await _run(
        hass,
        morning_sell_price=morning_price,
        midday_avoidance_price=midday_price,
    )

    _assert_charge_current(hass, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("morning_price", "midday_price", "current_price"),
    [
        (800.0, 400.0, 479.9),
        (100.0, 0.0, 19.9),
        (50.0, -50.0, -30.1),
    ],
)
async def test_restores_below_dynamic_threshold(
    morning_price: float,
    midday_price: float,
    current_price: float,
) -> None:
    """Restore default charging below the low-value spread threshold."""
    hass = _setup_hass(current_price=current_price)

    await _run(
        hass,
        morning_sell_price=morning_price,
        midday_avoidance_price=midday_price,
    )

    _assert_charge_current(hass, DEFAULT_MAX_CHARGE_CURRENT)


@pytest.mark.asyncio
async def test_restores_when_forecast_surplus_fits_in_battery() -> None:
    """Restore charging when forecast surplus no longer exceeds free space."""
    hass = _setup_hass(battery_space_value=5.0)

    await _run(hass, pv_total_kwh=5.0)

    _assert_charge_current(hass, DEFAULT_MAX_CHARGE_CURRENT)


@pytest.mark.asyncio
async def test_restores_when_current_hour_pv_does_not_exceed_demand() -> None:
    """Restore charging until the current hour has real PV surplus."""
    hass = _setup_hass()

    await _run(
        hass,
        pv_current_hour_kwh=1.0,
        current_hour_demand_kwh=1.0,
    )

    _assert_charge_current(hass, DEFAULT_MAX_CHARGE_CURRENT)


@pytest.mark.asyncio
async def test_at_daytime_min_price_restores_when_current_charge_is_zero() -> None:
    """Restore once the midday cutoff is reached if solar charging is blocked."""
    hass = _setup_hass(now_hour=12, current_price=500.0, max_charge_current_value=0)

    await _run(hass)

    _assert_charge_current(hass, DEFAULT_MAX_CHARGE_CURRENT)


@pytest.mark.asyncio
async def test_before_daytime_min_price_in_same_hour_can_still_block() -> None:
    """Allow normal evaluation before the exact midday cutoff minute."""
    hass = _setup_hass(now_hour=11, now_minute=0)

    await _run(hass, daytime_min_price_time=time(11, 30))

    _assert_charge_current(hass, 0)


@pytest.mark.asyncio
async def test_at_daytime_min_price_skips_when_charge_is_not_zero() -> None:
    """Do not continue block evaluation after the midday cutoff."""
    hass = _setup_hass(
        now_hour=12,
        current_price=500.0,
        max_charge_current_value=DEFAULT_MAX_CHARGE_CURRENT,
    )

    await _run(hass)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_at_daytime_min_price_skips_when_charge_state_is_invalid() -> None:
    """Do not issue restore if the current max charge state cannot be verified."""
    hass = _setup_hass(now_hour=12, max_charge_current_value="unknown")

    await _run(hass)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_missing_current_sell_price_makes_no_changes() -> None:
    """Missing current sell-price data must not trigger a command."""
    hass = _setup_hass(current_price=None)

    await _run(hass)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("morning_price", "midday_price"),
    [(None, 400.0), (800.0, None)],
)
async def test_missing_window_price_makes_no_changes(
    morning_price: float | None,
    midday_price: float | None,
) -> None:
    """Missing Morning Sell or Midday Avoidance prices must not trigger a command."""
    hass = _setup_hass()

    await _run(
        hass,
        morning_sell_price=morning_price,
        midday_avoidance_price=midday_price,
    )

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_missing_pv_forecast_makes_no_changes() -> None:
    """Missing PV forecast data must not be treated as a false capacity guard."""
    hass = _setup_hass(pv_forecast_available=False)

    await _run(hass)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_missing_battery_space_makes_no_changes() -> None:
    """Missing battery-space data must not trigger a restore or block."""
    hass = _setup_hass(battery_space_value=None)

    await _run(hass)

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_ignores_soc_work_mode_and_program_soc() -> None:
    """Block without reading SOC or changing work mode or active program SOC."""
    hass = _setup_hass()

    await _run(hass)

    _assert_charge_current(hass, 0)
    requested_entity_ids = [
        call.args[2]["entity_id"]
        for call in hass.services.async_call.call_args_list
    ]
    assert "select.work_mode" not in requested_entity_ids
    assert "number.prog3_soc" not in requested_entity_ids
