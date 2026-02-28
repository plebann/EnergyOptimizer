"""Morning grid charge decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..calculations.battery import (
    calculate_battery_reserve,
)
from ..calculations.energy import (
    calculate_needed_reserve,
    calculate_needed_reserve_sufficiency,
)
from ..decision_engine.common import (
    ChargeAction,
    EnergyBalance,
    ForecastData,
    SufficiencyResult,
    build_no_action_outcome,
    build_morning_charge_outcome,
    calculate_target_soc_from_needed_reserve,
    compute_sufficiency,
    get_required_prog2_soc_state,
    handle_no_action_soc_update,
)
from ..helpers import (
    is_balancing_ongoing,
    resolve_tariff_end_hour,
    set_balancing_ongoing,
)
from .charge_base import BaseChargeStrategy
from ..utils.logging import DecisionOutcome, log_decision_unified

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

class MorningChargeStrategy(BaseChargeStrategy):
    """Morning charge strategy using BaseChargeStrategy template flow."""

    @property
    def scenario_name(self) -> str:
        """Scenario display name."""
        return "Morning Grid Charge"

    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        """Resolve morning Program 2 SOC state."""
        return get_required_prog2_soc_state(self.hass, self.config)

    def _resolve_forecast_params(self) -> tuple[int, int, dict[str, object]]:
        """Resolve morning forecast time window and kwargs."""
        return 6, resolve_tariff_end_hour(self.hass, self.config), {}

    async def _check_early_exit(self) -> bool:
        """Stop run when balancing is in progress."""
        if not is_balancing_ongoing(self.hass, self.entry.entry_id):
            return False

        set_balancing_ongoing(self.hass, self.entry.entry_id, ongoing=False)
        outcome = _build_balancing_ongoing_outcome()
        await log_decision_unified(
            self.hass,
            self.entry,
            outcome,
            context=self.integration_context,
            logger=_LOGGER,
        )
        return True

    def _post_forecast_setup(self) -> None:
        """Compute sufficiency after shared forecast gathering."""
        self._sufficiency = compute_sufficiency(self.forecasts)
        if self._sufficiency.required_kwh <= 0.0:
            _LOGGER.info("Required morning energy is zero or negative")
            self._sufficiency = SufficiencyResult(
                required_kwh=0.0,
                required_sufficiency_kwh=self._sufficiency.required_sufficiency_kwh,
                pv_sufficiency_kwh=self._sufficiency.pv_sufficiency_kwh,
                sufficiency_hour=self._sufficiency.sufficiency_hour,
                sufficiency_reached=self._sufficiency.sufficiency_reached,
            )

    def _evaluate_charge(self) -> tuple[float, EnergyBalance]:
        """Evaluate morning gaps and store derived metrics for outcomes."""
        (
            balance,
            self._needed_reserve_sufficiency_kwh,
            self._gap_sufficiency_kwh,
            self._needed_reserve_all_kwh,
            self._base_gap_kwh,
        ) = _calculate_morning_balance(
            self.bc,
            current_soc=self.current_soc,
            forecasts=self.forecasts,
            sufficiency=self._sufficiency,
            pv_compensation_factor=self.pv_compensation_factor,
        )
        return balance.gap_kwh, balance

    def _build_charge_outcome(
        self,
        action: ChargeAction,
        balance: EnergyBalance,
    ) -> DecisionOutcome:
        """Build morning charge outcome payload."""
        return build_morning_charge_outcome(
            scenario=self.scenario_name,
            action=action,
            balance=balance,
            forecasts=self.forecasts,
            sufficiency=self._sufficiency,
            needed_reserve_sufficiency_kwh=self._needed_reserve_sufficiency_kwh,
            gap_sufficiency_kwh=self._gap_sufficiency_kwh,
            current_soc=self.current_soc,
            efficiency=self.bc.efficiency,
            pv_compensation_factor=self.pv_compensation_factor,
        )

    async def _handle_no_action(self, balance: EnergyBalance) -> None:
        """Handle morning no-action path."""
        target_soc = calculate_target_soc_from_needed_reserve(
            needed_reserve_kwh=self._needed_reserve_all_kwh,
            min_soc=self.bc.min_soc,
            max_soc=self.bc.max_soc,
            capacity_ah=self.bc.capacity_ah,
            voltage=self.bc.voltage,
        )
        outcome = build_no_action_outcome(
            scenario=self.scenario_name,
            reason=(
                f"Gap {self._base_gap_kwh:.1f} kWh, reserve {balance.reserve_kwh:.1f} kWh, "
                f"required {balance.required_kwh:.1f} kWh, PV {self.forecasts.pv_forecast_kwh:.1f} kWh, "
                f"gap sufficiency {self._gap_sufficiency_kwh:.1f} kWh"
            ),
            current_soc=self.current_soc,
            reserve_kwh=balance.reserve_kwh,
            required_kwh=balance.required_kwh,
            pv_forecast_kwh=self.forecasts.pv_forecast_kwh,
            sufficiency_hour=self._sufficiency.sufficiency_hour,
            sufficiency_reached=self._sufficiency.sufficiency_reached,
            details_extra={
                "needed_reserve_kwh": round(balance.needed_reserve_kwh, 2),
                "needed_reserve_sufficiency_kwh": round(
                    self._needed_reserve_sufficiency_kwh,
                    2,
                ),
                "required_sufficiency_kwh": round(
                    self._sufficiency.required_sufficiency_kwh,
                    2,
                ),
                "usage_kwh": round(self.forecasts.usage_kwh, 2),
                "pv_sufficiency_kwh": round(self._sufficiency.pv_sufficiency_kwh, 2),
                "pv_compensation_factor": (
                    round(self.pv_compensation_factor, 4)
                    if self.pv_compensation_factor is not None
                    else None
                ),
                "heat_pump_kwh": round(self.forecasts.heat_pump_kwh, 2),
                "losses_kwh": round(self.forecasts.losses_kwh, 2),
                "gap_kwh": round(self._base_gap_kwh, 2),
                "gap_sufficiency_kwh": round(self._gap_sufficiency_kwh, 2),
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

async def async_run_morning_charge(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
) -> None:
    """Run morning grid charge routine."""
    strategy = MorningChargeStrategy(hass, entry_id=entry_id, margin=margin)
    await strategy.run()

def _calculate_morning_balance(
    bc,
    *,
    current_soc: float,
    forecasts: ForecastData,
    sufficiency: SufficiencyResult,
    pv_compensation_factor: float | None,
) -> tuple[EnergyBalance, float, float, float, float]:
    """Calculate morning reserve/gap values."""
    reserve_kwh = calculate_battery_reserve(
        current_soc,
        bc.min_soc,
        bc.capacity_ah,
        bc.voltage,
        efficiency=bc.efficiency,
    )
    needed_reserve_kwh = calculate_needed_reserve(
        sufficiency.required_kwh,
        forecasts.pv_forecast_kwh,
    )
    needed_reserve_sufficiency_kwh = calculate_needed_reserve_sufficiency(
        sufficiency.required_sufficiency_kwh,
        sufficiency.pv_sufficiency_kwh,
    )
    needed_reserve_all_kwh = max(needed_reserve_kwh, needed_reserve_sufficiency_kwh)

    gap_kwh = needed_reserve_kwh - reserve_kwh
    gap_sufficiency_kwh = needed_reserve_sufficiency_kwh - reserve_kwh
    gap_all_kwh = max(gap_kwh, gap_sufficiency_kwh)

    return (
        EnergyBalance(
            reserve_kwh=reserve_kwh,
            required_kwh=sufficiency.required_kwh,
            needed_reserve_kwh=needed_reserve_kwh,
            gap_kwh=gap_all_kwh,
            pv_compensation_factor=pv_compensation_factor,
        ),
        needed_reserve_sufficiency_kwh,
        gap_sufficiency_kwh,
        needed_reserve_all_kwh,
        gap_kwh,
    )

def _build_balancing_ongoing_outcome() -> DecisionOutcome:
    """Build outcome for balancing ongoing skip."""
    summary = "Battery balancing ongoing"
    return DecisionOutcome(
        scenario="Morning Grid Charge",
        action_type="no_action",
        summary=summary,
        reason="Battery balancing in progress",
        details={
            "result": summary,
            "balancing": "ongoing",
            "balancing_ongoing": True,
        },
    )
