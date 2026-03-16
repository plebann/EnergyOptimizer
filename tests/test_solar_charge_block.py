"""Tests for solar charge block decision logic."""
from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR,
    CONF_DAYTIME_MIN_PRICE_SENSOR,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MAX_SOC,
    CONF_MIN_SOC_PV,
    CONF_PRICE_SENSOR,
    CONF_PROG3_SOC_ENTITY,
    CONF_PROG3_TIME_START_ENTITY,
    CONF_PV_FORECAST_TODAY,
    CONF_WORK_MODE_ENTITY,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC_PV,
    DOMAIN,
    WORK_MODE_EXPORT_FIRST,
)
from custom_components.energy_optimizer.decision_engine.solar_charge_block import (
    async_run_solar_charge_block,
)

pytestmark = pytest.mark.enable_socket

_ENTRY_ID = "entry-solar"
_PRICE_ENTITY = "sensor.price"
_MIN_PRICE_ENTITY = "sensor.min_price"
_MIN_PRICE_HOUR_ENTITY = "sensor.min_price_hour"
_SOC_ENTITY = "sensor.soc"
_MAX_CHARGE_ENTITY = "number.max_charge"


def _state(value: str, attributes: dict | None = None) -> MagicMock:
    s = MagicMock()
    s.state = value
    s.attributes = attributes or {}
    return s


_WORK_MODE_ENTITY = "select.work_mode"
_PROG1_SOC_ENTITY = "number.prog1_soc"


def _setup_hass(
    *,
    sun_state: str = "above_horizon",
    sun_attrs: dict | None = None,
    now_hour: int = 9,
    current_price: str = "800",
    min_price: str = "400",
    min_price_hour: str | None = "12:00",
    battery_space_value: float | None = 2.0,
    max_charge_entity: str = _MAX_CHARGE_ENTITY,
    max_charge_current_state: str = "23",
    soc_value: str = "80",
    min_soc_pv: int = DEFAULT_MIN_SOC_PV,
    work_mode_entity: str | None = None,
    prog3_soc_entity: str | None = None,
    prog3_time_start: str | None = None,
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
        CONF_MIN_SOC_PV: min_soc_pv,
        CONF_MAX_CHARGE_CURRENT_ENTITY: max_charge_entity,
        CONF_PV_FORECAST_TODAY: None,
        **(
            {CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR: _MIN_PRICE_HOUR_ENTITY}
            if min_price_hour is not None
            else {}
        ),
        **({CONF_WORK_MODE_ENTITY: work_mode_entity} if work_mode_entity else {}),
        **({CONF_PROG3_SOC_ENTITY: prog3_soc_entity} if prog3_soc_entity else {}),
        **(
            {CONF_PROG3_TIME_START_ENTITY: "sensor.prog3_start"}
            if prog3_time_start is not None
            else {}
        ),
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
        **({_MIN_PRICE_HOUR_ENTITY: _state(min_price_hour)} if min_price_hour is not None else {}),
        _MAX_CHARGE_ENTITY: _state(max_charge_current_state),
        _SOC_ENTITY: _state(soc_value),
        **({_WORK_MODE_ENTITY: _state("General Mode")} if work_mode_entity else {}),
        **({"sensor.prog3_start": _state(prog3_time_start)} if prog3_time_start is not None else {}),
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


def _patch_now_and_pv(
    hass: MagicMock,
    *,
    pv_total_kwh: float,
    pv_current_hour_kwh: float | None = None,
):
    """Return context manager patches for dt_util.now and get_pv_forecast_window."""
    from unittest.mock import patch

    if pv_current_hour_kwh is None:
        pv_current_hour_kwh = pv_total_kwh

    return (
        patch(
            "custom_components.energy_optimizer.decision_engine.solar_charge_block.dt_util.now",
            return_value=hass._mock_patch_now,
        ),
        patch(
            "custom_components.energy_optimizer.decision_engine.solar_charge_block.get_pv_forecast_window",
            side_effect=[(pv_total_kwh, {}), (pv_current_hour_kwh, {})],
        ),
    )


@pytest.mark.asyncio
async def test_skip_when_sun_below_horizon() -> None:
    """No action when sun is below the horizon."""
    hass = _setup_hass(sun_state="below_horizon")
    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_work_mode_already_export_first() -> None:
    """No action when blocking already reached Export First state."""
    hass = _setup_hass(work_mode_entity=_WORK_MODE_ENTITY)
    states_map = {
        eid: hass.states.get(eid)
        for eid in [
            "sun.sun",
            _PRICE_ENTITY,
            _MIN_PRICE_ENTITY,
            _MIN_PRICE_HOUR_ENTITY,
            _MAX_CHARGE_ENTITY,
            _SOC_ENTITY,
        ]
    }
    states_map[_WORK_MODE_ENTITY] = _state(WORK_MODE_EXPORT_FIRST)
    hass.states.get.side_effect = lambda eid: states_map.get(eid)

    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_past_noon() -> None:
    """No action when current time is at or past the daytime min price time."""
    hass = _setup_hass(now_hour=12)
    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_price_close_to_minimum() -> None:
    """No action when 0.7 * current_price < min_price (price near daily min)."""
    # 0.7 * 500 = 350 < 400 → skip
    hass = _setup_hass(current_price="500", min_price="400")
    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_surplus_fits_in_battery() -> None:
    """No action when PV surplus <= free battery space."""
    # price gate: 0.7 * 800 = 560 >= 400 → passes
    # surplus 3.0 <= free_space 5.0 → no block
    hass = _setup_hass(current_price="800", min_price="400", battery_space_value=5.0)
    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=3.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_current_hour_pv_not_positive() -> None:
    """No action when current-hour PV forecast is not positive."""
    hass = _setup_hass(current_price="800", min_price="400", battery_space_value=2.0)
    p_now, p_pv = _patch_now_and_pv(
        hass,
        pv_total_kwh=8.0,
        pv_current_hour_kwh=0.0,
    )
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_blocks_at_1A_when_soc_below_min_soc() -> None:
    """Sets max charge current to 1A when PV surplus > free space and SOC < min_soc_pv."""
    # price gate: 0.7 * 800 = 560 >= 400 → passes
    # surplus 8.0 > free_space 2.0 → BLOCK branch
    # SOC 10% < default min_soc 15% → limit to 1A
    hass = _setup_hass(
        current_price="800",
        min_price="400",
        battery_space_value=2.0,
        soc_value="10",
        min_soc_pv=DEFAULT_MIN_SOC_PV,
    )
    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=8.0, pv_current_hour_kwh=1.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)

    hass.services.async_call.assert_called_once_with(
        "number",
        "set_value",
        {"entity_id": _MAX_CHARGE_ENTITY, "value": 1},
        blocking=True,
        context=ANY,
    )


