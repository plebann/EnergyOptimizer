"""Tests for solar charge block decision logic."""
from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_DAYTIME_MIN_PRICE_SENSOR,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MAX_SOC,
    CONF_PRICE_SENSOR,
    CONF_PV_FORECAST_TODAY,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_MAX_SOC,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.solar_charge_block import (
    async_run_solar_charge_block,
)

pytestmark = pytest.mark.enable_socket

_ENTRY_ID = "entry-solar"
_PRICE_ENTITY = "sensor.price"
_MIN_PRICE_ENTITY = "sensor.min_price"
_SOC_ENTITY = "sensor.soc"
_MAX_CHARGE_ENTITY = "number.max_charge"


def _state(value: str, attributes: dict | None = None) -> MagicMock:
    s = MagicMock()
    s.state = value
    s.attributes = attributes or {}
    return s


def _setup_hass(
    *,
    sun_state: str = "above_horizon",
    sun_attrs: dict | None = None,
    now_hour: int = 9,
    current_price: str = "800",
    min_price: str = "400",
    battery_space_value: float | None = 2.0,
    pv_forecast_kwh: float = 5.0,
    max_charge_entity: str = _MAX_CHARGE_ENTITY,
    max_charge_current_state: str = "23",
) -> MagicMock:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = _ENTRY_ID
    entry.domain = DOMAIN
    entry.options = {}
    entry.data = {
        CONF_PRICE_SENSOR: _PRICE_ENTITY,
        CONF_DAYTIME_MIN_PRICE_SENSOR: _MIN_PRICE_ENTITY,
        CONF_BATTERY_SOC_SENSOR: _SOC_ENTITY,
        CONF_BATTERY_CAPACITY_AH: DEFAULT_BATTERY_CAPACITY_AH,
        CONF_BATTERY_VOLTAGE: DEFAULT_BATTERY_VOLTAGE,
        CONF_MAX_SOC: DEFAULT_MAX_SOC,
        CONF_MAX_CHARGE_CURRENT_ENTITY: max_charge_entity,
        CONF_PV_FORECAST_TODAY: None,
    }
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry

    default_sun_attrs = {
        "next_setting": "2026-03-05T16:00:00+00:00",
    }
    if sun_attrs is not None:
        default_sun_attrs.update(sun_attrs)

    states: dict[str, MagicMock] = {
        "sun.sun": _state(sun_state, default_sun_attrs),
        _PRICE_ENTITY: _state(current_price),
        _MIN_PRICE_ENTITY: _state(min_price),
        _MAX_CHARGE_ENTITY: _state(max_charge_current_state),
    }
    hass.states.get.side_effect = lambda eid: states.get(eid)
    hass.services.async_call = AsyncMock()

    # Battery space sensor mock
    battery_space_sensor = MagicMock()
    battery_space_sensor.native_value = battery_space_value

    hass.data = {
        DOMAIN: {
            _ENTRY_ID: {
                "battery_space_sensor": battery_space_sensor,
            }
        }
    }

    # Mock dt_util.now() to return a controlled hour — patch via the module
    import datetime
    from unittest.mock import patch

    _now = datetime.datetime(2026, 3, 5, now_hour, 0, 0,
                             tzinfo=datetime.timezone.utc)

    hass._mock_patch_now = _now
    return hass


def _patch_now_and_pv(hass: MagicMock, pv_kwh: float):
    """Return context manager patches for dt_util.now and get_pv_forecast_window."""
    from unittest.mock import patch
    return (
        patch(
            "custom_components.energy_optimizer.decision_engine.solar_charge_block.dt_util.now",
            return_value=hass._mock_patch_now,
        ),
        patch(
            "custom_components.energy_optimizer.decision_engine.solar_charge_block.get_pv_forecast_window",
            return_value=(pv_kwh, {}),
        ),
    )


@pytest.mark.asyncio
async def test_skip_when_sun_below_horizon() -> None:
    """No action when sun is below the horizon."""
    hass = _setup_hass(sun_state="below_horizon")
    p_now, p_pv = _patch_now_and_pv(hass, pv_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_max_charge_current_already_zero() -> None:
    """No action when max charge current is already set to 0."""
    hass = _setup_hass(max_charge_current_state="0")
    p_now, p_pv = _patch_now_and_pv(hass, pv_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_past_noon() -> None:
    """No action when current hour is >= 12."""
    hass = _setup_hass(now_hour=12)
    p_now, p_pv = _patch_now_and_pv(hass, pv_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_price_close_to_minimum() -> None:
    """No action when 0.7 * current_price < min_price (price near daily min)."""
    # 0.7 * 500 = 350 < 400 → skip
    hass = _setup_hass(current_price="500", min_price="400")
    p_now, p_pv = _patch_now_and_pv(hass, pv_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_surplus_fits_in_battery() -> None:
    """No action when PV surplus <= free battery space."""
    # price gate: 0.7 * 800 = 560 >= 400 → passes
    # surplus 3.0 <= free_space 5.0 → no block
    hass = _setup_hass(current_price="800", min_price="400", battery_space_value=5.0)
    p_now, p_pv = _patch_now_and_pv(hass, pv_kwh=3.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_blocks_when_surplus_exceeds_space() -> None:
    """Sets max charge current to 0 when PV surplus > free battery space."""
    # price gate: 0.7 * 800 = 560 >= 400 → passes
    # surplus 8.0 > free_space 2.0 → BLOCK
    hass = _setup_hass(current_price="800", min_price="400", battery_space_value=2.0)
    p_now, p_pv = _patch_now_and_pv(hass, pv_kwh=8.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once_with(
        "number",
        "set_value",
        {"entity_id": _MAX_CHARGE_ENTITY, "value": 0},
        blocking=True,
        context=ANY,
    )


@pytest.mark.asyncio
async def test_skip_when_min_price_sensor_not_configured() -> None:
    """No action when daytime min price sensor is not configured."""
    hass = _setup_hass()
    # Remove the min price sensor from config
    entry = hass.config_entries.async_get_entry.return_value
    entry.data = {k: v for k, v in entry.data.items() if k != CONF_DAYTIME_MIN_PRICE_SENSOR}

    p_now, p_pv = _patch_now_and_pv(hass, pv_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()
