"""Afternoon grid charge decision logic."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING

from ..calculations.battery import calculate_battery_reserve
from ..calculations.energy import calculate_needed_reserve
from ..const import (
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_PV_FORECAST_REMAINING,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_PRODUCTION_SENSOR,
)
from ..decision_engine.common import (
    BatteryConfig,
    ChargeAction,
    EnergyBalance,
    ForecastData,
    _compute_arbitrage_from_cap,
    build_afternoon_charge_outcome,
    build_no_action_outcome,
    calculate_target_soc_from_needed_reserve,
    get_entry_data,
    get_required_prog4_soc_state,
    handle_no_action_soc_update,
    resolve_arbitrage_margin_gate,
    resolve_entry,
)
from ..helpers import (
    get_internal_window_price,
    resolve_day_buy_window_end_hour,
    resolve_day_buy_window_duration_hours,
    resolve_day_buy_window_start_hour,
    resolve_evening_max_price_hour,
    resolve_night_buy_window_tomorrow_start_hour,
    resolve_tariff_start_hour,
)
from ..service_handlers.charge_completion import (
    async_schedule_charge_completion,
    resolve_charge_window,
)
from ..utils.decision_dump import active_decision_audit
from ..utils.logging import DecisionOutcome
from ..utils.pv_forecast import get_forecast_adjusted_kwh
from .charge_base import BaseChargeStrategy

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AfternoonChargeStrategy(BaseChargeStrategy):
    """Afternoon charge strategy using BaseChargeStrategy template flow."""

    @property
    def scenario_name(self) -> str:
        """Scenario display name."""
        return "Afternoon Grid Charge"

    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        """Resolve afternoon Program 4 SOC state."""
        return get_required_prog4_soc_state(self.hass, self.config)

    def _resolve_forecast_params(self) -> tuple[int, int, dict[str, object]]:
        """Resolve afternoon forecast time window and kwargs."""
        tariff_start_hour = resolve_tariff_start_hour(self.hass, self.config)
        start_hour = resolve_day_buy_window_end_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=tariff_start_hour,
        )
        tomorrow_night_start = resolve_night_buy_window_tomorrow_start_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=None,
        )
        if tomorrow_night_start is None:
            self._forecast_end_kind = "day_e"
            return start_hour, 24, {"apply_efficiency": False}

        self._forecast_end_kind = "nb_t_s"
        return start_hour, tomorrow_night_start, {"apply_efficiency": False}

    def _resolve_charge_time_hours(self) -> float:
        """Use the resolved day buy window duration for charge-current sizing."""
        return resolve_day_buy_window_duration_hours(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hours=2.0,
        )

    def _resolve_completion_window(self) -> tuple[datetime, datetime]:
        """Resolve the concrete day buy window used by this run."""
        tariff_start_hour = resolve_tariff_start_hour(self.hass, self.config)
        start_hour = resolve_day_buy_window_start_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=(tariff_start_hour - 2) % 24,
        )
        end_hour = resolve_day_buy_window_end_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=tariff_start_hour,
        )
        return resolve_charge_window(
            self.hass,
            self.entry,
            charge_type="afternoon",
            fallback_start_hour=start_hour,
            fallback_end_hour=end_hour,
        )

    async def _schedule_completion(self) -> None:
        """Schedule Program 4 completion at the day buy window end."""
        window_start, window_end = self._resolve_completion_window()
        await async_schedule_charge_completion(
            self.hass,
            self.entry,
            charge_type="afternoon",
            complete_at=window_end,
            window_start=window_start,
            window_end=window_end,
        )

    async def _after_charge_action(
        self,
        action: ChargeAction,
        *,
        program_soc_changed: bool,
    ) -> None:
        """Schedule completion only after an actual Program 4 SOC write."""
        del action
        if program_soc_changed:
            await self._schedule_completion()

    def _history_window_kinds(self) -> tuple[str, str]:
        """Return source codes for the afternoon charge forecast horizon."""
        return "db_e", self._forecast_end_kind

    def _post_forecast_setup(self) -> None:
        """Prepare afternoon required energy, arbitrage and assist sensor."""
        entry_data = get_entry_data(self.hass, self.entry.entry_id)
        self._grid_assist_sensor = (
            entry_data.get("afternoon_grid_assist_sensor")
            if entry_data is not None
            else None
        )

        self._required_kwh = (
            self.forecasts.usage_kwh
            + self.forecasts.heat_pump_kwh
            + self.forecasts.losses_kwh
        ) * self.forecasts.margin

        if self._required_kwh <= 0.0:
            _LOGGER.info(
                "Required afternoon energy is zero or negative, proceeding with arbitrage only"
            )
            self._required_kwh = 0.0

        self._arbitrage_kwh, self._arbitrage_details = _calculate_arbitrage_kwh(
            self.hass,
            self.config,
            forecasts=self.forecasts,
            bc=self.bc,
            sell_start_hour=resolve_evening_max_price_hour(
                self.hass,
                self.config,
                entry_id=self.entry.entry_id,
            ),
            current_soc=self.current_soc,
            required_kwh=self._required_kwh,
            entry_id=self.entry.entry_id,
        )

    def _set_grid_assist(self, enabled: bool) -> None:
        """Toggle afternoon grid-assist flag sensor when available."""
        if self._grid_assist_sensor is not None:
            self._grid_assist_sensor.set_assist(enabled)

    def _evaluate_charge(self) -> tuple[float, EnergyBalance]:
        """Evaluate afternoon base gap plus optional arbitrage gap."""
        balance = _calculate_afternoon_balance(
            self.bc,
            current_soc=self.current_soc,
            required_kwh=self._required_kwh,
            pv_forecast_kwh=self.forecasts.pv_forecast_kwh,
            pv_compensation_factor=self.pv_compensation_factor,
        )

        base_gap_kwh = max(balance.gap_kwh, 0.0)
        self._total_gap_kwh = base_gap_kwh + self._arbitrage_kwh
        self._set_grid_assist(base_gap_kwh > 0.0)
        return self._total_gap_kwh, balance

    def _build_charge_outcome(
        self,
        action: ChargeAction,
        balance: EnergyBalance,
    ) -> DecisionOutcome:
        """Build afternoon charge outcome payload."""
        outcome = build_afternoon_charge_outcome(
            scenario=self.scenario_name,
            action=action,
            balance=balance,
            forecasts=self.forecasts,
            arbitrage_kwh=self._arbitrage_kwh,
            arbitrage_details=self._arbitrage_details,
            current_soc=self.current_soc,
            efficiency=self.bc.efficiency,
            pv_compensation_factor=self.pv_compensation_factor,
        )
        window_start, window_end = self._resolve_completion_window()
        outcome.details.update(
            {
                "program_soc": action.target_soc,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            }
        )
        return outcome

    async def _handle_no_action(self, balance: EnergyBalance) -> None:
        """Handle afternoon no-action path."""
        target_soc = calculate_target_soc_from_needed_reserve(
            needed_reserve_kwh=balance.needed_reserve_kwh,
            min_soc=self.bc.min_soc,
            max_soc=self.bc.max_soc,
            capacity_ah=self.bc.capacity_ah,
            voltage=self.bc.voltage,
        )

        outcome = build_no_action_outcome(
            scenario=self.scenario_name,
            reason=(
                f"Gap {self._total_gap_kwh:.1f} kWh, reserve {balance.reserve_kwh:.1f} kWh, "
                f"required {balance.required_kwh:.1f} kWh, PV {self.forecasts.pv_forecast_kwh:.1f} kWh"
            ),
            current_soc=self.current_soc,
            reserve_kwh=balance.reserve_kwh,
            required_kwh=balance.required_kwh,
            pv_forecast_kwh=self.forecasts.pv_forecast_kwh,
            details_extra={
                "needed_reserve_kwh": round(balance.needed_reserve_kwh, 2),
                "usage_kwh": round(self.forecasts.usage_kwh, 2),
                "pv_compensation_factor": (
                    round(self.pv_compensation_factor, 4)
                    if self.pv_compensation_factor is not None
                    else None
                ),
                "heat_pump_kwh": round(self.forecasts.heat_pump_kwh, 2),
                "losses_kwh": round(self.forecasts.losses_kwh, 2),
                "gap_kwh": round(self._total_gap_kwh, 2),
                **(self._arbitrage_details or {}),
            },
        )
        outcome.history_windows = self._history_windows()
        window_start, window_end = self._resolve_completion_window()
        outcome.details.update(
            {
                "program_soc": target_soc,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            }
        )
        program_soc_changed = await handle_no_action_soc_update(
            self.hass,
            self.entry,
            integration_context=self.integration_context,
            prog_soc_entity=self.prog_soc_entity,
            current_prog_soc=self.prog_soc_value,
            target_soc=target_soc,
            outcome=outcome,
        )
        if program_soc_changed:
            await self._schedule_completion()


async def async_run_afternoon_charge(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
    trigger: str = "manual:afternoon_charge",
) -> None:
    """Run afternoon grid charge routine."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    strategy = AfternoonChargeStrategy(hass, entry_id=entry_id, margin=margin)
    async with active_decision_audit(hass, entry, trigger=trigger):
        await strategy.run()


