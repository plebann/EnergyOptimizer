"""Afternoon grid charge decision logic."""
from __future__ import annotations

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
)
from ..helpers import (
    get_required_float_state,
    resolve_evening_max_price_hour,
    resolve_tariff_start_hour,
)
from ..utils.pv_forecast import get_forecast_adjusted_kwh
from ..utils.logging import DecisionOutcome
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
        return (
            resolve_tariff_start_hour(self.hass, self.config),
            22,
            {"apply_efficiency": False},
        )

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
            sell_start_hour=resolve_evening_max_price_hour(self.hass, self.config),
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
        return build_afternoon_charge_outcome(
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
        await handle_no_action_soc_update(
            self.hass,
            self.entry,
            integration_context=self.integration_context,
            prog_soc_entity=self.prog_soc_entity,
            current_prog_soc=self.prog_soc_value,
            target_soc=target_soc,
            outcome=outcome,
        )


async def async_run_afternoon_charge(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
) -> None:
    """Run afternoon grid charge routine."""
    strategy = AfternoonChargeStrategy(hass, entry_id=entry_id, margin=margin)
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
    sell_price_entity = config.get(CONF_EVENING_MAX_PRICE_SENSOR)
    pv_forecast_today_entity = config.get(CONF_PV_FORECAST_TODAY)
    pv_forecast_remaining_entity = config.get(CONF_PV_FORECAST_REMAINING)
    pv_production_entity = config.get(CONF_PV_PRODUCTION_SENSOR)

    sell_price = get_required_float_state(
        hass,
        sell_price_entity,
        entity_name="Sell window price",
    )
    if sell_price is None:
        details["arbitrage_reason"] = "missing_sell_price"
        return 0.0, details

    details["sell_price"] = round(sell_price, 4)
    details["min_arbitrage_price"] = round(float(min_arbitrage_price or 0.0), 4)
    if sell_price <= float(min_arbitrage_price or 0.0):
        details["arbitrage_reason"] = "sell_price_below_threshold"
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
