"""Evening peak sell decision logic."""
from __future__ import annotations

from dataclasses import replace
import logging
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_battery_reserve
from ..calculations.energy import (
    calculate_losses,
    calculate_sufficiency_window,
    calculate_surplus_energy,
)
from ..calculations.utils import build_hourly_usage_array
from ..calculations.price_windows import find_first_arbitrage_buy_hour
from ..const import (
    ARBITRAGE_BUY_WINDOW_PRICE_MULTIPLIER,
    CONF_BUY_PRICE_SENSOR,
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_EVENING_SECOND_MAX_PRICE_SENSOR,
    CONF_MAX_EXPORT_POWER,
    CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR,
    DEFAULT_MAX_EXPORT_POWER,
    DOMAIN,
)
from ..const import CONF_MIN_ARBITRAGE_PRICE
from ..decision_engine.common import (
    ForecastData,
    build_evening_sell_outcome,
    build_no_action_outcome,
    build_surplus_sell_outcome,
    compute_sufficiency,
    get_required_prog5_soc_state,
    resolve_entry,
)
from ..helpers import (
    get_buy_price_payload,
    get_internal_window_price,
    resolve_evening_max_price_hour,
    resolve_evening_second_max_price_hour,
    resolve_night_buy_window_tomorrow_start_hour,
    resolve_tariff_end_hour,
    resolve_tariff_start_hour,
)
from ..service_handlers.sell_restore import async_handle_sell_restore
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome
from ..utils.decision_dump import active_decision_audit
from ..utils.time_window import build_hour_window
from .sell_base import BaseSellStrategy, SellRequest

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


