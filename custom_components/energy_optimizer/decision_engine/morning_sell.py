"""Morning peak sell decision logic."""
from __future__ import annotations

import logging
from datetime import datetime, time
from math import ceil
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_battery_reserve, calculate_battery_space
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
    CONF_BATTERY_VOLTAGE_SENSOR,
    CONF_DISCHARGE_CURRENT_ENTITY,
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_MORNING_MAX_PRICE_SENSOR,
    CONF_MORNING_SELL_PV_COVERAGE_MARGIN,
    CONF_PV_FORECAST_TODAY,
    DOMAIN,
    DEFAULT_MORNING_SELL_PV_COVERAGE_MARGIN,
    SUN_ENTITY,
)
from ..decision_engine.common import (
    ForecastData,
    build_evening_sell_outcome,
    build_no_action_outcome,
    compute_sufficiency,
    get_required_prog3_soc_state,
    resolve_entry,
)
from ..helpers import (
    get_float_state_info,
    get_buy_price_payload,
    get_internal_window_price,
    resolve_day_buy_window_start_hour,
    resolve_morning_max_price_hour,
    resolve_tariff_end_hour,
)
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome
from ..utils.decision_dump import active_decision_audit, record_step
from ..utils.pv_forecast import MorningPVForecast, get_morning_pv_forecast
from ..utils.time_window import build_hour_window
from .sell_base import BaseSellStrategy, SellRegulator, SellRequest

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


