"""Evening peak sell decision logic."""
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
from ..const import CONF_EVENING_MAX_PRICE_SENSOR, CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR
from ..decision_engine.common import (
    ForecastData,
    build_evening_sell_outcome,
    build_no_action_outcome,
    build_surplus_sell_outcome,
    compute_sufficiency,
    get_required_prog5_soc_state,
)
from ..helpers import (
    get_required_float_state,
    resolve_evening_max_price_hour,
    resolve_tariff_end_hour,
    resolve_tariff_start_hour,
)
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome
from ..utils.time_window import build_hour_window
from .sell_base import BaseSellStrategy, SellRequest

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


class EveningSellStrategy(BaseSellStrategy):
    """Evening sell strategy using high-price and surplus branches."""

    @property
    def scenario_name(self) -> str:
        return "Evening Peak Sell"

    @property
    def sell_type(self) -> str:
        return "evening"

    @property
    def clamp_surplus_to_pv(self) -> bool:
        return True

    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        return get_required_prog5_soc_state(self.hass, self.config)

    def _get_price(self) -> float | None:
        return get_required_float_state(
            self.hass,
            self.config.get(CONF_EVENING_MAX_PRICE_SENSOR),
            entity_name="Evening max price sensor",
        )

    def _resolve_sell_hour(self) -> int:
        return resolve_evening_max_price_hour(self.hass, self.config, default_hour=17)

    async def _check_early_exit(self) -> DecisionOutcome | None:
        tomorrow_morning_price = get_required_float_state(
            self.hass,
            self.config.get(CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR),
            entity_name="Tomorrow morning max price sensor",
        )
        if tomorrow_morning_price is None:
            return None
        if self.price > tomorrow_morning_price:
            return None

        return build_no_action_outcome(
            scenario=self.scenario_name,
            summary="No evening peak sell action",
            reason="Evening price is not higher than tomorrow morning price",
            current_soc=self.current_soc,
            reserve_kwh=0.0,
            required_kwh=0.0,
            pv_forecast_kwh=0.0,
            key_metrics_extra={
                "evening_price": f"{self.price:.1f} PLN/MWh",
                "tomorrow_morning_price": f"{tomorrow_morning_price:.1f} PLN/MWh",
            },
            full_details_extra={
                "evening_price": round(self.price, 2),
                "tomorrow_morning_price": round(tomorrow_morning_price, 2),
            },
        )

    async def _evaluate_sell(self) -> DecisionOutcome | SellRequest:
        if self.price <= self.threshold_price:
            return await self._surplus_sell()
        return await self._high_price_sell()

    async def _high_price_sell(self) -> DecisionOutcome | SellRequest:
        start_hour = (self._now_hour + 1) % 24
        end_hour = resolve_tariff_start_hour(self.hass, self.config, default_hour=22)

        hours_window = build_hour_window(start_hour, end_hour)
        hours = max(len(hours_window), 1)
        hourly_usage = build_hourly_usage_array(
            self.config,
            self.hass.states.get,
            daily_load_fallback=None,
        )
        usage_kwh = sum(hourly_usage[hour] for hour in hours_window)

        heat_pump_kwh, _ = await get_heat_pump_forecast_window(
            self.hass,
            self.config,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        pv_forecast_kwh, _ = get_pv_forecast_window(
            self.hass,
            self.config,
            start_hour=start_hour,
            end_hour=end_hour,
            apply_efficiency=False,
            compensate=True,
            entry_id=self.entry.entry_id,
        )
        _, losses_kwh = calculate_losses(
            self.hass,
            self.config,
            hours=hours,
            margin=self.margin,
        )

        if _LOGGER.isEnabledFor(logging.DEBUG):
            hourly_breakdown = {
                hour: {
                    "usage_kwh": round(hourly_usage[hour], 3),
                }
                for hour in hours_window
            }
            _LOGGER.debug(
                "Evening high-price input window %02d:00-%02d:00 | hours=%d | "
                "usage_kwh=%.3f heat_pump_kwh=%.3f pv_forecast_kwh=%.3f losses_kwh=%.3f "
                "losses_hourly_kwh=%.3f margin=%.3f",
                start_hour,
                end_hour,
                hours,
                usage_kwh,
                heat_pump_kwh,
                pv_forecast_kwh,
                losses_kwh,
                losses_kwh / hours if hours > 0 else 0.0,
                self.margin,
            )
            _LOGGER.debug("Evening high-price usage hourly breakdown: %s", hourly_breakdown)

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
            "Evening high-price calculation | required=(usage %.3f + hp %.3f + losses %.3f) * margin %.3f = %.3f kWh | "
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
                summary="No evening peak sell action",
                reason="No surplus energy available for selling",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                key_metrics_extra={
                    "evening_price": f"{self.price:.1f} PLN/MWh",
                    "threshold_price": f"{self.threshold_price:.1f} PLN/MWh",
                },
                full_details_extra={
                    "evening_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                },
            )

        def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
            return build_evening_sell_outcome(
                target_soc=target_soc,
                current_soc=self.current_soc,
                surplus_kwh=surplus,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                heat_pump_kwh=heat_pump_kwh,
                losses_kwh=losses_kwh,
                start_hour=start_hour,
                end_hour=end_hour,
                export_power_w=export_w,
                evening_price=self.price,
                threshold_price=self.threshold_price,
            )

        def _make_no_action(_surplus: float) -> DecisionOutcome:
            return build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No evening peak sell action",
                reason="Calculated target SOC does not require discharge",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                key_metrics_extra={
                    "evening_price": f"{self.price:.1f} PLN/MWh",
                    "threshold_price": f"{self.threshold_price:.1f} PLN/MWh",
                },
                full_details_extra={
                    "evening_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                },
            )

        return SellRequest(
            surplus_kwh=surplus_kwh,
            build_outcome_fn=_make_outcome,
            build_no_action_fn=_make_no_action,
        )

    async def _surplus_sell(self) -> DecisionOutcome | SellRequest:
        hourly_usage = build_hourly_usage_array(
            self.config,
            self.hass.states.get,
            daily_load_fallback=None,
        )
        reserve_kwh = calculate_battery_reserve(
            self.current_soc,
            self.bc.min_soc,
            self.bc.capacity_ah,
            self.bc.voltage,
            efficiency=self.bc.efficiency,
        )

        tomorrow_end = resolve_tariff_end_hour(self.hass, self.config, default_hour=13)
        tomorrow_hp_kwh, tomorrow_hp_hourly = await get_heat_pump_forecast_window(
            self.hass,
            self.config,
            start_hour=0,
            end_hour=tomorrow_end,
        )
        tomorrow_pv_kwh, tomorrow_pv_hourly = get_pv_forecast_window(
            self.hass,
            self.config,
            start_hour=0,
            end_hour=tomorrow_end,
            apply_efficiency=True,
            compensate=True,
            entry_id=self.entry.entry_id,
        )
        tomorrow_losses_hourly, tomorrow_losses_kwh = calculate_losses(
            self.hass,
            self.config,
            hours=max(tomorrow_end, 1),
            margin=self.margin,
        )
        tomorrow_hour_window = build_hour_window(0, tomorrow_end)
        tomorrow_usage_kwh = sum(hourly_usage[hour] for hour in tomorrow_hour_window)
        tomorrow_forecasts = ForecastData(
            start_hour=0,
            end_hour=tomorrow_end,
            hours=max(len(tomorrow_hour_window), 1),
            hourly_usage=hourly_usage,
            usage_kwh=tomorrow_usage_kwh,
            heat_pump_kwh=tomorrow_hp_kwh,
            heat_pump_hourly=tomorrow_hp_hourly,
            pv_forecast_kwh=tomorrow_pv_kwh,
            pv_forecast_hourly=tomorrow_pv_hourly,
            losses_hourly=tomorrow_losses_hourly,
            losses_kwh=tomorrow_losses_kwh,
            margin=self.margin,
        )
        tomorrow_sufficiency = compute_sufficiency(
            tomorrow_forecasts,
            calculator=calculate_sufficiency_window,
        )

        today_start = (self._now_hour + 1) % 24
        today_end = 24
        today_window = build_hour_window(today_start, today_end)
        today_hours = max(len(today_window), 1)

        today_usage_kwh = sum(hourly_usage[hour] for hour in today_window)
        today_hp_kwh, today_hp_hourly = await get_heat_pump_forecast_window(
            self.hass,
            self.config,
            start_hour=today_start,
            end_hour=today_end,
        )
        today_pv_kwh, today_pv_hourly = get_pv_forecast_window(
            self.hass,
            self.config,
            start_hour=today_start,
            end_hour=today_end,
            apply_efficiency=True,
            compensate=True,
            entry_id=self.entry.entry_id,
        )
        _, today_losses_kwh = calculate_losses(
            self.hass,
            self.config,
            hours=today_hours,
            margin=self.margin,
        )

        if _LOGGER.isEnabledFor(logging.DEBUG):
            today_usage_hourly = {
                hour: round(hourly_usage[hour], 3)
                for hour in today_window
            }
            tomorrow_usage_hourly = {
                hour: round(hourly_usage[hour], 3)
                for hour in tomorrow_hour_window
            }
            tomorrow_heat_pump_hourly = {
                hour: round(tomorrow_hp_hourly.get(hour, 0.0), 3)
                for hour in tomorrow_hour_window
            }
            tomorrow_pv_hourly_map = {
                hour: round(tomorrow_pv_hourly.get(hour, 0.0), 3)
                for hour in tomorrow_hour_window
            }
            today_heat_pump_hourly = {
                hour: round(today_hp_hourly.get(hour, 0.0), 3)
                for hour in today_window
            }
            today_pv_hourly_map = {
                hour: round(today_pv_hourly.get(hour, 0.0), 3)
                for hour in today_window
            }
            _LOGGER.debug(
                "Evening surplus input windows | today=%02d:00-%02d:00 (hours=%d) tomorrow=00:00-%02d:00 (hours=%d) | margin=%.3f",
                today_start,
                today_end,
                today_hours,
                tomorrow_end,
                max(len(tomorrow_hour_window), 1),
                self.margin,
            )
            _LOGGER.debug(
                "Evening surplus totals today | usage_kwh=%.3f heat_pump_kwh=%.3f pv_kwh=%.3f losses_kwh=%.3f losses_hourly_kwh=%.3f",
                today_usage_kwh,
                today_hp_kwh,
                today_pv_kwh,
                today_losses_kwh,
                today_losses_kwh / today_hours if today_hours > 0 else 0.0,
            )
            _LOGGER.debug(
                "Evening surplus totals tomorrow | usage_kwh=%.3f heat_pump_kwh=%.3f pv_kwh=%.3f losses_kwh=%.3f losses_hourly_kwh=%.3f",
                tomorrow_usage_kwh,
                tomorrow_hp_kwh,
                tomorrow_pv_kwh,
                tomorrow_losses_kwh,
                tomorrow_losses_hourly,
            )
            _LOGGER.debug("Evening surplus usage hourly today: %s", today_usage_hourly)
            _LOGGER.debug("Evening surplus usage hourly tomorrow: %s", tomorrow_usage_hourly)
            _LOGGER.debug("Evening surplus heat pump hourly today: %s", today_heat_pump_hourly)
            _LOGGER.debug("Evening surplus heat pump hourly tomorrow: %s", tomorrow_heat_pump_hourly)
            _LOGGER.debug("Evening surplus PV hourly today: %s", today_pv_hourly_map)
            _LOGGER.debug("Evening surplus PV hourly tomorrow: %s", tomorrow_pv_hourly_map)

        today_required_kwh = (today_usage_kwh + today_hp_kwh + today_losses_kwh) * self.margin
        if tomorrow_sufficiency.sufficiency_reached:
            tomorrow_required_kwh = tomorrow_sufficiency.required_sufficiency_kwh
            tomorrow_pv_kwh = tomorrow_sufficiency.pv_sufficiency_kwh
        else:
            tomorrow_required_kwh = tomorrow_sufficiency.required_kwh
            tomorrow_pv_kwh = tomorrow_pv_kwh

        required_kwh = today_required_kwh + tomorrow_required_kwh
        pv_forecast_kwh = today_pv_kwh + tomorrow_pv_kwh
        _LOGGER.debug(
            "Evening surplus step 1 | today_required=(usage %.3f + hp %.3f + losses %.3f) * margin %.3f = %.3f kWh | "
            "tomorrow_required=%.3f kWh | required_total=%.3f kWh | pv_total=%.3f kWh",
            today_usage_kwh,
            today_hp_kwh,
            today_losses_kwh,
            self.margin,
            today_required_kwh,
            tomorrow_required_kwh,
            required_kwh,
            pv_forecast_kwh,
        )
        _LOGGER.debug(
            "Evening surplus sufficiency | required_sufficiency_kwh=%.3f pv_sufficiency_kwh=%.3f sufficiency_hour=%s sufficiency_reached=%s",
            tomorrow_sufficiency.required_sufficiency_kwh,
            tomorrow_sufficiency.pv_sufficiency_kwh,
            tomorrow_sufficiency.sufficiency_hour,
            tomorrow_sufficiency.sufficiency_reached,
        )

        tomorrow_net_kwh = max(0.0, tomorrow_required_kwh - tomorrow_pv_kwh)
        today_net_kwh = max(0.0, today_required_kwh - today_pv_kwh)
        total_needed_kwh = today_net_kwh + tomorrow_net_kwh
        surplus_kwh = max(0.0, reserve_kwh - total_needed_kwh)
        _LOGGER.debug(
            "Evening surplus step 2 | today_net=max(0, %.3f-%.3f)=%.3f kWh | "
            "tomorrow_net=max(0, %.3f-%.3f)=%.3f kWh | total_needed=%.3f kWh | reserve=%.3f kWh | surplus=max(0, reserve-total_needed)=%.3f kWh",
            today_required_kwh,
            today_pv_kwh,
            today_net_kwh,
            tomorrow_required_kwh,
            tomorrow_pv_kwh,
            tomorrow_net_kwh,
            total_needed_kwh,
            reserve_kwh,
            surplus_kwh,
        )

        if surplus_kwh <= 0.0:
            return build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No surplus sell action",
                reason="No surplus energy available for surplus sell",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                sufficiency_hour=tomorrow_sufficiency.sufficiency_hour,
                sufficiency_reached=tomorrow_sufficiency.sufficiency_reached,
                key_metrics_extra={
                    "evening_price": f"{self.price:.1f} PLN/MWh",
                    "threshold_price": f"{self.threshold_price:.1f} PLN/MWh",
                    "surplus": f"{surplus_kwh:.1f} kWh",
                    "total_needed": f"{total_needed_kwh:.1f} kWh",
                },
                full_details_extra={
                    "evening_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                    "surplus_kwh": round(surplus_kwh, 2),
                    "total_needed_kwh": round(total_needed_kwh, 2),
                },
            )

        def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
            return build_surplus_sell_outcome(
                target_soc=target_soc,
                current_soc=self.current_soc,
                surplus_kwh=surplus,
                reserve_kwh=reserve_kwh,
                today_net_kwh=today_net_kwh,
                tomorrow_net_kwh=tomorrow_net_kwh,
                total_needed_kwh=total_needed_kwh,
                pv_today_kwh=today_pv_kwh,
                pv_tomorrow_kwh=tomorrow_pv_kwh,
                heat_pump_today_kwh=today_hp_kwh,
                heat_pump_tomorrow_kwh=tomorrow_hp_kwh,
                sufficiency_hour=tomorrow_sufficiency.sufficiency_hour,
                sufficiency_reached=tomorrow_sufficiency.sufficiency_reached,
                export_power_w=export_w,
                evening_price=self.price,
                threshold_price=self.threshold_price,
            )

        def _make_no_action(current_surplus_kwh: float) -> DecisionOutcome:
            return build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No surplus sell action",
                reason="Calculated target SOC does not require discharge",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                sufficiency_hour=tomorrow_sufficiency.sufficiency_hour,
                sufficiency_reached=tomorrow_sufficiency.sufficiency_reached,
                key_metrics_extra={
                    "evening_price": f"{self.price:.1f} PLN/MWh",
                    "threshold_price": f"{self.threshold_price:.1f} PLN/MWh",
                    "surplus": f"{current_surplus_kwh:.1f} kWh",
                    "total_needed": f"{total_needed_kwh:.1f} kWh",
                },
                full_details_extra={
                    "evening_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                    "surplus_kwh": round(current_surplus_kwh, 2),
                    "total_needed_kwh": round(total_needed_kwh, 2),
                },
            )

        return SellRequest(
            surplus_kwh=surplus_kwh,
            build_outcome_fn=_make_outcome,
            build_no_action_fn=_make_no_action,
        )


async def async_run_evening_sell(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
) -> None:
    """Run evening peak sell routine."""
    strategy = EveningSellStrategy(hass, entry_id=entry_id, margin=margin)
    await strategy.run()