class EveningSellStrategy(BaseSellStrategy):
    """Evening sell strategy using high-price and surplus branches."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry_id: str | None,
        margin: float | None,
        is_primary: bool = True,
        is_first: bool = True,
    ) -> None:
        """Initialize evening sell strategy."""
        super().__init__(hass, entry_id=entry_id, margin=margin)
        self._is_primary = is_primary
        self._is_first = is_first
        self._has_secondary_window = False
        self._primary_sell_hour = 17
        self._secondary_sell_hour: int | None = None
        self._current_window_hour = 17
        self._other_window_hour: int | None = None
        self._current_window_label = "A"
        self._other_window_label: str | None = None
        self._tomorrow_morning_price: float | None = None
        self._sell_horizon_details: dict[str, object] = {}

    @property
    def scenario_name(self) -> str:
        return "Evening Peak Sell"

    @property
    def sell_type(self) -> str:
        return "evening"

    @property
    def arbitrage_buy_reference_suffix(self) -> str:
        """Return the evening sell Arbitrage Buy Reference sensor suffix."""
        return "night_buy_window_tomorrow"

    @property
    def arbitrage_buy_reference_name(self) -> str:
        """Return the evening sell Arbitrage Buy Reference sensor name."""
        return "Night buy window tomorrow"

    @property
    def clamp_surplus_to_pv(self) -> bool:
        return True

    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        return get_required_prog5_soc_state(self.hass, self.config)

    def _get_price(self) -> float | None:
        self._resolve_window_context()
        if self._has_secondary_window and not self._is_primary:
            return get_internal_window_price(
                self.hass,
                entry_id=self.entry.entry_id,
                unique_id_suffix="evening_sell_window",
                entity_name="Evening second max price sensor",
                attribute_name="second_window_price",
                fallback_entity_id=self.config.get(CONF_EVENING_SECOND_MAX_PRICE_SENSOR),
            )
        return get_internal_window_price(
            self.hass,
            entry_id=self.entry.entry_id,
            unique_id_suffix="evening_sell_window",
            entity_name="Evening max price sensor",
            attribute_name="price",
            fallback_entity_id=self.config.get(CONF_EVENING_MAX_PRICE_SENSOR),
        )

    def _resolve_sell_hour(self) -> int:
        self._resolve_window_context()
        if self._has_secondary_window and self._is_first:
            return max(self._primary_sell_hour, self._secondary_sell_hour or self._primary_sell_hour)
        return self._current_window_hour

    def _resolve_window_context(self) -> None:
        """Resolve current and other evening window metadata."""
        self._primary_sell_hour = resolve_evening_max_price_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=17,
        )
        self._secondary_sell_hour = resolve_evening_second_max_price_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
        )
        self._has_secondary_window = self._secondary_sell_hour is not None

        if self._has_secondary_window and not self._is_primary:
            self._current_window_label = "B"
            self._other_window_label = "A"
            self._current_window_hour = self._secondary_sell_hour or self._primary_sell_hour
            self._other_window_hour = self._primary_sell_hour
        else:
            self._current_window_label = "A"
            self._other_window_label = "B" if self._has_secondary_window else None
            self._current_window_hour = self._primary_sell_hour
            self._other_window_hour = self._secondary_sell_hour

    def _is_second_window(self) -> bool:
        """Return whether the current invocation is the later evening window."""
        return self._has_secondary_window and not self._is_first

    def _hourly_cap_kwh(self) -> float:
        """Return sellable energy for one full hour based on inverter export power."""
        max_export_power = float(
            self.config.get(CONF_MAX_EXPORT_POWER, DEFAULT_MAX_EXPORT_POWER)
            or DEFAULT_MAX_EXPORT_POWER
        )
        return max(max_export_power / 1000.0, 0.0)

    def _is_sell_active(self) -> bool:
        """Return whether an evening sell restore payload currently exists."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        if not isinstance(entry_data, dict):
            return False
        restore = entry_data.get("sell_restore")
        return isinstance(restore, dict) and restore.get("sell_type") == self.sell_type

    async def _stop_active_sell(self, *, reason: str) -> DecisionOutcome:
        """Stop active evening sell immediately via the shared restore path."""
        await async_handle_sell_restore(self.hass, self.entry, self.sell_type)
        details = {
            "window": self._current_window_label,
            "window_hour": self._current_window_hour,
            "evening_price": round(self.price, 2),
        }
        if self._tomorrow_morning_price is not None:
            details["tomorrow_morning_price"] = round(self._tomorrow_morning_price, 2)
        return DecisionOutcome(
            scenario=self.scenario_name,
            action_type="sell_restore",
            summary="Stopped active evening peak sell",
            reason=reason,
            details=details,
        )

    async def _compute_base_evaluation(self) -> DecisionOutcome | SellRequest:
        """Compute sellable energy for the current window before A/B allocation."""
        if getattr(self, "_price_unavailable", False):
            self._sell_horizon_details = {
                "sell_horizon_mode": "normal",
                "sell_horizon_reason": "sell_price_unavailable",
                "arbitrage_hour": None,
            }
            return await self._surplus_sell()

        if not self.config.get(CONF_BUY_PRICE_SENSOR):
            self._sell_horizon_details = {
                "sell_horizon_mode": "static_fallback",
                "sell_horizon_reason": (
                    "static_margin_gate"
                    if self._arbitrage_margin_ok
                    else "static_margin_not_achieved"
                ),
                "arbitrage_hour": None,
            }
            if self._arbitrage_margin_ok:
                return await self._high_price_sell()
            return await self._surplus_sell()

        prices = get_buy_price_payload(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
        )
        if not prices:
            self._sell_horizon_details = {
                "sell_horizon_mode": "normal",
                "sell_horizon_reason": "missing_buy_price_payload",
                "arbitrage_hour": None,
            }
            return await self._surplus_sell(require_sufficiency=True)

        night_buy_start_hour = resolve_night_buy_window_tomorrow_start_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=4,
        )
        buy_window_reference_price = get_internal_window_price(
            self.hass,
            entry_id=self.entry.entry_id,
            unique_id_suffix="night_buy_window_tomorrow",
            entity_name="Tomorrow night buy window sensor",
        )
        buy_window_price_limit = (
            buy_window_reference_price * ARBITRAGE_BUY_WINDOW_PRICE_MULTIPLIER
            if buy_window_reference_price is not None
            else None
        )
        local_now = dt_util.as_local(dt_util.utcnow())
        search_start = datetime.combine(
            local_now.date(),
            time((self._current_window_hour + 1) % 24),
            tzinfo=local_now.tzinfo,
        )
        search_end = datetime.combine(
            local_now.date() + timedelta(days=1),
            time(night_buy_start_hour),
            tzinfo=local_now.tzinfo,
        )
        arbitrage = find_first_arbitrage_buy_hour(
            prices,
            str(self.config[CONF_BUY_PRICE_SENSOR]),
            start_local=search_start,
            end_local=search_end,
            sell_price=self.price,
            min_arbitrage_margin=self.threshold_price,
            max_buy_price=buy_window_price_limit,
        )
        if arbitrage.start_local is not None:
            arbitrage_hour = arbitrage.start_local.hour
            self._sell_horizon_details = {
                "sell_horizon_mode": "arbitrage",
                "sell_horizon_reason": "qualifying_buy_price",
                "arbitrage_reason": arbitrage.reason,
                "arbitrage_hour": arbitrage_hour,
                "arbitrage_datetime": arbitrage.start_local.isoformat(),
                "arbitrage_buy_price": round(arbitrage.average_price, 2),
                "arbitrage_margin": round(arbitrage.arbitrage_margin, 2),
                "buy_window_reference_price": round(buy_window_reference_price, 2),
                "buy_window_price_limit": round(buy_window_price_limit, 2),
                "selected_end_hour": arbitrage_hour,
                "history_end_kind": "arb_b",
            }
            return await self._high_price_sell(
                start_hour=(self._current_window_hour + 1) % 24,
                end_hour=arbitrage_hour,
            )

        self._sell_horizon_details = {
            "sell_horizon_mode": "normal",
            "sell_horizon_reason": "no_qualifying_buy_price",
            "arbitrage_reason": arbitrage.reason,
            "arbitrage_hour": None,
            "buy_window_reference_price": (
                round(buy_window_reference_price, 2)
                if buy_window_reference_price is not None
                else None
            ),
            "buy_window_price_limit": (
                round(buy_window_price_limit, 2)
                if buy_window_price_limit is not None
                else None
            ),
        }
        return await self._surplus_sell(require_sufficiency=True)

    def _apply_sell_horizon_details(self, outcome: DecisionOutcome) -> DecisionOutcome:
        """Attach the selected sell-demand horizon to diagnostics."""
        outcome.details.update(self._sell_horizon_details)
        return outcome

    def _allocate_window_surplus(self, base_surplus_kwh: float) -> float:
        """Allocate the sellable surplus for the current A/B window."""
        if not self._has_secondary_window:
            return base_surplus_kwh

        hourly_cap_kwh = self._hourly_cap_kwh()

        if self._is_primary and self._is_first:
            return min(base_surplus_kwh, hourly_cap_kwh)
        if self._is_primary and not self._is_first:
            return min(base_surplus_kwh, hourly_cap_kwh)
        if not self._is_primary and self._is_first:
            reserved_for_primary_kwh = min(base_surplus_kwh, hourly_cap_kwh)
            return max(0.0, base_surplus_kwh - reserved_for_primary_kwh)
        return base_surplus_kwh

    async def _get_sell_window_consumption_kwh(self) -> float:
        """Return forecast AC consumption during the selected sell hour."""
        sell_hour = self._current_window_hour
        end_hour = (sell_hour + 1) % 24
        hourly_usage = build_hourly_usage_array(
            self.config,
            self.hass.states.get,
            daily_load_fallback=None,
        )
        heat_pump_kwh, _ = await get_heat_pump_forecast_window(
            self.hass,
            self.config,
            start_hour=sell_hour,
            end_hour=end_hour,
        )
        _, losses_kwh = calculate_losses(self.hass, self.config, hours=1)
        return (hourly_usage[sell_hour] + heat_pump_kwh + losses_kwh) * self.margin

    async def _on_price_unavailable(self) -> bool:
        """Fall back to surplus sell when evening price sensor is unavailable."""
        _LOGGER.info(
            "Evening %s price sensor unavailable - falling back to surplus sell",
            self._current_window_label,
        )
        self.price = 0.0
        self._price_unavailable = True
        return True

    async def _check_early_exit(self) -> DecisionOutcome | None:
        self._resolve_window_context()

        if getattr(self, "_price_unavailable", False):
            # Price unknown - skip tomorrow comparison and proceed to surplus sell.
            return None
        if self.config.get(CONF_BUY_PRICE_SENSOR):
            return None
        self._tomorrow_morning_price = get_internal_window_price(
            self.hass,
            entry_id=self.entry.entry_id,
            unique_id_suffix="morning_sell_window_tomorrow",
            entity_name="Tomorrow morning max price sensor",
            attribute_name="price",
            fallback_entity_id=self.config.get(CONF_TOMORROW_MORNING_MAX_PRICE_SENSOR),
        )
        if self._tomorrow_morning_price is None:
            return None
        if self.price > self._tomorrow_morning_price:
            return None

        if self._is_second_window() and self._is_sell_active():
            return await self._stop_active_sell(
                reason="Current evening window price is not higher than tomorrow morning price",
            )

        return build_no_action_outcome(
            scenario=self.scenario_name,
            summary="No evening peak sell action",
            reason="Evening price is not higher than tomorrow morning price",
            current_soc=self.current_soc,
            reserve_kwh=0.0,
            required_kwh=0.0,
            pv_forecast_kwh=0.0,
            details_extra={
                "evening_price": round(self.price, 2),
                "tomorrow_morning_price": round(self._tomorrow_morning_price, 2),
                "window": self._current_window_label,
            },
        )

    async def _evaluate_sell(self) -> DecisionOutcome | SellRequest:
        evaluation = await self._compute_base_evaluation()

        if not self._has_secondary_window:
            if isinstance(evaluation, SellRequest):
                return replace(
                    evaluation,
                    sell_window_consumption_kwh=(
                        await self._get_sell_window_consumption_kwh()
                    ),
                )
            return evaluation

        if isinstance(evaluation, DecisionOutcome):
            if self._is_second_window() and self._is_sell_active():
                return await self._stop_active_sell(
                    reason=evaluation.reason or "No sellable surplus remaining in second evening window",
                )
            return evaluation

        allocated_surplus_kwh = self._allocate_window_surplus(evaluation.surplus_kwh)
        if allocated_surplus_kwh <= 0.0:
            if self._is_second_window() and self._is_sell_active():
                return await self._stop_active_sell(
                    reason="No sellable surplus remaining in second evening window",
                )
            outcome = evaluation.build_no_action_fn(allocated_surplus_kwh)
            outcome.details["window"] = self._current_window_label
            outcome.details["hourly_cap_kwh"] = round(self._hourly_cap_kwh(), 2)
            return outcome

        return SellRequest(
            surplus_kwh=allocated_surplus_kwh,
            required_kwh=evaluation.required_kwh,
            build_outcome_fn=evaluation.build_outcome_fn,
            build_no_action_fn=evaluation.build_no_action_fn,
            skip_restore=False,
            sell_window_consumption_kwh=(
                await self._get_sell_window_consumption_kwh()
            ),
        )

    async def _high_price_sell(
        self,
        *,
        start_hour: int | None = None,
        end_hour: int = 22,
        surplus_offset_kwh: float = 0.0,
        skip_restore: bool = False,
    ) -> DecisionOutcome | SellRequest:
        if start_hour is None:
            start_hour = (self._now_hour + 1) % 24
        self._sell_horizon_details.setdefault("selected_end_hour", end_hour)
        history_end_kind = str(
            self._sell_horizon_details.get("history_end_kind", "sw_e")
        )

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
            apply_efficiency=True,
            compensate=True,
            entry_id=self.entry.entry_id,
        )
        _, losses_kwh = calculate_losses(
            self.hass,
            self.config,
            hours=hours,
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
            self.battery_config.min_soc,
            self.battery_config.capacity_ah,
            self.battery_config.voltage,
            efficiency=self.battery_config.efficiency,
        )
        surplus_kwh = calculate_surplus_energy(
            reserve_kwh,
            required_kwh,
            pv_forecast_kwh,
        )
        if surplus_offset_kwh > 0:
            surplus_kwh = max(0.0, surplus_kwh - surplus_offset_kwh)
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
            outcome = self._apply_sell_horizon_details(self._apply_arbitrage_gate_details(build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No evening peak sell action",
                reason="No surplus energy available for selling",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                details_extra={
                    "evening_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                },
            )))
            return self._apply_history_window(
                outcome,
                start_hour=start_hour,
                end_hour=end_hour,
                end_kind=history_end_kind,
            )

        def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
            outcome = self._apply_sell_horizon_details(self._apply_arbitrage_gate_details(build_evening_sell_outcome(
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
            )))
            return self._apply_history_window(
                outcome,
                start_hour=start_hour,
                end_hour=end_hour,
                end_kind=history_end_kind,
            )

        def _make_no_action(_surplus: float) -> DecisionOutcome:
            outcome = self._apply_sell_horizon_details(self._apply_arbitrage_gate_details(build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No evening peak sell action",
                reason="Calculated target SOC does not require discharge",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                details_extra={
                    "evening_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                },
            )))
            return self._apply_history_window(
                outcome,
                start_hour=start_hour,
                end_hour=end_hour,
                end_kind=history_end_kind,
            )

        return SellRequest(
            surplus_kwh=surplus_kwh,
            required_kwh=required_kwh,
            build_outcome_fn=_make_outcome,
            build_no_action_fn=_make_no_action,
            skip_restore=skip_restore,
        )

    async def _surplus_sell(
        self,
        *,
        require_sufficiency: bool = False,
    ) -> DecisionOutcome | SellRequest:
        hourly_usage = build_hourly_usage_array(
            self.config,
            self.hass.states.get,
            daily_load_fallback=None,
        )
        reserve_kwh = calculate_battery_reserve(
            self.current_soc,
            self.battery_config.min_soc,
            self.battery_config.capacity_ah,
            self.battery_config.voltage,
            efficiency=self.battery_config.efficiency,
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
        self._sell_horizon_details.setdefault(
            "selected_end_hour",
            tomorrow_sufficiency.sufficiency_hour
            if tomorrow_sufficiency.sufficiency_reached
            else None,
        )
        today_start = (self._now_hour + 1) % 24
        history_end_hour = (
            tomorrow_sufficiency.sufficiency_hour
            if tomorrow_sufficiency.sufficiency_reached
            else tomorrow_end
        )
        history_end_kind = (
            "pv_s" if tomorrow_sufficiency.sufficiency_reached else "tariff_e"
        )
        if require_sufficiency and not tomorrow_sufficiency.sufficiency_reached:
            outcome = self._apply_sell_horizon_details(self._apply_arbitrage_gate_details(
                build_no_action_outcome(
                    scenario=self.scenario_name,
                    summary="No evening peak sell action",
                    reason="Next-day PV sufficiency was not reached",
                    current_soc=self.current_soc,
                    reserve_kwh=reserve_kwh,
                    required_kwh=tomorrow_sufficiency.required_kwh,
                    pv_forecast_kwh=tomorrow_pv_kwh,
                    sufficiency_hour=tomorrow_sufficiency.sufficiency_hour,
                    sufficiency_reached=False,
                )
            ))
            return self._apply_history_window(
                outcome,
                start_hour=today_start,
                end_hour=history_end_hour,
                end_kind=history_end_kind,
            )

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
            outcome = self._apply_sell_horizon_details(self._apply_arbitrage_gate_details(build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No surplus sell action",
                reason="No surplus energy available for surplus sell",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                sufficiency_hour=tomorrow_sufficiency.sufficiency_hour,
                sufficiency_reached=tomorrow_sufficiency.sufficiency_reached,
                details_extra={
                    "evening_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                    "surplus_kwh": round(surplus_kwh, 2),
                    "total_needed_kwh": round(total_needed_kwh, 2),
                },
            )))
            return self._apply_history_window(
                outcome,
                start_hour=today_start,
                end_hour=history_end_hour,
                end_kind=history_end_kind,
            )

        def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
            outcome = build_surplus_sell_outcome(
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
            return self._apply_history_window(
                self._apply_sell_horizon_details(self._apply_arbitrage_gate_details(outcome)),
                start_hour=today_start,
                end_hour=history_end_hour,
                end_kind=history_end_kind,
            )

        def _make_no_action(current_surplus_kwh: float) -> DecisionOutcome:
            outcome = self._apply_sell_horizon_details(self._apply_arbitrage_gate_details(build_no_action_outcome(
                scenario=self.scenario_name,
                summary="No surplus sell action",
                reason="Calculated target SOC does not require discharge",
                current_soc=self.current_soc,
                reserve_kwh=reserve_kwh,
                required_kwh=required_kwh,
                pv_forecast_kwh=pv_forecast_kwh,
                sufficiency_hour=tomorrow_sufficiency.sufficiency_hour,
                sufficiency_reached=tomorrow_sufficiency.sufficiency_reached,
                details_extra={
                    "evening_price": round(self.price, 2),
                    "threshold_price": round(self.threshold_price, 2),
                    "surplus_kwh": round(current_surplus_kwh, 2),
                    "total_needed_kwh": round(total_needed_kwh, 2),
                },
            )))
            return self._apply_history_window(
                outcome,
                start_hour=today_start,
                end_hour=history_end_hour,
                end_kind=history_end_kind,
            )

        return SellRequest(
            surplus_kwh=surplus_kwh,
            required_kwh=required_kwh,
            build_outcome_fn=_make_outcome,
            build_no_action_fn=_make_no_action,
        )

async def async_run_evening_sell(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
    is_primary: bool = True,
    is_first: bool = True,
    trigger: str = "manual:evening_sell",
) -> None:
    """Run evening peak sell routine."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    strategy = EveningSellStrategy(
        hass,
        entry_id=entry_id,
        margin=margin,
        is_primary=is_primary,
        is_first=is_first,
    )
    async with active_decision_audit(hass, entry, trigger=trigger):
        await strategy.run()
    resolve_night_buy_window_tomorrow_start_hour,