def _get_morning_pv_window(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
    apply_efficiency: bool,
    entry_id: str,
) -> tuple[float, dict[int, float], MorningPVForecast | None]:
    """Return validated morning PV when configured, otherwise preserve legacy input."""
    if config.get(CONF_PV_FORECAST_TODAY):
        forecast = get_morning_pv_forecast(
            hass,
            config,
            start_hour=start_hour,
            end_hour=end_hour,
            apply_efficiency=apply_efficiency,
        )
        return forecast.total_kwh, forecast.hourly_kwh, forecast
    total_kwh, hourly_kwh = get_pv_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
        apply_efficiency=apply_efficiency,
        compensate=False,
        entry_id=entry_id,
    )
    return total_kwh, hourly_kwh, None


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
        self._use_discharge_current = False
        self._regulator_diagnostics: dict[str, object] = {}

    @property
    def scenario_name(self) -> str:
        """Scenario display name."""
        return "Morning Peak Sell"

    @property
    def sell_type(self) -> str:
        """Sell type persisted for restore."""
        return "morning"

    @property
    def arbitrage_buy_reference_suffix(self) -> str:
        """Return the morning sell Arbitrage Buy Reference sensor suffix."""
        return "morning_sell_buy_reference"

    @property
    def arbitrage_buy_reference_name(self) -> str:
        """Return the morning sell Arbitrage Buy Reference sensor name."""
        return "Morning sell buy reference"

    def _get_target_soc_floor(self, *, surplus_kwh: float) -> float:
        """Use PV floor only when sufficiency is confirmed for morning sell."""
        if self._allow_min_soc_pv:
            return self.battery_config.min_soc_pv
        return self.battery_config.min_soc

    def _build_missing_soc_outcome(self) -> DecisionOutcome:
        """Report a missing SOC input as a concise skipped morning sell."""
        return DecisionOutcome(
            scenario=self.scenario_name,
            action_type="no_action",
            summary="Morning sell skipped: battery SOC unavailable",
            reason="Battery SOC is missing, unavailable, or invalid",
        )

    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        """Resolve program SOC entity/value for morning sell."""
        return get_required_prog3_soc_state(self.hass, self.config)

    def _get_price(self) -> float | None:
        """Resolve morning max price state."""
        return get_internal_window_price(
            self.hass,
            entry_id=self.entry.entry_id,
            unique_id_suffix="morning_sell_window",
            entity_name="Morning max price sensor",
            attribute_name="price",
            fallback_entity_id=self.config.get(CONF_MORNING_MAX_PRICE_SENSOR),
        )

    def _resolve_sell_hour(self) -> int:
        """Resolve morning sell hour."""
        return resolve_morning_max_price_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=7,
        )

    async def _on_price_unavailable(self) -> bool:
        """Fall back to surplus-over-space sell when morning price sensor is unavailable."""
        _LOGGER.info(
            "Morning max price sensor unavailable - falling back to surplus-over-space sell"
        )
        self.price = 0.0
        self._price_unavailable = True
        return True

    def _resolve_sell_regulator(
        self,
        surplus_kwh: float,
        *,
        duration_hours: float = 1.0,
    ) -> SellRegulator:
        """Select the configured regulator for the evaluated morning sell."""
        if not self._use_discharge_current:
            regulator = super()._resolve_sell_regulator(
                surplus_kwh,
                duration_hours=duration_hours,
            )
            export_power_w = regulator.value
            self._regulator_diagnostics.update(
                {
                    "regulator_kind": regulator.kind,
                    "regulator_value": export_power_w,
                    "regulator_previous_value": regulator.previous_value,
                }
            )
            record_step(
                "morning_sell_regulator",
                kind="calculation",
                inputs=self._regulator_diagnostics,
                result={"kind": regulator.kind, "value": export_power_w},
            )
            return SellRegulator(
                kind=regulator.kind,
                entity_id=regulator.entity_id,
                value=export_power_w,
                previous_value=regulator.previous_value,
            )

        entity_id = self.config.get(CONF_DISCHARGE_CURRENT_ENTITY)
        previous_value: float | None = None
        max_current: float | None = None
        if entity_id:
            state = self.hass.states.get(str(entity_id))
            if state is not None:
                try:
                    previous_value = float(state.state)
                except (TypeError, ValueError):
                    previous_value = None
                try:
                    max_current = float(state.attributes.get("max"))
                except (TypeError, ValueError):
                    max_current = None

        voltage_entity = self.config.get(CONF_BATTERY_VOLTAGE_SENSOR)
        voltage = None
        voltage_source = "configured_nominal"
        if voltage_entity:
            voltage, _, voltage_error = get_float_state_info(
                self.hass, str(voltage_entity)
            )
            if voltage_error is None and voltage is not None and voltage > 0:
                voltage_source = str(voltage_entity)
            else:
                voltage = None
        if voltage is None:
            voltage = self.battery_config.voltage

        calculated_current = ceil((surplus_kwh * 1000.0) / voltage)
        current = (
            min(float(calculated_current), max_current)
            if max_current is not None
            else float(calculated_current)
        )
        self._regulator_diagnostics.update(
            {
                "regulator_kind": "discharge_current",
                "regulator_entity": entity_id,
                "surplus_kwh": surplus_kwh,
                "voltage_v": voltage,
                "voltage_source": voltage_source,
                "calculated_current_a": calculated_current,
                "max_current_a": max_current,
                "requested_current_a": current,
                "previous_current_a": previous_value,
            }
        )
        record_step(
            "morning_sell_regulator",
            kind="calculation",
            inputs=self._regulator_diagnostics,
            result={"kind": "discharge_current", "value": current},
        )
        return SellRegulator(
            kind="discharge_current",
            entity_id=str(entity_id) if entity_id else None,
            value=current,
            previous_value=previous_value,
        )

    async def _evaluate_sell(self) -> DecisionOutcome | SellRequest:
        """Run morning sell logic using a single surplus branch."""
        self._allow_min_soc_pv = False
        start_hour = (self._now_hour + 1) % 24
        tariff_end_hour = resolve_tariff_end_hour(self.hass, self.config, default_hour=13)
        base_end_hour = resolve_day_buy_window_start_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=tariff_end_hour,
        )
        sell_hour = self._resolve_sell_hour()
        sell_window_end_hour = (sell_hour + 1) % 24
        horizon_details: dict[str, object] = {
            "sell_horizon_mode": "base_daily",
            "sell_horizon_reason": "pv_sufficiency_or_day_buy_window",
            "selected_end_hour": base_end_hour,
            "arbitrage_hour": None,
            "buy_window_reference_price": None,
            "buy_window_price_limit": None,
        }

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
        (
            base_pv_forecast_kwh,
            base_pv_forecast_hourly,
            base_pv_forecast,
        ) = _get_morning_pv_window(
            self.hass,
            self.config,
            start_hour=start_hour,
            end_hour=base_end_hour,
            apply_efficiency=True,
            entry_id=self.entry.entry_id,
        )
        if base_pv_forecast is not None:
            horizon_details.update(base_pv_forecast.audit_details())
        base_losses_hourly, _ = calculate_losses(
            self.hass,
            self.config,
            hours=base_hours,
        )

        if (
            base_pv_forecast is None
            or not base_pv_forecast.sufficiency_available
            or sell_hour not in base_pv_forecast_hourly
        ):
            return build_no_action_outcome(
                scenario=self.scenario_name,
                summary="Morning sell skipped: hourly PV forecast unavailable",
                reason="A valid hourly PV forecast is required to select the sell regulator",
                current_soc=self.current_soc,
                reserve_kwh=0.0,
                required_kwh=0.0,
                pv_forecast_kwh=0.0,
                sufficiency_hour=None,
                sufficiency_reached=False,
                details_extra=horizon_details,
            )

        hourly_demand_kwh = (
            hourly_usage[sell_hour]
            + base_heat_pump_hourly.get(sell_hour, 0.0)
            + base_losses_hourly
        ) * self.margin
        hourly_pv_kwh = base_pv_forecast_hourly[sell_hour]
        coverage_margin = float(
            self.config.get(
                CONF_MORNING_SELL_PV_COVERAGE_MARGIN,
                DEFAULT_MORNING_SELL_PV_COVERAGE_MARGIN,
            )
        )
        required_pv_kwh = hourly_demand_kwh * (1.0 + coverage_margin)
        self._use_discharge_current = hourly_pv_kwh >= required_pv_kwh
        if self._use_discharge_current and not self.config.get(
            CONF_DISCHARGE_CURRENT_ENTITY
        ):
            return build_no_action_outcome(
                scenario=self.scenario_name,
                summary="Morning sell skipped: discharge-current control unavailable",
                reason="PV covers demand, but no discharge-current entity is configured",
                current_soc=self.current_soc,
                reserve_kwh=0.0,
                required_kwh=hourly_demand_kwh,
                pv_forecast_kwh=hourly_pv_kwh,
                sufficiency_hour=None,
                sufficiency_reached=False,
                details_extra=horizon_details,
            )
        if self._use_discharge_current:
            discharge_state = self.hass.states.get(
                str(self.config[CONF_DISCHARGE_CURRENT_ENTITY])
            )
            try:
                previous_discharge_current = (
                    float(discharge_state.state) if discharge_state is not None else None
                )
            except (TypeError, ValueError):
                previous_discharge_current = None
            if previous_discharge_current is None:
                return build_no_action_outcome(
                    scenario=self.scenario_name,
                    summary="Morning sell skipped: discharge-current baseline unavailable",
                    reason=(
                        "The existing discharge-current value must be available "
                        "before it can be restored"
                    ),
                    current_soc=self.current_soc,
                    reserve_kwh=0.0,
                    required_kwh=hourly_demand_kwh,
                    pv_forecast_kwh=hourly_pv_kwh,
                    sufficiency_hour=None,
                    sufficiency_reached=False,
                    details_extra=horizon_details,
                )
        self._regulator_diagnostics = {
            "sell_hour": sell_hour,
            "hourly_pv_kwh": round(hourly_pv_kwh, 3),
            "hourly_demand_kwh": round(hourly_demand_kwh, 3),
            "pv_coverage_margin": coverage_margin,
            "required_pv_kwh": round(required_pv_kwh, 3),
            "selected_regulator": (
                "discharge_current" if self._use_discharge_current else "export_power"
            ),
        }
        record_step(
            "morning_sell_regulator_selection",
            kind="gate",
            inputs=self._regulator_diagnostics,
            result=self._use_discharge_current,
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

        def _resolve_sufficiency(
            forecasts: ForecastData,
        ) -> object:
            suff = compute_sufficiency(
                forecasts,
                calculator=calculate_sufficiency_window,
            )
            return suff

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
            morning_pv_forecast=base_pv_forecast,
        )

        sufficiency = _resolve_sufficiency(base_forecasts)
        required_kwh = sufficiency.required_kwh
        pv_forecast_kwh = base_forecasts.pv_forecast_kwh
        required_sufficiency_kwh = sufficiency.required_sufficiency_kwh
        pv_sufficiency_kwh = sufficiency.pv_sufficiency_kwh
        heat_pump_kwh = base_heat_pump_kwh
        losses_kwh = base_forecasts.losses_kwh

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Morning sell sufficiency | reached=%s sufficiency_hour=%s required_sufficiency_kwh=%.3f pv_sufficiency_kwh=%.3f",
                sufficiency.sufficiency_reached,
                sufficiency.sufficiency_hour,
                required_sufficiency_kwh,
                pv_sufficiency_kwh,
            )

        prices = get_buy_price_payload(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
        )
        has_dynamic_buy_prices = bool(self.config.get(CONF_BUY_PRICE_SENSOR))
        arbitrage_hour: int | None = None
        margin_achievable = False
        if has_dynamic_buy_prices and prices:
            buy_window_reference_price = get_internal_window_price(
                self.hass,
                entry_id=self.entry.entry_id,
                unique_id_suffix="day_buy_window",
                entity_name="Day buy window sensor",
            )
            if buy_window_reference_price is None:
                horizon_details["arbitrage_reason"] = "missing_buy_window_reference"
            else:
                buy_window_price_limit = (
                    buy_window_reference_price * ARBITRAGE_BUY_WINDOW_PRICE_MULTIPLIER
                )
                horizon_details["buy_window_reference_price"] = round(
                    buy_window_reference_price,
                    2,
                )
                horizon_details["buy_window_price_limit"] = round(buy_window_price_limit, 2)
                local_now = dt_util.as_local(dt_util.utcnow())
                search_start = datetime.combine(
                    local_now.date(),
                    time(sell_window_end_hour),
                    tzinfo=local_now.tzinfo,
                )
                search_end = datetime.combine(
                    local_now.date(),
                    time(base_end_hour),
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
                horizon_details["arbitrage_reason"] = arbitrage.reason
                if arbitrage.start_local is not None:
                    arbitrage_hour = arbitrage.start_local.hour
                    margin_achievable = True
                    horizon_details["arbitrage_hour"] = arbitrage_hour
                    horizon_details["arbitrage_buy_price"] = round(
                        arbitrage.average_price,
                        2,
                    )
                    horizon_details["arbitrage_margin"] = round(
                        arbitrage.arbitrage_margin,
                        2,
                    )
        elif has_dynamic_buy_prices:
            horizon_details["arbitrage_reason"] = "missing_buy_price_payload"
        else:
            margin_achievable = self._arbitrage_margin_ok
            horizon_details["sell_horizon_reason"] = (
                "static_margin_gate" if margin_achievable else "static_margin_not_achieved"
            )

        selected_end_hour: int | None = None
        if sufficiency.sufficiency_reached:
            selected_end_hour = sufficiency.sufficiency_hour
            horizon_details["sell_horizon_mode"] = "pv_sufficiency"
            horizon_details["sell_horizon_reason"] = "pv_sufficiency_reached"
        if arbitrage_hour is not None and (
            selected_end_hour is None or arbitrage_hour < selected_end_hour
        ):
            selected_end_hour = arbitrage_hour
            horizon_details["sell_horizon_mode"] = "arbitrage"
            horizon_details["sell_horizon_reason"] = "qualifying_buy_price"

        use_sunset_overflow = False
        if selected_end_hour is None:
            if margin_achievable:
                selected_end_hour = base_end_hour
                horizon_details["sell_horizon_mode"] = "day_buy_window"
                horizon_details["sell_horizon_reason"] = "margin_achievable"
            else:
                use_sunset_overflow = True
                horizon_details["sell_horizon_mode"] = "sunset_overflow"
                horizon_details["sell_horizon_reason"] = "no_pv_sufficiency_or_arbitrage"

        end_kind = "sunset"
        if arbitrage_hour is not None and selected_end_hour == arbitrage_hour:
            end_kind = "arb_b"
        elif (
            sufficiency.sufficiency_reached
            and selected_end_hour == sufficiency.sufficiency_hour
        ):
            end_kind = "pv_s"
        elif selected_end_hour == base_end_hour:
            end_kind = "db_s"

        if selected_end_hour is not None and selected_end_hour != base_end_hour:
            selected_window = build_hour_window(start_hour, selected_end_hour)
            selected_hours = max(len(selected_window), 1)
            selected_usage_kwh = sum(hourly_usage[hour] for hour in selected_window)
            heat_pump_kwh, _ = await get_heat_pump_forecast_window(
                self.hass,
                self.config,
                start_hour=start_hour,
                end_hour=selected_end_hour,
            )
            pv_forecast_kwh, _, _ = _get_morning_pv_window(
                self.hass,
                self.config,
                start_hour=start_hour,
                end_hour=selected_end_hour,
                apply_efficiency=True,
                entry_id=self.entry.entry_id,
            )
            selected_losses_hourly, _ = calculate_losses(
                self.hass,
                self.config,
                hours=selected_hours,
            )
            required_kwh = (
                selected_usage_kwh + heat_pump_kwh + selected_losses_hourly * selected_hours
            ) * self.margin
            losses_kwh = selected_losses_hourly * selected_hours

        horizon_details["selected_end_hour"] = selected_end_hour
        outcome_end_hour = selected_end_hour if selected_end_hour is not None else base_end_hour
        self._allow_min_soc_pv = (
            sufficiency.sufficiency_reached
            and selected_end_hour is not None
            and sufficiency.sufficiency_hour <= selected_end_hour
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
            "Morning sell calculation | required_kwh=%.3f (full window) | "
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

        evening_price = get_internal_window_price(
            self.hass,
            entry_id=self.entry.entry_id,
            unique_id_suffix="evening_sell_window",
            entity_name="Evening max price sensor",
            attribute_name="price",
            fallback_entity_id=self.config.get(CONF_EVENING_MAX_PRICE_SENSOR),
        )

        selected_surplus_kwh = surplus_kwh
        surplus_to_sunset: float | None = None
        selection_reason = "selected_demand_horizon"

        price_unavailable = getattr(self, "_price_unavailable", False)
        if use_sunset_overflow:
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
            outcome_end_hour = surplus_end_hour
            horizon_details["selected_end_hour"] = surplus_end_hour
            surplus_window = build_hour_window(start_hour, surplus_end_hour)
            surplus_hours = max(len(surplus_window), 1)
            surplus_usage_kwh = sum(hourly_usage[hour] for hour in surplus_window)
            surplus_heat_pump_kwh, surplus_heat_pump_hourly = await get_heat_pump_forecast_window(
                self.hass,
                self.config,
                start_hour=start_hour,
                end_hour=surplus_end_hour,
            )
            (
                surplus_pv_forecast_kwh,
                surplus_pv_forecast_hourly,
                surplus_pv_forecast,
            ) = _get_morning_pv_window(
                self.hass,
                self.config,
                start_hour=start_hour,
                end_hour=surplus_end_hour,
                apply_efficiency=True,
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
                morning_pv_forecast=surplus_pv_forecast,
            )
            sufficiency_to_sunset = _resolve_sufficiency(forecasts_to_sunset)
            required_to_sunset_kwh = sufficiency_to_sunset.required_kwh
            pv_to_sunset_kwh = forecasts_to_sunset.pv_forecast_kwh
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
            outcome = self._apply_arbitrage_gate_details(
                build_no_action_outcome(
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
                    "base_required_kwh_full": round(required_kwh, 2),
                    "base_pv_forecast_kwh_full": round(pv_forecast_kwh, 2),
                    "required_sufficiency_kwh": round(required_sufficiency_kwh, 2),
                    "pv_sufficiency_kwh": round(pv_sufficiency_kwh, 2),
                    "surplus_to_sunset_kwh": (
                        round(surplus_to_sunset, 2)
                        if surplus_to_sunset is not None
                        else None
                    ),
                    "surplus_selection_reason": selection_reason,
                    "price_unavailable": price_unavailable,
                    "start_hour": start_hour,
                    "end_hour": outcome_end_hour,
                },
                )
            )
            outcome.details.update(horizon_details)
            return self._apply_history_window(
                outcome,
                start_hour=start_hour,
                end_hour=outcome_end_hour,
                end_kind=end_kind,
            )

        def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
            outcome = self._apply_arbitrage_gate_details(build_evening_sell_outcome(
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
                end_hour=outcome_end_hour,
                export_power_w=export_w,
                evening_price=None if price_unavailable else self.price,
                threshold_price=self.threshold_price,
            ))
            outcome.details["sufficiency_hour"] = sufficiency.sufficiency_hour
            outcome.details["sufficiency_reached"] = sufficiency.sufficiency_reached
            outcome.details["evening_price"] = (
                round(evening_price, 2) if evening_price is not None else None
            )
            outcome.details["free_space_kwh"] = round(free_space_kwh, 2)
            outcome.details["surplus_kwh_base"] = round(surplus_kwh, 2)
            outcome.details["selected_surplus_kwh"] = round(surplus, 2)
            outcome.details["base_required_kwh_full"] = round(required_kwh, 2)
            outcome.details["base_pv_forecast_kwh_full"] = round(pv_forecast_kwh, 2)
            outcome.details["required_sufficiency_kwh"] = round(required_sufficiency_kwh, 2)
            outcome.details["pv_sufficiency_kwh"] = round(pv_sufficiency_kwh, 2)
            outcome.details["surplus_to_sunset_kwh"] = (
                round(surplus_to_sunset, 2)
                if surplus_to_sunset is not None
                else None
            )
            outcome.details["surplus_selection_reason"] = selection_reason
            outcome.details["price_unavailable"] = price_unavailable
            outcome.details.update(horizon_details)
            return self._apply_history_window(
                outcome,
                start_hour=start_hour,
                end_hour=outcome_end_hour,
                end_kind=end_kind,
            )

        def _make_no_action(current_surplus_kwh: float) -> DecisionOutcome:
            outcome = self._apply_arbitrage_gate_details(build_no_action_outcome(
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
                    "base_required_kwh_full": round(required_kwh, 2),
                    "base_pv_forecast_kwh_full": round(pv_forecast_kwh, 2),
                    "required_sufficiency_kwh": round(required_sufficiency_kwh, 2),
                    "pv_sufficiency_kwh": round(pv_sufficiency_kwh, 2),
                    "surplus_to_sunset_kwh": (
                        round(surplus_to_sunset, 2)
                        if surplus_to_sunset is not None
                        else None
                    ),
                    "surplus_selection_reason": selection_reason,
                    "price_unavailable": price_unavailable,
                    "start_hour": start_hour,
                    "end_hour": outcome_end_hour,
                },
            ))
            outcome.details.update(horizon_details)
            return self._apply_history_window(
                outcome,
                start_hour=start_hour,
                end_hour=outcome_end_hour,
                end_kind=end_kind,
            )

        return SellRequest(
            surplus_kwh=selected_surplus_kwh,
            required_kwh=required_kwh,
            build_outcome_fn=_make_outcome,
            build_no_action_fn=_make_no_action,
            sell_window_consumption_kwh=hourly_demand_kwh,
        )


async def async_run_morning_sell(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
    trigger: str = "manual:morning_sell",
) -> None:
    """Run morning peak sell routine."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    strategy = MorningSellStrategy(hass, entry_id=entry_id, margin=margin)
    async with active_decision_audit(hass, entry, trigger=trigger):
        await strategy.run()
