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
from custom_components.energy_optimizer.entities.sensors.pricing import (
    BuyPriceSensor,
    MiddaySellWindowSensor,
    MiddaySellWindowTomorrowSensor,
    MinArbitrageMarginSensor,
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
    coordinator = _coordinator_with_prices(_payload(low_start_hour=10), "sensor.sell")
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

