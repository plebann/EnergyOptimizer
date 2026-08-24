"""Morning grid charge decision logic."""
from __future__ import annotations

from datetime import datetime, time
import logging
from typing import TYPE_CHECKING

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from ..calculations.battery import (
    calculate_battery_reserve,
)
from ..calculations.energy import (
    calculate_needed_reserve,
    calculate_needed_reserve_sufficiency,
)
from ..const import (
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MORNING_MAX_PRICE_SENSOR,
    CONF_PROG2_TIME_START_ENTITY,
    CONF_PV_FORECAST_REMAINING,
)
from ..controllers.inverter import (
    set_charge_current,
    set_program_soc,
    set_program_start_time,
)
from ..decision_engine.common import (
    BatteryConfig,
    ChargeAction,
    EnergyBalance,
    ForecastData,
    SufficiencyResult,
    _compute_arbitrage_from_cap,
    build_no_action_outcome,
    build_morning_charge_outcome,
    calculate_target_soc_from_needed_reserve,
    compute_sufficiency,
    get_required_prog2_soc_state,
    resolve_arbitrage_margin_gate,
    resolve_entry,
)
from ..helpers import (
    get_internal_window_price,
    is_balancing_ongoing,
    resolve_day_buy_window_start_hour,
    resolve_morning_max_price_hour,
    resolve_night_buy_window_end_hour,
    resolve_night_buy_window_duration_hours,
    resolve_night_buy_window_start_hour,
    resolve_tariff_end_hour,
    set_balancing_ongoing,
)
from ..service_handlers.charge_completion import (
    async_schedule_charge_completion,
    resolve_charge_window,
)
from ..utils.decision_dump import active_decision_audit
from ..utils.logging import DecisionOutcome, log_decision_unified
from ..utils.time_window import build_hour_window
from .charge_base import BaseChargeStrategy

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
        tariff_end_hour = resolve_tariff_end_hour(self.hass, self.config)
        return (
            resolve_night_buy_window_end_hour(
                self.hass,
                self.config,
                entry_id=self.entry.entry_id,
                default_hour=6,
            ),
            resolve_day_buy_window_start_hour(
                self.hass,
                self.config,
                entry_id=self.entry.entry_id,
                default_hour=tariff_end_hour,
            ),
            {"compensate": False, "use_morning_pv_fallback": True},
        )

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
        """Compute sufficiency and morning arbitrage after shared forecast gathering."""
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
        self._arbitrage_kwh, self._arbitrage_details = _calculate_morning_arbitrage_kwh(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            forecasts=self.forecasts,
            bc=self.bc,
            sell_start_hour=resolve_morning_max_price_hour(
                self.hass,
                self.config,
                entry_id=self.entry.entry_id,
            ),
            current_soc=self.current_soc,
            required_kwh=self._sufficiency.required_kwh,
        )

    def _resolve_charge_time_hours(self) -> float:
        """Use the resolved night buy window duration for charge-current sizing."""
        return resolve_night_buy_window_duration_hours(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hours=2.0,
        )

    def _resolve_completion_window(self) -> tuple[datetime, datetime]:
        """Resolve the concrete night buy window used by this run."""
        start_hour = resolve_night_buy_window_start_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=4,
        )
        end_hour = resolve_night_buy_window_end_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=6,
        )
        return resolve_charge_window(
            self.hass,
            self.entry,
            charge_type="morning",
            fallback_start_hour=start_hour,
            fallback_end_hour=end_hour,
        )

    def _current_program_start_time(self, entity_id: str) -> time | None:
        """Read the configured Program 2 start-time control."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        parsed = dt_util.parse_time(str(state.state))
        if parsed is not None:
            return parsed.replace(microsecond=0)
        parsed_dt = dt_util.parse_datetime(str(state.state))
        return parsed_dt.time().replace(microsecond=0) if parsed_dt is not None else None

    async def _write_temporary_program_soc(
        self,
        target_soc: float,
    ) -> list[dict[str, float | str]] | None:
        """Write Program 2 start time then SOC, rolling time back on SOC failure."""
        self._temporary_start_entity: str | None = None
        self._temporary_previous_start: time | None = None
        self._temporary_soc_changed = False
        if abs(target_soc - self.prog_soc_value) <= 0.01:
            return []

        start_entity = self.config.get(CONF_PROG2_TIME_START_ENTITY)
        start_entity_id = str(start_entity) if start_entity else ""
        previous_start = self._current_program_start_time(start_entity_id)
        window_start, _ = self._resolve_completion_window()
        if previous_start is None:
            await self._log_write_failure(
                "Program 2 start-time control unavailable or invalid"
            )
            return None

        try:
            await set_program_start_time(
                self.hass,
                start_entity_id,
                window_start.time(),
                entry=self.entry,
                logger=_LOGGER,
                context=self.integration_context,
            )
        except (HomeAssistantError, ValueError) as err:
            await self._log_write_failure(str(err))
            return None

        try:
            await set_program_soc(
                self.hass,
                self.prog_soc_entity,
                target_soc,
                entry=self.entry,
                logger=_LOGGER,
                context=self.integration_context,
            )
        except HomeAssistantError as err:
            try:
                await set_program_start_time(
                    self.hass,
                    start_entity_id,
                    previous_start,
                    entry=self.entry,
                    logger=_LOGGER,
                    context=self.integration_context,
                )
            except (HomeAssistantError, ValueError) as rollback_err:
                _LOGGER.error(
                    "Morning charge failed to restore Program 2 start time: %s",
                    rollback_err,
                )
            await self._log_write_failure(str(err))
            return None

        self._temporary_start_entity = start_entity_id
        self._temporary_previous_start = previous_start
        self._temporary_soc_changed = True
        return [
            {"entity_id": start_entity_id, "value": window_start.time().isoformat()},
            {"entity_id": self.prog_soc_entity, "value": target_soc},
        ]

    async def _rollback_temporary_program_soc(self) -> None:
        """Restore Program 2 controls after a later Morning Charge write fails."""
        if not self._temporary_soc_changed:
            return

        try:
            await set_program_soc(
                self.hass,
                self.prog_soc_entity,
                self.prog_soc_value,
                entry=self.entry,
                logger=_LOGGER,
                context=self.integration_context,
            )
            if (
                self._temporary_start_entity is not None
                and self._temporary_previous_start is not None
            ):
                await set_program_start_time(
                    self.hass,
                    self._temporary_start_entity,
                    self._temporary_previous_start,
                    entry=self.entry,
                    logger=_LOGGER,
                    context=self.integration_context,
                )
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.error(
                "Morning charge failed to roll back Program 2 controls: %s",
                err,
            )

    async def _log_write_failure(self, reason: str) -> None:
        """Emit an explicit morning charge write failure."""
        window_start, window_end = self._resolve_completion_window()
        outcome = DecisionOutcome(
            scenario=self.scenario_name,
            action_type="charge_failed",
            summary="Morning charge inverter write failed",
            reason=reason,
            details={
                "program_soc": self.prog_soc_value,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
        )
        await log_decision_unified(
            self.hass,
            self.entry,
            outcome,
            context=self.integration_context,
            logger=_LOGGER,
        )

    async def _schedule_completion(self, target_soc: float) -> None:
        """Schedule restoration of a temporary Program 2 target."""
        if abs(target_soc - self.bc.min_soc) <= 0.01:
            return
        window_start, window_end = self._resolve_completion_window()
        await async_schedule_charge_completion(
            self.hass,
            self.entry,
            charge_type="morning",
            complete_at=window_end,
            window_start=window_start,
            window_end=window_end,
        )

    async def _apply_charge_action(
        self,
        action: ChargeAction,
    ) -> list[dict[str, float | str]] | None:
        """Apply transactional Program 2 writes and shared charge current."""
        entities_changed = await self._write_temporary_program_soc(action.target_soc)
        if entities_changed is None:
            return None
        charge_current_entity = self.config.get(CONF_CHARGE_CURRENT_ENTITY)
        if charge_current_entity:
            try:
                await set_charge_current(
                    self.hass,
                    str(charge_current_entity),
                    action.charge_current,
                    entry=self.entry,
                    logger=_LOGGER,
                    context=self.integration_context,
                )
            except HomeAssistantError as err:
                await self._rollback_temporary_program_soc()
                await self._log_write_failure(str(err))
                return None
            entities_changed.append(
                {"entity_id": str(charge_current_entity), "value": action.charge_current}
            )
        return entities_changed

    async def _after_charge_action(
        self,
        action: ChargeAction,
        *,
        program_soc_changed: bool,
    ) -> None:
        """Schedule completion for every temporary morning target."""
        del program_soc_changed
        await self._schedule_completion(action.target_soc)

    def _history_window_kinds(self) -> tuple[str, str]:
        """Return source codes for the morning charge forecast horizon."""
        return "nb_e", "db_s"

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
        self._total_gap_kwh = max(balance.gap_kwh, 0.0) + self._arbitrage_kwh
        return self._total_gap_kwh, balance

    def _build_charge_outcome(
        self,
        action: ChargeAction,
        balance: EnergyBalance,
    ) -> DecisionOutcome:
        """Build morning charge outcome payload."""
        outcome = build_morning_charge_outcome(
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
            arbitrage_kwh=self._arbitrage_kwh,
            arbitrage_details=self._arbitrage_details,
        )
        outcome.details["gap_required_kwh"] = round(self._base_gap_kwh, 2)
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
        """Handle morning no-action path."""
        target_soc = calculate_target_soc_from_needed_reserve(
            needed_reserve_kwh=self._needed_reserve_all_kwh,
            min_soc=self.bc.min_soc,
            max_soc=self.bc.max_soc,
            capacity_ah=self.bc.capacity_ah,
            voltage=self.bc.voltage,
        )
        if target_soc == self.bc.min_soc:
            target_soc -= 4
        
        outcome = build_no_action_outcome(
            scenario=self.scenario_name,
            reason=(
                f"Gap {self._total_gap_kwh:.1f} kWh, reserve {balance.reserve_kwh:.1f} kWh, "
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
                "needed_reserve_all_kwh": round(
                    self._needed_reserve_all_kwh,
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
                "gap_kwh": round(self._total_gap_kwh, 2),
                "gap_required_kwh": round(self._base_gap_kwh, 2),
                "gap_sufficiency_kwh": round(self._gap_sufficiency_kwh, 2),
                "gap_before_clamp_kwh": round(balance.gap_kwh, 2),
                "gap_clamped_kwh": round(max(balance.gap_kwh, 0.0), 2),
                "window_start_hour": self.forecasts.start_hour,
                "window_end_hour": self.forecasts.end_hour,
                "window_end_day_offset": int(
                    self.forecasts.end_hour < self.forecasts.start_hour
                ),
                "window_duration_hours": self.forecasts.hours,
                "window_hours": build_hour_window(
                    self.forecasts.start_hour,
                    self.forecasts.end_hour,
                ),
                **(
                    self.forecasts.morning_pv_forecast.audit_details()
                    if self.forecasts.morning_pv_forecast is not None
                    else {}
                ),
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
        entities_changed = await self._write_temporary_program_soc(target_soc)
        if entities_changed is None:
            return
        if entities_changed:
            outcome.action_type = "program_soc_updated"
            outcome.summary = f"Set Program 2 SOC to {target_soc:.0f}%"
            outcome.entities_changed = entities_changed
        await self._schedule_completion(target_soc)
        await log_decision_unified(
            self.hass,
            self.entry,
            outcome,
            context=self.integration_context,
            logger=_LOGGER,
        )

async def async_run_morning_charge(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
    trigger: str = "manual:morning_charge",
) -> None:
    """Run morning grid charge routine."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    strategy = MorningChargeStrategy(hass, entry_id=entry_id, margin=margin)
    async with active_decision_audit(hass, entry, trigger=trigger):
        await strategy.run()