@pytest.mark.asyncio
async def test_export_first_when_soc_above_min_soc() -> None:
    """Sets Export First + target SOC when PV surplus > free space and SOC >= min_soc_pv."""
    # price gate: 0.7 * 800 = 560 >= 400 → passes
    # surplus 8.0 > free_space 2.0 → BLOCK branch
    # SOC 80% >= default min_soc 15% → Export First path
    hass = _setup_hass(
        current_price="800",
        min_price="400",
        battery_space_value=2.0,
        soc_value="80",
        min_soc_pv=DEFAULT_MIN_SOC_PV,
        work_mode_entity=_WORK_MODE_ENTITY,
        prog3_soc_entity="number.prog3_soc",
        prog3_time_start="08:00",
    )
    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=8.0, pv_current_hour_kwh=1.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)

    calls = hass.services.async_call.call_args_list
    assert len(calls) == 3
    assert calls[0] == (
        ("number", "set_value", {"entity_id": _MAX_CHARGE_ENTITY, "value": 23}),
        {"blocking": True, "context": ANY},
    )
    assert calls[1] == (
        ("select", "select_option", {"entity_id": _WORK_MODE_ENTITY, "option": WORK_MODE_EXPORT_FIRST}),
        {"blocking": True, "context": ANY},
    )
    assert calls[2] == (
        ("number", "set_value", {"entity_id": "number.prog3_soc", "value": float(DEFAULT_MIN_SOC_PV)}),
        {"blocking": True, "context": ANY},
    )


@pytest.mark.asyncio
async def test_skip_when_soc_unavailable_at_block_decision() -> None:
    """Skip blocking when battery SOC sensor unavailable."""
    hass = _setup_hass(current_price="800", min_price="400", battery_space_value=2.0)
    # Remove SOC sensor from states
    original_side_effect = hass.states.get.side_effect
    hass.states.get.side_effect = lambda eid: None if eid == _SOC_ENTITY else original_side_effect(eid)
    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=8.0, pv_current_hour_kwh=1.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_min_price_sensor_not_configured() -> None:
    """No action when daytime min price sensor is not configured."""
    hass = _setup_hass()
    # Remove the min price sensor from config
    entry = hass.config_entries.async_get_entry.return_value
    entry.data = {k: v for k, v in entry.data.items() if k != CONF_DAYTIME_MIN_PRICE_SENSOR}

    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_min_price_hour_sensor_not_configured() -> None:
    """No action when daytime min price hour sensor is not configured."""
    hass = _setup_hass(min_price_hour=None)
    p_now, p_pv = _patch_now_and_pv(hass, pv_total_kwh=10.0)
    with p_now, p_pv:
        await async_run_solar_charge_block(hass, entry_id=_ENTRY_ID)
    hass.services.async_call.assert_not_called()
