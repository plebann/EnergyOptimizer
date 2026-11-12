"""Price-related sensors for Energy Optimizer."""
from __future__ import annotations

from datetime import datetime
from math import copysign

from homeassistant.components.sensor import SensorStateClass
from homeassistant.util import dt as dt_util

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


def _local_now() -> datetime:
    """Return the tz-aware local time used to resolve and judge Market Windows."""
    now_local = dt_util.now()
    if now_local.tzinfo is None:
        now_local = now_local.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return now_local


class SnapshotCache:
    """Shares one Market Window snapshot among the window sensors.

    Resolves again only when the coordinator published new data or the minute
    changed, so one refresh of every window sensor reads the resolver once.
    """

    def __init__(self, coordinator, resolver) -> None:
        self._coordinator = coordinator
        self._resolver = resolver
        self._data: object = None
        self._minute: datetime | None = None
        self._snapshot = None

    def windows(self, now: datetime):
        """Return the cached snapshot, resolving it when stale."""
        minute = now.replace(second=0, microsecond=0)
        data = self._coordinator.data
        if self._snapshot is None or data is not self._data or minute != self._minute:
            self._snapshot = self._resolver.windows(now)
            self._data = data
            self._minute = minute
        return self._snapshot


class _SnapshotSensor(EnergyOptimizerSensor):
    """Base sensor projecting one field of the Market Window snapshot."""

    _snapshot_field: str

    def __init__(self, coordinator, config_entry, config, resolver) -> None:
        """Initialize the sensor with the resolver handed over by the platform."""
        self._resolver = resolver
        super().__init__(coordinator, config_entry, config)

    def _snapshot_window(self):
        """Return this sensor's field of the snapshot resolved now."""
        return getattr(self._resolver.windows(_local_now()), self._snapshot_field)


