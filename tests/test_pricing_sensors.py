"""Tests for price-related Energy Optimizer sensors."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_SELL_PRICE_SENSOR,
)
from custom_components.energy_optimizer.coordinator import EnergyOptimizerCoordinator
from custom_components.energy_optimizer.entities.sensors.pricing import (
    BuyPriceSensor,
    DayBuyWindowSensor,
    DayBuyWindowTomorrowSensor,
    EveningSellWindowSensor,
    EveningSellWindowTomorrowSensor,
    MiddaySellWindowSensor,
    MiddaySellWindowTomorrowSensor,
    MinArbitrageMarginSensor,
    MorningSellWindowSensor,
    MorningSellWindowTomorrowSensor,
    NightBuyWindowSensor,
    NightBuyWindowTomorrowSensor,
    SellPriceSensor,
)

TZ = timezone(timedelta(hours=2))


def _mock_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {}
    entry.options = {}
    return entry


def _hourly_entry(hour: int, price: float | str) -> dict[str, object]:
    dt = datetime(2026, 5, 8, hour, 0, tzinfo=TZ)
    return {"time": dt.isoformat(), "price": price}


def _hourly_entry_for_day(day: int, hour: int, price: float | str) -> dict[str, object]:
    dt = datetime(2026, 5, day, hour, 0, tzinfo=TZ)
    return {"time": dt.isoformat(), "price": price}


def _payload(low_start_hour: int = 10, low_hours: int = 2) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for hour in range(8, 16):
        is_low = low_start_hour <= hour < low_start_hour + low_hours
        entries.append(_hourly_entry(hour, 0.5 if is_low else 1.0))
    return entries


def _payload_for_day(day: int, low_start_hour: int = 10, low_hours: int = 2) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for hour in range(8, 16):
        is_low = low_start_hour <= hour < low_start_hour + low_hours
        entries.append(_hourly_entry_for_day(day, hour, 0.5 if is_low else 1.0))
    return entries


def _ranked_payload_for_hours(
    day: int,
    prices_by_hour: dict[int, float | str],
) -> list[dict[str, object]]:
    return [
        _hourly_entry_for_day(day, hour, price)
        for hour, price in sorted(prices_by_hour.items())
    ]


def _buy_payload_for_hours(
    day: int,
    prices_by_hour: dict[int, float | str],
) -> list[dict[str, object]]:
    return [
        _hourly_entry_for_day(day, hour, price)
        for hour, price in sorted(prices_by_hour.items())
    ]


def _coordinator_with_price_payloads(
    price_payloads: dict[str, dict[str, object]],
    *,
    states: dict[str, object] | None = None,
) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {
        "states": states or {},
        "price_payloads": price_payloads,
    }
    return coordinator


def _coordinator_with_prices(
    prices_today: list[dict[str, object]] | None = None,
    prices_tomorrow: list[dict[str, object]] | None = None,
    sell_entity: str = "sensor.sell",
) -> MagicMock:
    coordinator = MagicMock()
    payload: dict[str, object] = {}
    if prices_today is not None:
        payload["prices_today"] = prices_today
    if prices_tomorrow is not None:
        payload["prices_tomorrow"] = prices_tomorrow
    coordinator.data = {
        "states": {},
        "price_payloads": {
            sell_entity: payload,
        },
    }
    return coordinator


def _midday_sensor(prices_today: list[dict[str, object]], config: dict[str, object] | None = None) -> MiddaySellWindowSensor:
    config = config or {CONF_SELL_PRICE_SENSOR: "sensor.sell"}
    coordinator = _coordinator_with_prices(prices_today, None, str(config[CONF_SELL_PRICE_SENSOR]))
    sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), config)
    sensor.hass = MagicMock()
    return sensor


def _midday_tomorrow_sensor(
    prices_tomorrow: list[dict[str, object]],
    config: dict[str, object] | None = None,
) -> MiddaySellWindowTomorrowSensor:
    config = config or {CONF_SELL_PRICE_SENSOR: "sensor.sell"}
    coordinator = _coordinator_with_prices(None, prices_tomorrow, str(config[CONF_SELL_PRICE_SENSOR]))
    sensor = MiddaySellWindowTomorrowSensor(coordinator, _mock_entry(), config)
    sensor.hass = MagicMock()
    return sensor


def _morning_sensor(prices_today: list[dict[str, object]]) -> MorningSellWindowSensor:
    coordinator = _coordinator_with_prices(prices_today, None, "sensor.sell")
    sensor = MorningSellWindowSensor(
        coordinator,
        _mock_entry(),
        {CONF_SELL_PRICE_SENSOR: "sensor.sell"},
    )
    sensor.hass = MagicMock()
    return sensor


def _evening_sensor(prices_today: list[dict[str, object]]) -> EveningSellWindowSensor:
    coordinator = _coordinator_with_prices(prices_today, None, "sensor.sell")
    sensor = EveningSellWindowSensor(
        coordinator,
        _mock_entry(),
        {CONF_SELL_PRICE_SENSOR: "sensor.sell"},
    )
    sensor.hass = MagicMock()
    return sensor


def _morning_tomorrow_sensor(
    prices_tomorrow: list[dict[str, object]],
) -> MorningSellWindowTomorrowSensor:
    coordinator = _coordinator_with_prices(None, prices_tomorrow, "sensor.sell")
    sensor = MorningSellWindowTomorrowSensor(
        coordinator,
        _mock_entry(),
        {CONF_SELL_PRICE_SENSOR: "sensor.sell"},
    )
    sensor.hass = MagicMock()
    return sensor


def _evening_tomorrow_sensor(
    prices_tomorrow: list[dict[str, object]],
) -> EveningSellWindowTomorrowSensor:
    coordinator = _coordinator_with_prices(None, prices_tomorrow, "sensor.sell")
    sensor = EveningSellWindowTomorrowSensor(
        coordinator,
        _mock_entry(),
        {CONF_SELL_PRICE_SENSOR: "sensor.sell"},
    )
    sensor.hass = MagicMock()
    return sensor


def _night_buy_sensor(
    prices_today: list[dict[str, object]],
    prices_tomorrow: list[dict[str, object]] | None = None,
) -> NightBuyWindowSensor:
    coordinator = _coordinator_with_prices(prices_today, prices_tomorrow, "sensor.buy")
    sensor = NightBuyWindowSensor(
        coordinator,
        _mock_entry(),
        {CONF_BUY_PRICE_SENSOR: "sensor.buy"},
    )
    sensor.hass = MagicMock()
    return sensor


def _day_buy_sensor(
    prices_today: list[dict[str, object]],
    prices_tomorrow: list[dict[str, object]] | None = None,
) -> DayBuyWindowSensor:
    coordinator = _coordinator_with_prices(prices_today, prices_tomorrow, "sensor.buy")
    sensor = DayBuyWindowSensor(
        coordinator,
        _mock_entry(),
        {CONF_BUY_PRICE_SENSOR: "sensor.buy"},
    )
    sensor.hass = MagicMock()
    return sensor


def _night_buy_tomorrow_sensor(
    prices_tomorrow: list[dict[str, object]],
) -> NightBuyWindowTomorrowSensor:
    coordinator = _coordinator_with_prices(None, prices_tomorrow, "sensor.buy")
    sensor = NightBuyWindowTomorrowSensor(
        coordinator,
        _mock_entry(),
        {CONF_BUY_PRICE_SENSOR: "sensor.buy"},
    )
    sensor.hass = MagicMock()
    return sensor


def _day_buy_tomorrow_sensor(
    prices_tomorrow: list[dict[str, object]],
) -> DayBuyWindowTomorrowSensor:
    coordinator = _coordinator_with_prices(None, prices_tomorrow, "sensor.buy")
    sensor = DayBuyWindowTomorrowSensor(
        coordinator,
        _mock_entry(),
        {CONF_BUY_PRICE_SENSOR: "sensor.buy"},
    )
    sensor.hass = MagicMock()
    return sensor


def test_price_sensors_round_source_values_to_three_decimals() -> None:
    coordinator = MagicMock()
    coordinator.data = {
        "states": {
            "sensor.buy_price": 1.3274,
            "sensor.sell_price": 1.4286,
        }
    }
    config = {
        CONF_BUY_PRICE_SENSOR: "sensor.buy_price",
        CONF_SELL_PRICE_SENSOR: "sensor.sell_price",
    }

    buy_sensor = BuyPriceSensor(coordinator, _mock_entry(), config)
    sell_sensor = SellPriceSensor(coordinator, _mock_entry(), config)

    assert buy_sensor.native_value == 1.327
    assert sell_sensor.native_value == 1.429


def test_min_arbitrage_margin_sensor_exposes_configured_value() -> None:
    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    sensor = MinArbitrageMarginSensor(
        coordinator,
        _mock_entry(),
        {CONF_MIN_ARBITRAGE_PRICE: 0.2574},
    )

    assert sensor.native_value == 0.257


@pytest.mark.unit
def test_midday_sell_window_sensor_publishes_correct_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _midday_sensor(_payload(low_start_hour=10))

    assert sensor.native_value == "10:00-12:00"
    assert sensor.extra_state_attributes == {"price": 0.5}


@pytest.mark.unit
def test_midday_sell_window_tomorrow_sensor_publishes_correct_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _midday_tomorrow_sensor(_payload_for_day(9, low_start_hour=11))

    assert sensor.native_value == "11:00-13:00"
    assert sensor.extra_state_attributes == {"price": 0.5}


@pytest.mark.unit
def test_midday_sell_window_sensor_ignores_buy_price_only_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    config = {
        CONF_SELL_PRICE_SENSOR: "sensor.sell",
        CONF_BUY_PRICE_SENSOR: "sensor.buy",
    }
    coordinator = _coordinator_with_prices(
        prices_today=_payload(low_start_hour=10),
        sell_entity="sensor.sell",
    )
    coordinator.data["states"]["sensor.buy"] = 0.25

    sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), config)
    sensor.hass = MagicMock()

    first_value = sensor.native_value
    coordinator.data["states"]["sensor.buy"] = 9.99
    second_value = sensor.native_value

    assert first_value == "10:00-12:00"
    assert second_value == first_value


@pytest.mark.unit
def test_midday_sell_window_sensor_uses_hhmm_hhmm_format(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _midday_sensor(_payload(low_start_hour=8))

    assert sensor.native_value == "08:00-10:00"


@pytest.mark.unit
def test_midday_sell_window_sensor_updates_when_shared_payload_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = _coordinator_with_prices(_payload(low_start_hour=10), None, "sensor.sell")
    sensor = MiddaySellWindowSensor(
        coordinator,
        _mock_entry(),
        {CONF_SELL_PRICE_SENSOR: "sensor.sell"},
    )
    sensor.hass = MagicMock()

    assert sensor.native_value == "10:00-12:00"

    coordinator.data["price_payloads"]["sensor.sell"] = {"prices_today": _payload(low_start_hour=8)}

    assert sensor.native_value == "08:00-10:00"


@pytest.mark.unit
def test_midday_sell_window_sensor_unavailable_when_missing_sell_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _midday_sensor([])

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


@pytest.mark.unit
def test_midday_sell_window_sensor_unavailable_when_fewer_than_two_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _midday_sensor([_hourly_entry(8, 0.5)])

    assert sensor.native_value is None


@pytest.mark.unit
def test_midday_sell_window_sensor_has_translation_key_and_prefixed_unique_id() -> None:
    sensor = _midday_sensor(_payload(low_start_hour=10))

    assert sensor.translation_key == "midday_sell_window"
    assert sensor.unique_id == "entry-1_midday_sell_window"


@pytest.mark.unit
def test_today_and_tomorrow_sensors_are_isolated_by_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = _coordinator_with_prices(
        _payload(low_start_hour=10),
        _payload_for_day(9, low_start_hour=11),
        "sensor.sell",
    )
    config = {CONF_SELL_PRICE_SENSOR: "sensor.sell"}

    today_sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), config)
    tomorrow_sensor = MiddaySellWindowTomorrowSensor(coordinator, _mock_entry(), config)
    today_sensor.hass = MagicMock()
    tomorrow_sensor.hass = MagicMock()

    assert today_sensor.native_value == "10:00-12:00"
    assert tomorrow_sensor.native_value == "11:00-13:00"

    coordinator.data["price_payloads"]["sensor.sell"]["prices_tomorrow"] = _payload_for_day(
        9, low_start_hour=8
    )

    assert today_sensor.native_value == "10:00-12:00"
    assert tomorrow_sensor.native_value == "08:00-10:00"


@pytest.mark.unit
def test_tomorrow_sensor_unavailable_omits_price_without_affecting_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = _coordinator_with_prices(_payload(low_start_hour=10), [], "sensor.sell")
    config = {CONF_SELL_PRICE_SENSOR: "sensor.sell"}

    today_sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), config)
    tomorrow_sensor = MiddaySellWindowTomorrowSensor(coordinator, _mock_entry(), config)
    today_sensor.hass = MagicMock()
    tomorrow_sensor.hass = MagicMock()

    assert today_sensor.native_value == "10:00-12:00"
    assert today_sensor.extra_state_attributes == {"price": 0.5}
    assert tomorrow_sensor.native_value is None
    assert tomorrow_sensor.extra_state_attributes == {}


@pytest.mark.unit
def test_midday_sell_window_tomorrow_sensor_has_translation_key_and_prefixed_unique_id() -> None:
    sensor = _midday_tomorrow_sensor(_payload_for_day(9, low_start_hour=10))

    assert sensor.translation_key == "midday_sell_window_tomorrow"
    assert sensor.unique_id == "entry-1_midday_sell_window_tomorrow"


@pytest.mark.unit
def test_morning_sell_window_sensor_publishes_best_and_second_best_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _morning_sensor(
        _ranked_payload_for_hours(
            8,
            {4: 0.40, 5: 0.85, 6: 0.72, 7: 0.91, 8: 0.55, 9: 0.60},
        )
    )

    assert sensor.native_value == "07:00"
    assert sensor.extra_state_attributes == {
        "price": 0.91,
        "second_window_start": "05:00",
        "second_window_price": 0.85,
        "second_window_gap_pct": 6.6,
    }


@pytest.mark.unit
def test_evening_sell_window_sensor_publishes_best_and_second_best_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 18, 0, tzinfo=TZ))

    sensor = _evening_sensor(
        _ranked_payload_for_hours(
            8,
            {16: 0.40, 17: 0.95, 18: 0.82, 19: 0.88, 20: 0.91, 21: 0.60},
        )
    )

    assert sensor.native_value == "17:00"
    assert sensor.extra_state_attributes == {
        "price": 0.95,
        "second_window_start": "20:00",
        "second_window_price": 0.91,
        "second_window_gap_pct": 4.2,
    }


@pytest.mark.unit
def test_morning_sell_window_tomorrow_sensor_isolated_from_today_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = _coordinator_with_prices(
        _ranked_payload_for_hours(8, {4: 0.40, 5: 0.85, 6: 0.72, 7: 0.91}),
        _ranked_payload_for_hours(9, {4: 0.90, 5: 0.70, 6: 0.65, 7: 0.60}),
        "sensor.sell",
    )
    config = {CONF_SELL_PRICE_SENSOR: "sensor.sell"}

    today_sensor = MorningSellWindowSensor(coordinator, _mock_entry(), config)
    tomorrow_sensor = MorningSellWindowTomorrowSensor(coordinator, _mock_entry(), config)
    today_sensor.hass = MagicMock()
    tomorrow_sensor.hass = MagicMock()

    assert today_sensor.native_value == "07:00"
    assert tomorrow_sensor.native_value == "04:00"

    coordinator.data["price_payloads"]["sensor.sell"]["prices_tomorrow"] = _ranked_payload_for_hours(
        9, {4: 0.20, 5: 0.95, 6: 0.65, 7: 0.60}
    )

    assert today_sensor.native_value == "07:00"
    assert tomorrow_sensor.native_value == "05:00"


@pytest.mark.unit
def test_evening_sell_window_tomorrow_sensor_publishes_best_and_second_best_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 18, 0, tzinfo=TZ))

    sensor = _evening_tomorrow_sensor(
        _ranked_payload_for_hours(
            9,
            {16: 0.4021, 17: 0.9544, 18: 0.8242, 19: 0.8811, 20: 0.9119, 21: 0.6012},
        )
    )

    assert sensor.native_value == "17:00"
    assert sensor.extra_state_attributes == {
        "price": 0.954,
        "second_window_start": "20:00",
        "second_window_price": 0.912,
        "second_window_gap_pct": 4.5,
    }


@pytest.mark.unit
def test_evening_sell_window_sensor_unavailable_when_fewer_than_two_valid_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 18, 0, tzinfo=TZ))

    sensor = _evening_sensor(_ranked_payload_for_hours(8, {17: 0.95}))

    assert sensor.native_value is None
    assert sensor.available is False
    assert sensor.extra_state_attributes == {}


@pytest.mark.unit
def test_morning_sell_window_sensor_omits_gap_when_best_price_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _morning_sensor(_ranked_payload_for_hours(8, {4: 0.0, 5: -0.1, 6: -0.2}))

    assert sensor.native_value == "04:00"
    assert sensor.extra_state_attributes == {
        "price": 0.0,
        "second_window_start": "05:00",
        "second_window_price": -0.1,
    }


@pytest.mark.unit
def test_ranked_sell_window_sensor_ignores_buy_price_only_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    config = {
        CONF_SELL_PRICE_SENSOR: "sensor.sell",
        CONF_BUY_PRICE_SENSOR: "sensor.buy",
    }
    coordinator = _coordinator_with_prices(
        _ranked_payload_for_hours(8, {4: 0.40, 5: 0.85, 6: 0.72, 7: 0.91}),
        None,
        "sensor.sell",
    )
    coordinator.data["states"]["sensor.buy"] = 0.25

    sensor = MorningSellWindowSensor(coordinator, _mock_entry(), config)
    sensor.hass = MagicMock()

    first_value = sensor.native_value
    first_attributes = sensor.extra_state_attributes
    coordinator.data["states"]["sensor.buy"] = 9.99

    assert sensor.native_value == first_value
    assert sensor.extra_state_attributes == first_attributes


@pytest.mark.unit
def test_ranked_sell_window_sensors_have_translation_keys_and_prefixed_unique_ids() -> None:
    morning = _morning_sensor(_ranked_payload_for_hours(8, {4: 0.4, 5: 0.8, 6: 0.7}))
    evening_tomorrow = _evening_tomorrow_sensor(
        _ranked_payload_for_hours(9, {16: 0.4, 17: 0.9, 18: 0.8})
    )

    assert morning.translation_key == "morning_sell_window"
    assert morning.unique_id == "entry-1_morning_sell_window"
    assert evening_tomorrow.translation_key == "evening_sell_window_tomorrow"
    assert evening_tomorrow.unique_id == "entry-1_evening_sell_window_tomorrow"


@pytest.mark.unit
def test_ranked_sell_window_sensor_rounds_only_published_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _morning_sensor(
        _ranked_payload_for_hours(
            8,
            {4: 0.9999, 5: 0.6666, 6: 0.5},
        )
    )

    assert sensor.native_value == "04:00"
    assert sensor.extra_state_attributes == {
        "price": 1.0,
        "second_window_start": "05:00",
        "second_window_price": 0.667,
        "second_window_gap_pct": 33.3,
    }


@pytest.mark.unit
def test_duplicate_hour_only_makes_affected_ranked_sensor_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 18, 0, tzinfo=TZ))

    coordinator = _coordinator_with_prices(
        _ranked_payload_for_hours(
            8,
            {
                4: 0.40,
                5: 0.80,
                6: 0.70,
                16: 0.60,
                17: 0.95,
                18: 0.85,
                19: 0.95,
            },
        )
        + [{"time": datetime(2026, 5, 8, 5, 0, tzinfo=TZ).isoformat(), "price": 0.81}],
        None,
        "sensor.sell",
    )
    config = {CONF_SELL_PRICE_SENSOR: "sensor.sell"}

    morning_sensor = MorningSellWindowSensor(coordinator, _mock_entry(), config)
    evening_sensor = EveningSellWindowSensor(coordinator, _mock_entry(), config)
    morning_sensor.hass = MagicMock()
    evening_sensor.hass = MagicMock()

    assert morning_sensor.native_value is None
    assert morning_sensor.available is False
    assert evening_sensor.native_value == "17:00"
    assert evening_sensor.extra_state_attributes == {
        "price": 0.95,
        "second_window_start": "19:00",
        "second_window_price": 0.95,
        "second_window_gap_pct": 0.0,
    }


@pytest.mark.asyncio
async def test_coordinator_copies_price_payloads_to_avoid_in_place_source_mutation() -> None:
    prices_today = _payload(low_start_hour=10)
    prices_tomorrow = _payload_for_day(9, low_start_hour=11)

    state = MagicMock()
    state.state = "1.0"
    state.attributes = {
        "prices_today": prices_today,
        "prices_tomorrow": prices_tomorrow,
    }

    hass = MagicMock()
    hass.states.get.return_value = state

    entry = _mock_entry()
    entry.data = {CONF_SELL_PRICE_SENSOR: "sensor.sell"}

    coordinator = EnergyOptimizerCoordinator(hass, entry)
    data = await coordinator._async_update_data()

    snapshot_today = data["price_payloads"]["sensor.sell"]["prices_today"]
    snapshot_tomorrow = data["price_payloads"]["sensor.sell"]["prices_tomorrow"]

    assert snapshot_today == prices_today
    assert snapshot_tomorrow == prices_tomorrow
    assert snapshot_today is not prices_today
    assert snapshot_tomorrow is not prices_tomorrow

    prices_tomorrow.clear()

    assert snapshot_tomorrow != prices_tomorrow
    assert snapshot_tomorrow


@pytest.mark.unit
def test_today_buy_window_sensors_publish_state_and_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    prices_today = _buy_payload_for_hours(
        8,
        {
            0: 0.50,
            1: 0.10,
            2: 0.20,
            3: 0.80,
            4: 0.90,
            5: 1.00,
            10: 0.80,
            11: 0.30,
            12: 0.20,
            13: 0.60,
            14: 0.90,
            15: 1.00,
        },
    )

    night_sensor = _night_buy_sensor(prices_today)
    day_sensor = _day_buy_sensor(prices_today)

    assert night_sensor.native_value == "01:00"
    assert night_sensor.extra_state_attributes == {
        "price": 0.15,
        "is_negative": False,
    }
    assert day_sensor.native_value == "11:00"
    assert day_sensor.extra_state_attributes == {
        "price": 0.25,
        "is_negative": False,
    }


@pytest.mark.unit
def test_tomorrow_buy_window_sensors_publish_state_and_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    prices_tomorrow = _buy_payload_for_hours(
        9,
        {
            0: 0.80,
            1: 0.60,
            2: 0.10,
            3: 0.20,
            4: 1.00,
            5: 1.10,
            10: 0.90,
            11: 0.60,
            12: -0.20,
            13: 0.80,
            14: 0.85,
            15: 0.90,
        },
    )

    night_sensor = _night_buy_tomorrow_sensor(prices_tomorrow)
    day_sensor = _day_buy_tomorrow_sensor(prices_tomorrow)

    assert night_sensor.native_value == "02:00"
    assert night_sensor.extra_state_attributes == {
        "price": 0.15,
        "is_negative": False,
    }
    assert day_sensor.native_value == "11:00"
    assert day_sensor.extra_state_attributes == {
        "price": 0.2,
        "is_negative": False,
    }


@pytest.mark.unit
def test_tomorrow_buy_window_sensors_are_unavailable_for_empty_payload_without_affecting_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = _coordinator_with_prices(
        _buy_payload_for_hours(8, {0: 0.50, 1: 0.10, 2: 0.20, 3: 0.80, 10: 0.80, 11: 0.30, 12: 0.20, 13: 0.60}),
        [],
        "sensor.buy",
    )
    config = {CONF_BUY_PRICE_SENSOR: "sensor.buy"}
    today_sensor = NightBuyWindowSensor(coordinator, _mock_entry(), config)
    tomorrow_sensor = NightBuyWindowTomorrowSensor(coordinator, _mock_entry(), config)
    today_sensor.hass = MagicMock()
    tomorrow_sensor.hass = MagicMock()

    assert today_sensor.native_value == "01:00"
    assert today_sensor.extra_state_attributes == {
        "price": 0.15,
        "is_negative": False,
    }
    assert tomorrow_sensor.native_value is None
    assert tomorrow_sensor.available is False
    assert tomorrow_sensor.extra_state_attributes == {}


@pytest.mark.unit
def test_buy_window_sensor_sets_is_negative_true_only_for_negative_average(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _day_buy_sensor(
        _buy_payload_for_hours(8, {10: 0.40, 11: -0.20, 12: -0.30, 13: 0.50})
    )

    assert sensor.native_value == "11:00"
    assert sensor.extra_state_attributes == {
        "price": -0.25,
        "is_negative": True,
    }


@pytest.mark.unit
def test_buy_window_sensor_keeps_zero_average_available_with_false_is_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _day_buy_sensor(
        _buy_payload_for_hours(8, {10: 0.20, 11: -0.20, 12: 0.30, 13: 0.40})
    )

    assert sensor.native_value == "10:00"
    assert sensor.extra_state_attributes == {
        "price": 0.0,
        "is_negative": False,
    }


@pytest.mark.unit
def test_buy_window_sensors_have_translation_keys_and_prefixed_unique_ids() -> None:
    today_night = _night_buy_sensor(_buy_payload_for_hours(8, {0: 0.50, 1: 0.10, 2: 0.20}))
    tomorrow_day = _day_buy_tomorrow_sensor(
        _buy_payload_for_hours(9, {10: 0.90, 11: 0.60, 12: -0.20, 13: 0.80})
    )

    assert today_night.translation_key == "night_buy_window"
    assert today_night.unique_id == "entry-1_night_buy_window"
    assert tomorrow_day.translation_key == "day_buy_window_tomorrow"
    assert tomorrow_day.unique_id == "entry-1_day_buy_window_tomorrow"


@pytest.mark.unit
def test_day_buy_window_sensor_publishes_expected_result_for_real_may_13_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 13, 12, 0, tzinfo=TZ))

    sensor = _day_buy_sensor(
        [
            {"time": "2026-05-13T00:00:00+02:00", "price": 0.833},
            {"time": "2026-05-13T01:00:00+02:00", "price": 0.805},
            {"time": "2026-05-13T02:00:00+02:00", "price": 0.787},
            {"time": "2026-05-13T03:00:00+02:00", "price": 0.792},
            {"time": "2026-05-13T04:00:00+02:00", "price": 0.805},
            {"time": "2026-05-13T05:00:00+02:00", "price": 0.855},
            {"time": "2026-05-13T06:00:00+02:00", "price": 1.327},
            {"time": "2026-05-13T07:00:00+02:00", "price": 1.348},
            {"time": "2026-05-13T08:00:00+02:00", "price": 1.279},
            {"time": "2026-05-13T09:00:00+02:00", "price": 1.177},
            {"time": "2026-05-13T10:00:00+02:00", "price": 1.095},
            {"time": "2026-05-13T11:00:00+02:00", "price": 1.065},
            {"time": "2026-05-13T12:00:00+02:00", "price": 1.057},
            {"time": "2026-05-13T13:00:00+02:00", "price": 1.031},
            {"time": "2026-05-13T14:00:00+02:00", "price": 1.02},
            {"time": "2026-05-13T15:00:00+02:00", "price": 0.67},
            {"time": "2026-05-13T16:00:00+02:00", "price": 0.758},
            {"time": "2026-05-13T17:00:00+02:00", "price": 1.238},
            {"time": "2026-05-13T18:00:00+02:00", "price": 1.344},
            {"time": "2026-05-13T19:00:00+02:00", "price": 1.426},
            {"time": "2026-05-13T20:00:00+02:00", "price": 1.475},
            {"time": "2026-05-13T21:00:00+02:00", "price": 1.428},
            {"time": "2026-05-13T22:00:00+02:00", "price": 0.938},
            {"time": "2026-05-13T23:00:00+02:00", "price": 0.884},
        ]
    )

    assert sensor.native_value == "15:00"
    assert sensor.extra_state_attributes == {
        "price": 0.714,
        "is_negative": False,
    }


@pytest.mark.unit
def test_existing_sell_window_sensor_behavior_is_unchanged_when_buy_payload_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = _coordinator_with_price_payloads(
        {
            "sensor.sell": {
                "prices_today": _ranked_payload_for_hours(8, {4: 0.40, 5: 0.85, 6: 0.72, 7: 0.91})
            },
            "sensor.buy": {
                "prices_today": _buy_payload_for_hours(8, {0: 0.50, 1: 0.10, 2: 0.20, 3: 0.80})
            },
        }
    )
    sell_sensor = MorningSellWindowSensor(
        coordinator,
        _mock_entry(),
        {CONF_SELL_PRICE_SENSOR: "sensor.sell", CONF_BUY_PRICE_SENSOR: "sensor.buy"},
    )
    buy_sensor = NightBuyWindowSensor(
        coordinator,
        _mock_entry(),
        {CONF_SELL_PRICE_SENSOR: "sensor.sell", CONF_BUY_PRICE_SENSOR: "sensor.buy"},
    )
    sell_sensor.hass = MagicMock()
    buy_sensor.hass = MagicMock()

    assert sell_sensor.native_value == "07:00"
    assert buy_sensor.native_value == "01:00"

    coordinator.data["price_payloads"]["sensor.buy"]["prices_today"] = _buy_payload_for_hours(
        8,
        {0: 0.90, 1: 0.80, 2: 0.10, 3: 0.20},
    )

    assert sell_sensor.native_value == "07:00"
    assert sell_sensor.extra_state_attributes == {
        "price": 0.91,
        "second_window_start": "05:00",
        "second_window_price": 0.85,
        "second_window_gap_pct": 6.6,
    }
    assert buy_sensor.native_value == "02:00"
