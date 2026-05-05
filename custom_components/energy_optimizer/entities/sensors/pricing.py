"""Price-related sensors for Energy Optimizer."""
from __future__ import annotations

from homeassistant.components.sensor import SensorStateClass

from ..base import EnergyOptimizerSensor
from ...const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_SELL_PRICE_SENSOR,
    DEFAULT_MIN_ARBITRAGE_PRICE,
    PRICE_UNIT_PLN_PER_KWH,
)


class _PriceValueSensor(EnergyOptimizerSensor):
    """Base sensor for values expressed in PLN/kWh."""

    _attr_native_unit_of_measurement = PRICE_UNIT_PLN_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3

    @staticmethod
    def _round_value(value: float | None) -> float | None:
        """Normalize output values to 3 decimal places."""
        if value is None:
            return None
        return round(value, 3)


class BuyPriceSensor(_PriceValueSensor):
    """Sensor mirroring the configured buy price source."""

    _attr_translation_key = "buy_price"
    _attr_unique_id = "buy_price"
    _attr_icon = "mdi:cart"

    @property
    def native_value(self) -> float | None:
        """Return the configured buy price."""
        return self._round_value(
            self._get_state_value(self.config.get(CONF_BUY_PRICE_SENSOR))
        )


class SellPriceSensor(_PriceValueSensor):
    """Sensor mirroring the configured sell price source."""

    _attr_translation_key = "sell_price"
    _attr_unique_id = "sell_price"
    _attr_icon = "mdi:cash-fast"

    @property
    def native_value(self) -> float | None:
        """Return the configured sell price."""
        return self._round_value(
            self._get_state_value(self.config.get(CONF_SELL_PRICE_SENSOR))
        )


class MinArbitrageMarginSensor(_PriceValueSensor):
    """Sensor exposing the configured minimum arbitrage margin."""

    _attr_translation_key = "min_arbitrage_margin"
    _attr_unique_id = "min_arbitrage_margin"
    _attr_icon = "mdi:swap-horizontal-bold"

    @property
    def native_value(self) -> float:
        """Return the configured minimum arbitrage margin."""
        configured = self.config.get(
            CONF_MIN_ARBITRAGE_PRICE,
            DEFAULT_MIN_ARBITRAGE_PRICE,
        )
        return round(float(configured or 0.0), 3)