def _calculate_morning_arbitrage_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    entry_id: str,
    forecasts: ForecastData,
    bc: BatteryConfig,
    sell_start_hour: int,
    current_soc: float,
    required_kwh: float,
) -> tuple[float, dict[str, float | str]]:
    """Resolve morning price + remaining cap, then delegateto _compute_arbitrage_from_cap.

    Cap = remaining_kwh from CONF_PV_FORECAST_REMAINING (raw, no correction).
    get_forecast_adjusted_kwh is intentionally NOT used: at 04:00 production_kwh==0
    causes _calculate_forecast_adjustment to return 'invalid_production'.
    """
    details: dict[str, float | str] = {"arbitrage_reason": "not_applicable"}

    min_arbitrage_price = float(config.get(CONF_MIN_ARBITRAGE_PRICE, 0.0) or 0.0)
    remaining_entity = config.get(CONF_PV_FORECAST_REMAINING)

    sell_price = get_internal_window_price(
        hass,
        entry_id=entry_id,
        unique_id_suffix="morning_sell_window",
        entity_name="Morning sell price",
        attribute_name="price",
        fallback_entity_id=config.get(CONF_MORNING_MAX_PRICE_SENSOR),
    )
    if sell_price is None:
        details["arbitrage_reason"] = "missing_morning_sell_price"
        return 0.0, details

    margin_ok, margin_details = resolve_arbitrage_margin_gate(
        hass,
        entry_id=entry_id,
        sell_price=sell_price,
        min_arbitrage_price=min_arbitrage_price,
        buy_reference_unique_id_suffix="night_buy_window",
        buy_reference_entity_name="Night buy window",
    )
    details.update(margin_details)
    if not margin_ok:
        return 0.0, details

    remaining_state = hass.states.get(remaining_entity) if remaining_entity else None
    if remaining_state is None:
        details["arbitrage_reason"] = "missing_remaining_forecast"
        return 0.0, details
    try:
        cap_kwh = float(remaining_state.state)
    except (ValueError, TypeError):
        details["arbitrage_reason"] = "invalid_remaining_forecast"
        return 0.0, details

    arbitrage_kwh, metrics = _compute_arbitrage_from_cap(
        bc=bc,
        forecasts=forecasts,
        sell_start_hour=sell_start_hour,
        current_soc=current_soc,
        required_kwh=required_kwh,
        cap_kwh=cap_kwh,
    )
    details.update({"remaining_forecast_kwh": round(cap_kwh, 2), **metrics})

    if arbitrage_kwh <= 0:
        details["arbitrage_reason"] = "arb_limit_zero"
        return 0.0, details

    details["arbitrage_reason"] = "enabled"
    return arbitrage_kwh, details


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
        bc.min_soc_pv if sufficiency.sufficiency_reached else bc.min_soc,
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
