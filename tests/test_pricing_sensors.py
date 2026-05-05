"""Tests for price-related Energy Optimizer sensors."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.energy_optimizer.const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_SELL_PRICE_SENSOR,
)
from custom_components.energy_optimizer.entities.sensors.pricing import (
    BuyPriceSensor,
    MinArbitrageMarginSensor,
    SellPriceSensor,
)


def _mock_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {}
    entry.options = {}
    return entry


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
