"""Morning peak sell decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..calculations.battery import calculate_battery_reserve
from ..calculations.energy import (
    calculate_losses,
    calculate_sufficiency_window,
    calculate_surplus_energy,
)
from ..calculations.utils import build_hourly_usage_array
from ..const import CONF_MORNING_MAX_PRICE_SENSOR
from ..decision_engine.common import (
    ForecastData,
    build_evening_sell_outcome,
    build_no_action_outcome,
    compute_sufficiency,
    get_required_prog3_soc_state,
)
from ..helpers import (
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

    @property
    def scenario_name(self) -> str:
        """Scenario display name."""
        return "Morning Peak Sell"

    @property
    def sell_type(self) -> str:
        """Sell type persisted for restore."""
        return "morning"

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

    async def _evaluate_sell(self) -> DecisionOutcome | SellRequest:
        """Run morning sell logic using a single surplus branch."""
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
            apply_efficiency=False,
            compensate=True,
            entry_id=self.entry.entry_id,
        )
        base_losses_hourly, _base_losses_kwh = calculate_losses(
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
        sufficiency = compute_sufficiency(
            base_forecasts,
            calculator=calculate_sufficiency_window,
        )

        effective_end_hour = base_end_hour
        if sufficiency.sufficiency_reached:
            effective_end_hour = min(sufficiency.sufficiency_hour, base_end_hour)

        effective_window = build_hour_window(start_hour, effective_end_hour)
        effective_hours = max(len(effective_window), 1)
        usage_kwh = sum(hourly_usage[hour] for hour in effective_window)
        heat_pump_kwh = sum(base_heat_pump_hourly.get(hour, 0.0) for hour in effective_window)
        pv_forecast_kwh = sum(base_pv_forecast_hourly.get(hour, 0.0) for hour in effective_window)
        losses_kwh = base_losses_hourly * effective_hours

        if _LOGGER.isEnabledFor(logging.DEBUG):
            effective_usage_hourly = {
                hour: round(hourly_usage[hour], 3)
                for hour in effective_window
            }
            effective_heat_pump_hourly_map = {
                hour: round(base_heat_pump_hourly.get(hour, 0.0), 3)
                for hour in effective_window
            }
            effective_pv_hourly_map = {
                hour: round(base_pv_forecast_hourly.get(hour, 0.0), 3)
                for hour in effective_window
            }
            _LOGGER.debug(
                "Morning sell sufficiency | reached=%s sufficiency_hour=%s effective_window=%02d:00-%02d:00 hours=%d",
                sufficiency.sufficiency_reached,
                sufficiency.sufficiency_hour,
                start_hour,
                effective_end_hour,
                effective_hours,
            )
            _LOGGER.debug(
                "Morning sell effective totals | usage_kwh=%.3f heat_pump_kwh=%.3f pv_forecast_kwh=%.3f losses_kwh=%.3f",
                usage_kwh,
                heat_pump_kwh,
                pv_forecast_kwh,
                losses_kwh,
            )
            _LOGGER.debug("Morning sell usage hourly effective: %s", effective_usage_hourly)
            _LOGGER.debug("Morning sell heat pump hourly effective: %s", effective_heat_pump_hourly_map)
            _LOGGER.debug("Morning sell PV hourly effective: %s", effective_pv_hourly_map)

        required_kwh = (usage_kwh + heat_pump_kwh + losses_kwh) * self.margin
        reserve_kwh = calculate_battery_reserve(
            self.current_soc,
            self.bc.min_soc,
            self.bc.capacity_ah,
            self.bc.voltage,
            efficiency=self.bc.efficiency,
        )
        surplus_kwh = calculate_surplus_energy(
            reserve_kwh,
            required_kwh,
            pv_forecast_kwh,
        )
        _LOGGER.debug(
            "Morning sell calculation | required=(usage %.3f + hp %.3f + losses %.3f) * margin %.3f = %.3f kWh | "
            "available=(reserve %.3f + pv %.3f)=%.3f kWh | surplus=%.3f kWh",
            usage_kwh,
            heat_pump_kwh,
            losses_kwh,
            self.margin,
            required_kwh,
            reserve_kwh,
            pv_forecast_kwh,
            reserve_kwh + pv_forecast_kwh,
            surplus_kwh,
        )

        if surplus_kwh <= 0.0:
            return build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No morning peak sell action",
                reason="No surplus energy available for selling",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                sufficiency_hour=sufficiency.sufficiency_hour,
                sufficiency_reached=sufficiency.sufficiency_reached,
                key_metrics_extra={
                    "morning_price": f"{self.price:.1f} PLN/MWh",
                    "threshold_price": f"{self.threshold_price:.1f} PLN/MWh",
                    "window": f"{start_hour:02d}:00-{effective_end_hour:02d}:00",
                },
                full_details_extra={
                    "morning_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                    "start_hour": start_hour,
                    "end_hour": effective_end_hour,
                },
            )

        def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
            return build_evening_sell_outcome(
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
                end_hour=effective_end_hour,
                export_power_w=export_w,
                evening_price=self.price,
                threshold_price=self.threshold_price,
            )

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
                key_metrics_extra={
                    "morning_price": f"{self.price:.1f} PLN/MWh",
                    "threshold_price": f"{self.threshold_price:.1f} PLN/MWh",
                    "surplus": f"{current_surplus_kwh:.1f} kWh",
                    "window": f"{start_hour:02d}:00-{effective_end_hour:02d}:00",
                },
                full_details_extra={
                    "morning_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                    "surplus_kwh": round(current_surplus_kwh, 2),
                    "start_hour": start_hour,
                    "end_hour": effective_end_hour,
                },
            )

        return SellRequest(
            surplus_kwh=surplus_kwh,
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
