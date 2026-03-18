"""Morning peak sell decision logic."""
from __future__ import annotations

from dataclasses import replace
import logging
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_battery_reserve, calculate_battery_space
from ..calculations.energy import (
    calculate_losses,
    calculate_sufficiency_window,
    calculate_surplus_energy,
)
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_MIN_SOC_PV,
    CONF_MORNING_MAX_PRICE_SENSOR,
    DEFAULT_MIN_SOC_PV,
    DOMAIN,
    SUN_ENTITY,
)
from ..decision_engine.common import (
    ForecastData,
    build_evening_sell_outcome,
    build_no_action_outcome,
    compute_sufficiency,
    get_required_prog3_soc_state,
)
from ..helpers import (
    get_float_state_info,
    get_required_float_state,
    resolve_morning_max_price_hour,
    resolve_tariff_end_hour,
)
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome
from ..utils.time_window import build_hour_window
from .sell_base import BaseSellStrategy, SellRequest

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


class MorningSellStrategy(BaseSellStrategy):
    """Morning sell strategy using single surplus branch."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry_id: str | None,
        margin: float | None,
    ) -> None:
        """Initialize morning sell strategy."""
        super().__init__(hass, entry_id=entry_id, margin=margin)
        self._allow_min_soc_pv = False

    @property
    def scenario_name(self) -> str:
        """Scenario display name."""
        return "Morning Peak Sell"

    @property
    def sell_type(self) -> str:
        """Sell type persisted for restore."""
        return "morning"

    def _get_target_soc_floor(self, *, surplus_kwh: float) -> float:
        """Use PV floor only when sufficiency is confirmed for morning sell."""
        if self._allow_min_soc_pv:
            return self.battery_config.min_soc_pv
        return self.battery_config.min_soc

    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        """Resolve program SOC entity/value for morning sell."""
        return get_required_prog3_soc_state(self.hass, self.config)

    def _get_price(self) -> float | None:
        """Resolve morning max price state."""
        return get_required_float_state(
            self.hass,
            self.config.get(CONF_MORNING_MAX_PRICE_SENSOR),
            entity_name="Morning max price sensor",
        )

    def _resolve_sell_hour(self) -> int:
        """Resolve morning sell hour."""
        return resolve_morning_max_price_hour(self.hass, self.config, default_hour=7)

    async def _on_price_unavailable(self) -> bool:
        """Fall back to surplus-over-space sell when morning price sensor is unavailable."""
        _LOGGER.info(
            "Morning max price sensor unavailable - falling back to surplus-over-space sell"
        )
        self.price = 0.0
        self._price_unavailable = True
        return True

    async def _evaluate_sell(self) -> DecisionOutcome | SellRequest:
        """Run morning sell logic using a single surplus branch."""
        self._allow_min_soc_pv = False
        start_hour = (self._now_hour + 1) % 24
        base_end_hour = resolve_tariff_end_hour(self.hass, self.config, default_hour=13)

        hourly_usage = build_hourly_usage_array(
            self.config,
            self.hass.states.get,
            daily_load_fallback=None,
        )

        base_window = build_hour_window(start_hour, base_end_hour)
        base_hours = max(len(base_window), 1)
        base_usage_kwh = sum(hourly_usage[hour] for hour in base_window)
        base_heat_pump_kwh, base_heat_pump_hourly = await get_heat_pump_forecast_window(
            self.hass,
            self.config,
            start_hour=start_hour,
            end_hour=base_end_hour,
        )
        base_pv_forecast_kwh, base_pv_forecast_hourly = get_pv_forecast_window(
            self.hass,
            self.config,
            start_hour=start_hour,
            end_hour=base_end_hour,
            apply_efficiency=True,
            compensate=True,
            entry_id=self.entry.entry_id,
        )
        base_losses_hourly, _ = calculate_losses(
            self.hass,
            self.config,
            hours=base_hours,
        )

        if _LOGGER.isEnabledFor(logging.DEBUG):
            base_usage_hourly = {
                hour: round(hourly_usage[hour], 3)
                for hour in base_window
            }
            base_heat_pump_hourly_map = {
                hour: round(base_heat_pump_hourly.get(hour, 0.0), 3)
                for hour in base_window
            }
            base_pv_hourly_map = {
                hour: round(base_pv_forecast_hourly.get(hour, 0.0), 3)
                for hour in base_window
            }
            _LOGGER.debug(
                "Morning sell base input window %02d:00-%02d:00 | hours=%d | "
                "usage_kwh=%.3f heat_pump_kwh=%.3f pv_forecast_kwh=%.3f losses_hourly_kwh=%.3f losses_kwh=%.3f margin=%.3f",
                start_hour,
                base_end_hour,
                base_hours,
                base_usage_kwh,
                base_heat_pump_kwh,
                base_pv_forecast_kwh,
                base_losses_hourly,
                base_losses_hourly * base_hours,
                self.margin,
            )
            _LOGGER.debug("Morning sell usage hourly base: %s", base_usage_hourly)
            _LOGGER.debug("Morning sell heat pump hourly base: %s", base_heat_pump_hourly_map)
            _LOGGER.debug("Morning sell PV hourly base: %s", base_pv_hourly_map)

        def _resolve_required_and_pv(
            forecasts: ForecastData,
        ) -> tuple[float, float, object]:
            suff = compute_sufficiency(
                forecasts,
                calculator=calculate_sufficiency_window,
            )
            if suff.sufficiency_reached:
                required = suff.required_sufficiency_kwh
                pv_kwh = suff.pv_sufficiency_kwh
            else:
                required = suff.required_kwh
                pv_kwh = forecasts.pv_forecast_kwh
            return required, pv_kwh, suff

        base_forecasts = ForecastData(
            start_hour=start_hour,
            end_hour=base_end_hour,
            hours=base_hours,
            hourly_usage=hourly_usage,
            usage_kwh=base_usage_kwh,
            heat_pump_kwh=base_heat_pump_kwh,
            heat_pump_hourly=base_heat_pump_hourly,
            pv_forecast_kwh=base_pv_forecast_kwh,
            pv_forecast_hourly=base_pv_forecast_hourly,
            losses_hourly=base_losses_hourly,
            losses_kwh=base_losses_hourly * base_hours,
            margin=self.margin,
        )

        required_kwh, pv_forecast_kwh, sufficiency = _resolve_required_and_pv(base_forecasts)
        self._allow_min_soc_pv = sufficiency.sufficiency_reached

        heat_pump_kwh = base_heat_pump_kwh
        losses_kwh = base_forecasts.losses_kwh

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Morning sell sufficiency | reached=%s sufficiency_hour=%s required_kwh=%.3f pv_forecast_kwh=%.3f",
                sufficiency.sufficiency_reached,
                sufficiency.sufficiency_hour,
                required_kwh,
                pv_forecast_kwh,
            )
        reserve_kwh = calculate_battery_reserve(
            self.current_soc,
            self.battery_config.min_soc_pv,
            self.battery_config.capacity_ah,
            self.battery_config.voltage,
            efficiency=self.battery_config.efficiency,
        )
        surplus_kwh = calculate_surplus_energy(
            reserve_kwh,
            required_kwh,
            pv_forecast_kwh,
        )
        _LOGGER.debug(
            "Morning sell calculation | required_kwh=%.3f (from sufficiency model) | "
            "base_usage_kwh=%.3f base_heat_pump_kwh=%.3f losses_kwh=%.3f margin=%.3f | "
            "available=(reserve %.3f + pv %.3f)=%.3f kWh | surplus=%.3f kWh",
            required_kwh,
            base_usage_kwh,
            base_heat_pump_kwh,
            losses_kwh,
            self.margin,
            reserve_kwh,
            pv_forecast_kwh,
            reserve_kwh + pv_forecast_kwh,
            surplus_kwh,
        )

        free_space_kwh: float
        battery_space_entity_id: str | None = None
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        if isinstance(entry_data, dict):
            battery_space_sensor = entry_data.get("battery_space_sensor")
            battery_space_entity_id = getattr(battery_space_sensor, "entity_id", None)

        if battery_space_entity_id:
            free_space_kwh_raw, _, free_space_error = get_float_state_info(
                self.hass,
                battery_space_entity_id,
            )
            if free_space_error is None and free_space_kwh_raw is not None:
                free_space_kwh = free_space_kwh_raw
            else:
                free_space_kwh = calculate_battery_space(
                    self.current_soc,
                    self.battery_config.max_soc,
                    self.battery_config.capacity_ah,
                    self.battery_config.voltage,
                )
        else:
            free_space_kwh = calculate_battery_space(
                self.current_soc,
                self.battery_config.max_soc,
                self.battery_config.capacity_ah,
                self.battery_config.voltage,
            )

        evening_price = get_required_float_state(
            self.hass,
            self.config.get(CONF_EVENING_MAX_PRICE_SENSOR),
            entity_name="Evening max price sensor",
        )

        selected_surplus_kwh = surplus_kwh
        surplus_to_sunset: float | None = None
        selection_reason = "base_surplus"

        price_unavailable = getattr(self, "_price_unavailable", False)
        if surplus_kwh > free_space_kwh and not price_unavailable:
            if evening_price is not None and self.price > evening_price:
                selected_surplus_kwh = surplus_kwh
                selection_reason = "morning_price_higher_than_evening"
            else:
                selected_surplus_kwh = max(free_space_kwh - surplus_kwh, 0.0)
                selection_reason = "pv_fit_fallback_from_free_space"
        else:
            surplus_end_hour = 19
            sun_state = self.hass.states.get(SUN_ENTITY)
            if sun_state is None:
                _LOGGER.warning(
                    "Morning sell: %s not found, using default surplus end hour %02d:00",
                    SUN_ENTITY,
                    surplus_end_hour,
                )
            else:
                next_setting_raw = sun_state.attributes.get("next_setting")
                if next_setting_raw is None:
                    _LOGGER.warning(
                        "Morning sell: %s missing next_setting, using default surplus end hour %02d:00",
                        SUN_ENTITY,
                        surplus_end_hour,
                    )
                else:
                    next_setting_dt = dt_util.parse_datetime(str(next_setting_raw))
                    if next_setting_dt is None:
                        _LOGGER.warning(
                            "Morning sell: cannot parse next_setting '%s', using default surplus end hour %02d:00",
                            next_setting_raw,
                            surplus_end_hour,
                        )
                    else:
                        surplus_end_hour = dt_util.as_local(next_setting_dt).hour
            surplus_window = build_hour_window(start_hour, surplus_end_hour)
            surplus_hours = max(len(surplus_window), 1)
            surplus_usage_kwh = sum(hourly_usage[hour] for hour in surplus_window)
            surplus_heat_pump_kwh, surplus_heat_pump_hourly = await get_heat_pump_forecast_window(
                self.hass,
                self.config,
                start_hour=start_hour,
                end_hour=surplus_end_hour,
            )
            surplus_pv_forecast_kwh, surplus_pv_forecast_hourly = get_pv_forecast_window(
                self.hass,
                self.config,
                start_hour=start_hour,
                end_hour=surplus_end_hour,
                apply_efficiency=True,
                compensate=True,
                entry_id=self.entry.entry_id,
            )
            surplus_losses_hourly, _ = calculate_losses(
                self.hass,
                self.config,
                hours=surplus_hours,
            )
            forecasts_to_sunset = ForecastData(
                start_hour=start_hour,
                end_hour=surplus_end_hour,
                hours=surplus_hours,
                hourly_usage=hourly_usage,
                usage_kwh=surplus_usage_kwh,
                heat_pump_kwh=surplus_heat_pump_kwh,
                heat_pump_hourly=surplus_heat_pump_hourly,
                pv_forecast_kwh=surplus_pv_forecast_kwh,
                pv_forecast_hourly=surplus_pv_forecast_hourly,
                losses_hourly=surplus_losses_hourly,
                losses_kwh=surplus_losses_hourly * surplus_hours,
                margin=self.margin,
            )
            required_to_sunset_kwh, pv_to_sunset_kwh, _suff_to_sunset = _resolve_required_and_pv(
                forecasts_to_sunset
            )
            surplus_to_sunset = calculate_surplus_energy(
                reserve_kwh,
                required_to_sunset_kwh,
                pv_to_sunset_kwh,
            )

            if surplus_to_sunset <= free_space_kwh:
                selected_surplus_kwh = 0.0
                selection_reason = "surplus_to_sunset_not_above_free_space"
            else:
                selected_surplus_kwh = min(
                    surplus_kwh,
                    surplus_to_sunset - free_space_kwh,
                )
                selection_reason = "surplus_to_sunset_above_free_space"

        selected_surplus_kwh = max(selected_surplus_kwh, 0.0)

        if selected_surplus_kwh <= 0.0:
            return build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No morning peak sell action",
                reason="No eligible surplus energy available for selling",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                sufficiency_hour=sufficiency.sufficiency_hour,
                sufficiency_reached=sufficiency.sufficiency_reached,
                details_extra={
                    "morning_price": None if price_unavailable else round(self.price, 2),
                    "evening_price": round(evening_price, 2) if evening_price is not None else None,
                    "threshold_price": round(self.threshold_price, 2),
                    "surplus_kwh": round(surplus_kwh, 2),
                    "selected_surplus_kwh": round(selected_surplus_kwh, 2),
                    "free_space_kwh": round(free_space_kwh, 2),
                    "surplus_to_sunset_kwh": (
                        round(surplus_to_sunset, 2)
                        if surplus_to_sunset is not None
                        else None
                    ),
                    "surplus_selection_reason": selection_reason,
                    "price_unavailable": price_unavailable,
                    "start_hour": start_hour,
                    "end_hour": base_end_hour,
                },
            )

        def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
            outcome = build_evening_sell_outcome(
                scenario=self.scenario_name,
                action_type="sell",
                price_metric_key="morning_price",
                threshold_metric_key="threshold_price",
                target_soc=target_soc,
                current_soc=self.current_soc,
                surplus_kwh=surplus,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                heat_pump_kwh=heat_pump_kwh,
                losses_kwh=losses_kwh,
                start_hour=start_hour,
                end_hour=base_end_hour,
                export_power_w=export_w,
                evening_price=None if price_unavailable else self.price,
                threshold_price=self.threshold_price,
            )
            outcome.details["sufficiency_hour"] = sufficiency.sufficiency_hour
            outcome.details["sufficiency_reached"] = sufficiency.sufficiency_reached
            outcome.details["evening_price"] = (
                round(evening_price, 2) if evening_price is not None else None
            )
            outcome.details["free_space_kwh"] = round(free_space_kwh, 2)
            outcome.details["surplus_kwh_base"] = round(surplus_kwh, 2)
            outcome.details["selected_surplus_kwh"] = round(surplus, 2)
            outcome.details["surplus_to_sunset_kwh"] = (
                round(surplus_to_sunset, 2)
                if surplus_to_sunset is not None
                else None
            )
            outcome.details["surplus_selection_reason"] = selection_reason
            outcome.details["price_unavailable"] = price_unavailable
            return outcome

        def _make_no_action(current_surplus_kwh: float) -> DecisionOutcome:
            return build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No morning peak sell action",
                reason="Calculated target SOC does not require discharge",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                sufficiency_hour=sufficiency.sufficiency_hour,
                sufficiency_reached=sufficiency.sufficiency_reached,
                details_extra={
                    "morning_price": None if price_unavailable else round(self.price, 2),
                    "evening_price": (
                        round(evening_price, 2) if evening_price is not None else None
                    ),
                    "threshold_price": round(self.threshold_price, 2),
                    "surplus_kwh": round(current_surplus_kwh, 2),
                    "surplus_kwh_base": round(surplus_kwh, 2),
                    "free_space_kwh": round(free_space_kwh, 2),
                    "surplus_to_sunset_kwh": (
                        round(surplus_to_sunset, 2)
                        if surplus_to_sunset is not None
                        else None
                    ),
                    "surplus_selection_reason": selection_reason,
                    "price_unavailable": price_unavailable,
                    "start_hour": start_hour,
                    "end_hour": base_end_hour,
                },
            )

        return SellRequest(
            surplus_kwh=selected_surplus_kwh,
            build_outcome_fn=_make_outcome,
            build_no_action_fn=_make_no_action,
        )


async def async_run_morning_sell(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
) -> None:
    """Run morning peak sell routine."""
    strategy = MorningSellStrategy(hass, entry_id=entry_id, margin=margin)
    await strategy.run()
