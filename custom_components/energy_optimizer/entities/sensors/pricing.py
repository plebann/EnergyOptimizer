"""Price-related sensors for Energy Optimizer."""
from __future__ import annotations

from homeassistant.components.sensor import SensorStateClass

from ..base import EnergyOptimizerSensor
from ...calculations.price_windows import (
    find_cheapest_midday_sell_window,
    format_sell_window,
)
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


class MiddaySellWindowSensor(EnergyOptimizerSensor):
    """Sensor publishing the cheapest 8-quarter-hour midday sell-price window.

    Reads the current-day sell-price series directly from the Home Assistant
    state object and publishes the cheapest contiguous window between 08:00 and
    16:00 as a text value in HH:MM-HH-MM format.  When sufficient data is not
    available the sensor becomes unavailable (native_value returns None).
    """

    _attr_translation_key = "midday_sell_window"
    _attr_unique_id = "midday_sell_window"
    _attr_icon = "mdi:clock-time-eight-outline"

    @property
    def native_value(self) -> str | None:
        """Return the cheapest midday sell-price window as HH:MM-HH-MM, or None."""
        entity_id = self.config.get(CONF_SELL_PRICE_SENSOR)
        result = find_cheapest_midday_sell_window(self.hass, entity_id)
        if result is None:
            return None
        return format_sell_window(result)