def _calculate_afternoon_balance(
    bc: BatteryConfig,
    *,
    current_soc: float,
    required_kwh: float,
    pv_forecast_kwh: float,
    pv_compensation_factor: float | None,
) -> EnergyBalance:
    """Calculate afternoon reserve/gap values."""
    reserve_kwh = calculate_battery_reserve(
        current_soc,
        bc.min_soc,
        bc.capacity_ah,
        bc.voltage,
        efficiency=bc.efficiency,
    )
    needed_reserve_kwh = calculate_needed_reserve(required_kwh, pv_forecast_kwh)
    gap_kwh = needed_reserve_kwh - reserve_kwh
    return EnergyBalance(
        reserve_kwh=reserve_kwh,
        required_kwh=required_kwh,
        needed_reserve_kwh=needed_reserve_kwh,
        gap_kwh=gap_kwh,
        pv_compensation_factor=pv_compensation_factor,
    )


def _calculate_arbitrage_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    forecasts: ForecastData,
    bc: BatteryConfig,
    sell_start_hour: int,
    current_soc: float,
    required_kwh: float,
    entry_id: str | None = None,
) -> tuple[float, dict[str, float | str]]:
    """Calculate optional arbitrage energy and detail metrics."""
    details: dict[str, float | str] = {
        "arbitrage_reason": "not_applicable",
    }

    min_arbitrage_price = float(config.get(CONF_MIN_ARBITRAGE_PRICE, 0.0) or 0.0)
    pv_forecast_today_entity = config.get(CONF_PV_FORECAST_TODAY)
    pv_forecast_remaining_entity = config.get(CONF_PV_FORECAST_REMAINING)
    pv_production_entity = config.get(CONF_PV_PRODUCTION_SENSOR)

    if not entry_id:
        details["arbitrage_reason"] = "missing_entry_id"
        return 0.0, details

    sell_price = get_internal_window_price(
        hass,
        entry_id=entry_id,
        unique_id_suffix="evening_sell_window",
        entity_name="Sell window price",
        attribute_name="price",
        fallback_entity_id=config.get(CONF_EVENING_MAX_PRICE_SENSOR),
    )
    if sell_price is None:
        details["arbitrage_reason"] = "missing_sell_price"
        return 0.0, details

    margin_ok, margin_details = resolve_arbitrage_margin_gate(
        hass,
        entry_id=entry_id,
        sell_price=sell_price,
        min_arbitrage_price=min_arbitrage_price,
        buy_reference_unique_id_suffix="day_buy_window",
        buy_reference_entity_name="Day buy window",
    )
    details.update(margin_details)
    if not margin_ok:
        return 0.0, details

    cap_kwh, cap_reason = get_forecast_adjusted_kwh(
        hass,
        config,
        pv_forecast_today_entity=pv_forecast_today_entity,
        pv_forecast_remaining_entity=pv_forecast_remaining_entity,
        pv_production_entity=pv_production_entity,
        entry_id=entry_id,
    )
    if cap_kwh is None:
        details["arbitrage_reason"] = cap_reason or "invalid_forecast_adjustment"
        return 0.0, details

    arbitrage_kwh, metrics = _compute_arbitrage_from_cap(
        bc=bc,
        forecasts=forecasts,
        sell_start_hour=sell_start_hour,
        current_soc=current_soc,
        required_kwh=required_kwh,
        cap_kwh=cap_kwh,
    )
    details.update({"forecast_adjusted": round(cap_kwh, 2), **metrics})

    if arbitrage_kwh <= 0:
        details["arbitrage_reason"] = "arb_limit_zero"
        return 0.0, details

    details["arbitrage_reason"] = "enabled"
    return arbitrage_kwh, details