class _BuyWindowBaseSensor(_SnapshotSensor):
    """Base sensor for buy-price windows."""

    _attr_icon = "mdi:clock-time-two-outline"
    _display_window_range: bool = True
    _include_timestamps: bool = True
    _include_plan_date: bool = False
    _include_is_active: bool = False

    def __init__(self, coordinator, config_entry, config, resolver) -> None:
        """Initialize the sensor with the current snapshot."""
        super().__init__(coordinator, config_entry, config, resolver)
        self._attr_available = False
        self._apply_result(self._get_result())

    def _get_result(self):
        """Return the projected window, or None for a Default Market Window."""
        window = self._snapshot_window()
        return None if window.is_fallback else window

    def _apply_result(self, result) -> None:
        """Update cached state and attributes from the projected buy window."""
        if result is None:
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        self._attr_available = True
        self._attr_native_value = (
            f"{result.start:%H:%M}-{result.end:%H:%M}"
            if self._display_window_range
            else result.start.strftime("%H:%M")
        )
        self._attr_extra_state_attributes = {
            "end": result.end.strftime("%H:%M"),
            "duration_hours": int(result.duration_hours),
            "price": round(result.price, 3),
            # The resolver rounds -0.0004 to -0.0: the sign bit keeps it negative, a true 0.0 is not.
            "is_negative": copysign(1.0, result.price) < 0,
        }
        if self._include_plan_date:
            self._attr_extra_state_attributes["plan_date"] = result.plan_date.isoformat()
        if self._include_timestamps:
            self._attr_extra_state_attributes["start_time"] = result.start.isoformat()
            self._attr_extra_state_attributes["end_time"] = result.end.isoformat()
        if self._include_is_active:
            self._attr_extra_state_attributes["is_active"] = (
                "on" if result.contains(_local_now()) else "off"
            )

    @property
    def available(self) -> bool:
        """Return True only when the coordinator and buy-window result are available."""
        return super().available and self._attr_available

    @property
    def native_value(self) -> str | None:
        """Return the selected buy window as HH:MM-HH:MM, or None."""
        self._apply_result(self._get_result())
        return getattr(self, "_attr_native_value", None)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return buy-window details when a valid result exists."""
        self._apply_result(self._get_result())
        return getattr(self, "_attr_extra_state_attributes", {})

    def _handle_coordinator_update(self) -> None:
        """Handle updated coordinator data."""
        self._apply_result(self._get_result())
        super()._handle_coordinator_update()


class NightBuyWindowSensor(_BuyWindowBaseSensor):
    """Sensor publishing the current or most recently completed night plan."""

    _include_plan_date = True
    _include_is_active = True
    _attr_translation_key = "night_buy_window"
    _attr_unique_id = "night_buy_window"
    _snapshot_field = "night_buy_completed"


class NightBuyWindowTomorrowSensor(_BuyWindowBaseSensor):
    """Sensor publishing the current-before-06:01 or next planned night."""

    _include_plan_date = True
    _attr_translation_key = "night_buy_next_window"
    _attr_unique_id = "night_buy_next_window"
    _snapshot_field = "night_buy"


class DayBuyWindowTomorrowSensor(_BuyWindowBaseSensor):
    """Sensor publishing the best day buy window for tomorrow."""

    _include_plan_date = True
    _attr_translation_key = "day_buy_next_window"
    _attr_unique_id = "day_buy_next_window"
    _snapshot_field = "day_buy_next"


class DayBuyWindowSensor(_BuyWindowBaseSensor):
    """Sensor publishing the persisted current day buy plan."""

    _include_plan_date = True
    _include_is_active = True
    _attr_translation_key = "day_buy_window"
    _attr_unique_id = "day_buy_window"
    _snapshot_field = "day_buy"


# Public names retain their Python API while exposing the new entity names.
NightBuyWindowNextSensor = NightBuyWindowTomorrowSensor
DayBuyWindowNextSensor = DayBuyWindowTomorrowSensor


class MorningSellBuyReferenceSensor(_BuyWindowBaseSensor):
    """Sensor publishing the buy reference used by the morning sell margin gate."""

    _attr_translation_key = "morning_sell_buy_reference"
    _attr_unique_id = "morning_sell_buy_reference"
    _snapshot_field = "morning_sell_buy_reference"
    _display_window_range = False
    _include_timestamps = False


class _ConsumeWindowBaseSensor(_SnapshotSensor):
    """Base sensor for day-scoped consume windows."""

    _attr_icon = "mdi:clock-time-eight-outline"
    _include_is_active: bool = False

    def __init__(self, coordinator, config_entry, config, resolver) -> None:
        """Initialize the sensor with the current snapshot."""
        super().__init__(coordinator, config_entry, config, resolver)
        self._apply_result(self._get_result())

    def _get_result(self):
        """Return the projected window, or None for a Default Market Window."""
        window = self._snapshot_window()
        return None if window.is_fallback else window

    def _apply_result(self, result) -> None:
        """Update cached state and attributes from the projected window."""
        if result is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        self._attr_native_value = f"{result.start:%H:%M}-{result.end:%H:%M}"
        attributes: dict[str, object] = {}
        if result.price is not None:
            attributes["price"] = round(result.price, 2)
        if self._include_is_active:
            attributes["is_active"] = "on" if result.contains(_local_now()) else "off"

        self._attr_extra_state_attributes = attributes

    @property
    def native_value(self) -> str | None:
        """Return the cheapest consume window as HH:MM-HH:MM, or None."""
        self._apply_result(self._get_result())
        return getattr(self, "_attr_native_value", None)

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        """Return the rounded average price when a valid window exists."""
        self._apply_result(self._get_result())
        return getattr(self, "_attr_extra_state_attributes", {})

    def _handle_coordinator_update(self) -> None:
        """Handle updated coordinator data."""
        self._apply_result(self._get_result())
        super()._handle_coordinator_update()


class ConsumeWindowSensor(_ConsumeWindowBaseSensor):
    """Sensor publishing the cheapest 8-quarter-hour consume window."""

    _attr_translation_key = "consume_window"
    _attr_unique_id = "consume_window"
    _snapshot_field = "consume"
    _include_is_active = True


class ConsumeWindowTomorrowSensor(_ConsumeWindowBaseSensor):
    """Sensor publishing the cheapest consume window for tomorrow."""

    _attr_translation_key = "consume_window_tomorrow"
    _attr_unique_id = "consume_window_tomorrow"
    _snapshot_field = "consume_tomorrow"


class _RankedSellWindowBaseSensor(_SnapshotSensor):
    """Base sensor for ranked one-hour sell windows."""

    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(self, coordinator, config_entry, config, resolver) -> None:
        """Initialize the sensor with the current snapshot."""
        super().__init__(coordinator, config_entry, config, resolver)
        self._attr_available = False
        self._apply_result(self._get_result())

    def _get_result(self):
        """Return the projected ranking, or None for a Default Market Window."""
        ranked = self._snapshot_window()
        return None if ranked.primary.is_fallback else ranked

    def _apply_result(self, result) -> None:
        """Update cached state and attributes from the projected ranking."""
        if result is None:
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        self._attr_available = True
        primary, secondary = result.primary, result.secondary
        attributes: dict[str, object] = {}
        if primary.price is not None:
            attributes["price"] = round(primary.price, 3)
        if secondary is not None:
            attributes["second_window_start"] = secondary.start.strftime("%H:%M")
            if secondary.price is not None:
                attributes["second_window_price"] = round(secondary.price, 3)
                if primary.price:
                    attributes["second_window_gap_pct"] = round(
                        (primary.price - secondary.price) / primary.price * 100, 1
                    )

        self._attr_native_value = primary.start.strftime("%H:%M")
        self._attr_extra_state_attributes = attributes

    @property
    def available(self) -> bool:
        """Return True only when the coordinator and ranked sell-window result are available."""
        return super().available and self._attr_available

    @property
    def native_value(self) -> str | None:
        """Return the best one-hour sell window start time as HH:MM, or None."""
        self._apply_result(self._get_result())
        return getattr(self, "_attr_native_value", None)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return ranked sell-window details when a valid result exists."""
        self._apply_result(self._get_result())
        return getattr(self, "_attr_extra_state_attributes", {})

    def _handle_coordinator_update(self) -> None:
        """Handle updated coordinator data."""
        self._apply_result(self._get_result())
        super()._handle_coordinator_update()


class MorningSellWindowSensor(_RankedSellWindowBaseSensor):
    """Sensor publishing the best morning sell window for today."""

    _attr_translation_key = "morning_sell_window"
    _attr_unique_id = "morning_sell_window"
    _snapshot_field = "morning_sell"


class EveningSellWindowSensor(_RankedSellWindowBaseSensor):
    """Sensor publishing the best evening sell window for today."""

    _attr_translation_key = "evening_sell_window"
    _attr_unique_id = "evening_sell_window"
    _snapshot_field = "evening_sell"


class MorningSellWindowTomorrowSensor(_RankedSellWindowBaseSensor):
    """Sensor publishing the best morning sell window for tomorrow."""

    _attr_translation_key = "morning_sell_window_tomorrow"
    _attr_unique_id = "morning_sell_window_tomorrow"
    _snapshot_field = "morning_sell_tomorrow"


class EveningSellWindowTomorrowSensor(_RankedSellWindowBaseSensor):
    """Sensor publishing the best evening sell window for tomorrow."""

    _attr_translation_key = "evening_sell_window_tomorrow"
    _attr_unique_id = "evening_sell_window_tomorrow"
    _snapshot_field = "evening_sell_tomorrow"
