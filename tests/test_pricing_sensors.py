"""Tests for price-related Energy Optimizer sensors."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
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
    MinArbitrageMarginSensor,
    SellPriceSensor,
)

# UTC+2 offset used across all sensor tests
TZ = timezone(timedelta(hours=2))
TODAY = date(2026, 5, 8)
SLOT = timedelta(minutes=15)


def _mock_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {}
    entry.options = {}
    return entry


def _midday_sensor(prices: list[dict], sell_entity: str = "sensor.sell_price") -> MiddaySellWindowSensor:
    """Build a MiddaySellWindowSensor with a mock hass containing the given prices."""
    coordinator = MagicMock()
    coordinator.data = {"states": {}}

    state = MagicMock()
    state.attributes = {"prices": prices}

    hass = MagicMock()
    hass.states.get.return_value = state

    sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), {CONF_SELL_PRICE_SENSOR: sell_entity})
    sensor.hass = hass
    return sensor


def _full_midday_entries(low_start_slot: int = 8, low_price: float = 0.5) -> list[dict]:
    """32 entries covering 08:00-16:00; low_price on slots low_start_slot … +7."""
    entries = []
    for i in range(32):
        h = 8 + (i * 15) // 60
        m = (i * 15) % 60
        price = low_price if low_start_slot <= i < low_start_slot + 8 else 1.0
        dt = datetime(2026, 5, 8, h, m, tzinfo=TZ)
        entries.append({
            "dtime": dt.isoformat(),
            "period": f"{dt.strftime('%H:%M')} - {(dt + SLOT).strftime('%H:%M')}",
            "rce_pln": price,
            "business_date": "2026-05-08",
        })
    return entries


# ──────────────────────────────────────────────────────────────────────────────
# Existing sensor tests


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


# ──────────────────────────────────────────────────────────────────────────────
# MiddaySellWindowSensor – US1: publication of cheapest window


@pytest.mark.unit
def test_midday_sell_window_sensor_publishes_correct_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _midday_sensor(_full_midday_entries(low_start_slot=8))
    # low_start_slot=8 → cheapest window starts at 10:00 (slot 8 = 08:00 + 8*15min)
    assert sensor.native_value == "10:00-12-00"


@pytest.mark.unit
def test_midday_sell_window_sensor_publishes_separate_from_buy_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sensor is wired to sell-price entity only; buy-price config has no effect."""
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = MagicMock()
    coordinator.data = {"states": {}}

    sell_state = MagicMock()
    sell_state.attributes = {"prices": _full_midday_entries(low_start_slot=8)}

    hass = MagicMock()
    hass.states.get.side_effect = lambda eid: sell_state if eid == "sensor.sell" else None

    config = {
        CONF_SELL_PRICE_SENSOR: "sensor.sell",
        CONF_BUY_PRICE_SENSOR: "sensor.buy",
    }
    sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), config)
    sensor.hass = hass

    # Should return a value based on sell entity
    assert sensor.native_value is not None
    # buy entity is never consulted for window calculation
    hass.states.get.assert_called_with("sensor.sell")


# ──────────────────────────────────────────────────────────────────────────────
# MiddaySellWindowSensor – US2: stable HH:MM-HH-MM format


@pytest.mark.unit
def test_midday_sell_window_sensor_format_hh_mm_hh_mm(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _midday_sensor(_full_midday_entries(low_start_slot=0))
    # low_start_slot=0 → cheapest window starts at 08:00
    value = sensor.native_value
    assert value is not None
    # Must match HH:MM-HH-MM pattern
    parts = value.split("-")
    assert len(parts) == 3, f"Expected 3 dash-separated parts, got: {value!r}"
    start_part = parts[0]  # "HH:MM"
    assert ":" in start_part
    end_h, end_m = parts[1], parts[2]
    assert end_h.isdigit() and end_m.isdigit()


@pytest.mark.unit
def test_midday_sell_window_sensor_updates_when_prices_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sensor reflects updated prices on subsequent native_value reads."""
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    # First evaluation: cheapest at 10:00
    state = MagicMock()
    state.attributes = {"prices": _full_midday_entries(low_start_slot=8)}
    hass = MagicMock()
    hass.states.get.return_value = state
    coordinator = MagicMock()
    coordinator.data = {"states": {}}

    sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), {CONF_SELL_PRICE_SENSOR: "sensor.sell"})
    sensor.hass = hass

    first_value = sensor.native_value
    assert first_value == "10:00-12-00"

    # Second evaluation: price data changed, cheapest now at 08:00
    state.attributes = {"prices": _full_midday_entries(low_start_slot=0)}
    second_value = sensor.native_value
    assert second_value == "08:00-10-00"
    assert first_value != second_value


# ──────────────────────────────────────────────────────────────────────────────
# MiddaySellWindowSensor – US3: unavailable on insufficient data


@pytest.mark.unit
def test_midday_sell_window_sensor_unavailable_when_no_sell_price_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    hass = MagicMock()
    hass.states.get.return_value = None

    sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), {})
    sensor.hass = hass

    assert sensor.native_value is None


@pytest.mark.unit
def test_midday_sell_window_sensor_unavailable_when_prices_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    sensor = _midday_sensor([])
    assert sensor.native_value is None


@pytest.mark.unit
def test_midday_sell_window_sensor_unavailable_when_fewer_than_8_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    # Only 7 contiguous slots
    entries = []
    for i in range(7):
        dt = datetime(2026, 5, 8, 8, i * 15, tzinfo=TZ)
        entries.append({
            "dtime": dt.isoformat(),
            "rce_pln": 0.5,
            "business_date": "2026-05-08",
        })

    sensor = _midday_sensor(entries)
    assert sensor.native_value is None


@pytest.mark.unit
def test_midday_sell_window_sensor_reads_only_sell_price_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirm the sensor only calls hass.states.get with the sell-price entity ID."""
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    hass = MagicMock()
    hass.states.get.return_value = None  # returns None → unavailable

    config = {
        CONF_SELL_PRICE_SENSOR: "sensor.sell_source",
        CONF_BUY_PRICE_SENSOR: "sensor.buy_source",
    }
    sensor = MiddaySellWindowSensor(coordinator, _mock_entry(), config)
    sensor.hass = hass

    sensor.native_value

    called_ids = [call.args[0] for call in hass.states.get.call_args_list]
    assert "sensor.sell_source" in called_ids
    assert "sensor.buy_source" not in called_ids

