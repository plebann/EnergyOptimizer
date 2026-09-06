"""Afternoon grid charge decision logic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil
import logging
from typing import TYPE_CHECKING, Any, Callable

from ..calculations.battery import calculate_hourly_charge_capacity, soc_to_kwh
from ..calculations.energy import hourly_demand
from ..const import (
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_MIN_ARBITRAGE_PRICE,
    DEFAULT_MAX_CHARGE_CURRENT,
)
from ..decision_engine.common import (
    BatteryConfig,
    ChargeAction,
    EnergyBalance,
    ForecastData,
    get_entry_data,
    get_required_prog4_soc_state,
    resolve_arbitrage_margin_gate,
    resolve_entry,
)
from ..helpers import (
    get_internal_window_price,
    resolve_day_buy_window_end_hour,
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
from ..utils.logging import DecisionOutcome, log_decision_unified
from ..utils.time_window import build_hour_window
from .charge_base import BaseChargeStrategy

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_EPSILON_KWH = 0.001
_SEARCH_ITERATIONS = 48


@dataclass(frozen=True, slots=True)
class _SimulationResult:
    """Physical hourly SOC simulation result."""

    forecast_consumption_kwh: float
    forecast_pv_surplus_kwh: float
    projected_load_grid_import_kwh: float
    projected_end_soc: float
    physical_free_space_end_kwh: float
    protection_grid_charge_kwh: float
    arbitrage_grid_charge_kwh: float
    pv_stored_kwh: float
    grid_charge_stored_kwh: float
    forecast_export_kwh: float
    virtual_sale_kwh: float
    unserved_virtual_sale_kwh: float
    charge_window_peak_soc: float
    pv_stored_by_hour: list[float]
    hourly_trace: list[dict[str, float | int]]


@dataclass(frozen=True, slots=True)
class _AfternoonPlan:
    """Final afternoon protection and arbitrage plan."""

    protection_grid_charge_kwh: float
    arbitrage_grid_charge_kwh: float
    uncovered_reserve_deficit_kwh: float
    simulation: _SimulationResult
    arbitrage_details: dict[str, float | str]

    @property
    def planned_grid_charge_kwh(self) -> float:
        """Return total planned AC grid input."""
        return self.protection_grid_charge_kwh + self.arbitrage_grid_charge_kwh


class AfternoonChargeStrategy(BaseChargeStrategy):
    """Afternoon charge strategy using an hourly physical SOC simulation."""

    @property
    def scenario_name(self) -> str:
        """Scenario display name."""
        return "Afternoon Grid Charge"

    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        """Resolve afternoon Program 4 SOC state."""
        return get_required_prog4_soc_state(self.hass, self.config)

    def _resolve_forecast_params(self) -> tuple[int, int, dict[str, object]]:
        """Resolve the full day-buy start through the protection horizon."""
        tariff_start_hour = resolve_tariff_start_hour(self.hass, self.config)
        self._day_buy_start_hour = resolve_day_buy_window_start_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            default_hour=(tariff_start_hour - 2) % 24,
        )
        self._day_buy_end_hour = resolve_day_buy_window_end_hour(
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
            return self._day_buy_start_hour, 24, {"apply_efficiency": False}

        self._forecast_end_kind = "nb_t_s"
        return (
            self._day_buy_start_hour,
            tomorrow_night_start,
            {"apply_efficiency": False},
        )

    def _resolve_completion_window(self) -> tuple[datetime, datetime]:
        """Resolve the concrete day buy window used by this run."""
        return resolve_charge_window(
            self.hass,
            self.entry,
            charge_type="afternoon",
            fallback_start_hour=self._day_buy_start_hour,
            fallback_end_hour=self._day_buy_end_hour,
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
        return "db_s", self._forecast_end_kind

    def _post_forecast_setup(self) -> None:
        """Prepare the afternoon physical plan and assist sensor."""
        entry_data = get_entry_data(self.hass, self.entry.entry_id)
        self._grid_assist_sensor = (
            entry_data.get("afternoon_grid_assist_sensor")
            if entry_data is not None
            else None
        )
        self._sell_start_hour = resolve_evening_max_price_hour(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
        )
        self._plan = _build_afternoon_plan(
            self.hass,
            self.config,
            entry_id=self.entry.entry_id,
            forecasts=self.forecasts,
            bc=self.bc,
            current_soc=self.current_soc,
            day_buy_start_hour=self._day_buy_start_hour,
            day_buy_end_hour=self._day_buy_end_hour,
            sell_start_hour=self._sell_start_hour,
        )

    def _set_grid_assist(self, enabled: bool) -> None:
        """Toggle afternoon grid-assist flag sensor when available."""
        if self._grid_assist_sensor is not None:
            self._grid_assist_sensor.set_assist(enabled)

    def _evaluate_charge(self) -> tuple[float, EnergyBalance]:
        """Return the planned grid input and compatibility balance."""
        protection_kwh = self._plan.protection_grid_charge_kwh
        self._set_grid_assist(protection_kwh > _EPSILON_KWH)
        simulation = self._plan.simulation
        balance = EnergyBalance(
            reserve_kwh=max(
                soc_to_kwh(
                    self.current_soc - self.bc.min_soc,
                    self.bc.capacity_ah,
                    self.bc.voltage,
                ),
                0.0,
            ),
            required_kwh=simulation.forecast_consumption_kwh,
            needed_reserve_kwh=protection_kwh,
            gap_kwh=self._plan.planned_grid_charge_kwh,
            pv_compensation_factor=self.pv_compensation_factor,
        )
        return self._plan.planned_grid_charge_kwh, balance

    def _calculate_charge_action(
        self,
        *,
        total_gap: float,
        balance: EnergyBalance,
    ) -> ChargeAction:
        """Use the simulator's exact source-side grid plan."""
        del total_gap, balance
        simulation = self._plan.simulation
        charge_hours = max(
            len(
                build_hour_window(
                    self._day_buy_start_hour,
                    self._day_buy_end_hour,
                )
            ),
            1,
        )
        efficiency = max(self.bc.efficiency / 100.0, 0.0)
        stored_rate_kwh = (
            self._plan.planned_grid_charge_kwh * efficiency / charge_hours
        )
        charge_current = (
            ceil(stored_rate_kwh * 1000.0 / self.bc.voltage)
            if self.bc.voltage > 0 and stored_rate_kwh > _EPSILON_KWH
            else 0
        )
        total_capacity_kwh = soc_to_kwh(
            100.0,
            self.bc.capacity_ah,
            self.bc.voltage,
        )
        grid_soc_delta = (
            simulation.grid_charge_stored_kwh / total_capacity_kwh * 100.0
            if total_capacity_kwh > 0
            else 0.0
        )
        return ChargeAction(
            gap_to_charge_kwh=self._plan.planned_grid_charge_kwh,
            soc_delta=grid_soc_delta,
            target_soc=float(
                min(ceil(simulation.charge_window_peak_soc), self.bc.max_soc)
            ),
            charge_current=float(charge_current),
        )

    def _build_charge_outcome(
        self,
        action: ChargeAction,
        balance: EnergyBalance,
    ) -> DecisionOutcome:
        """Build the afternoon result without legacy aggregate metrics."""
        del balance
        simulation = self._plan.simulation
        summary = (
            f"Battery scheduled to charge to {action.target_soc:.0f}%"
            if self._plan.planned_grid_charge_kwh > _EPSILON_KWH
            else "No afternoon grid charge needed"
        )
        reason = (
            f"Protection {self._plan.protection_grid_charge_kwh:.1f} kWh, "
            f"arbitrage {self._plan.arbitrage_grid_charge_kwh:.1f} kWh, "
            f"projected grid import "
            f"{simulation.projected_load_grid_import_kwh:.1f} kWh"
        )
        window_start, window_end = self._resolve_completion_window()
        details: dict[str, Any] = {
            "result": summary,
            "current_soc": round(self.current_soc, 1),
            "target_soc": round(action.target_soc, 1),
            "program_soc": round(action.target_soc, 1),
            "charge_current_a": round(action.charge_current, 1),
            "forecast_consumption_kwh": round(
                simulation.forecast_consumption_kwh, 2
            ),
            "forecast_pv_surplus_kwh": round(
                simulation.forecast_pv_surplus_kwh, 2
            ),
            "planned_grid_charge_kwh": round(
                self._plan.planned_grid_charge_kwh, 2
            ),
            "projected_load_grid_import_kwh": round(
                simulation.projected_load_grid_import_kwh, 2
            ),
            "projected_end_soc": round(simulation.projected_end_soc, 1),
            "physical_free_space_end_kwh": round(
                simulation.physical_free_space_end_kwh, 2
            ),
            "protection_grid_charge_kwh": round(
                self._plan.protection_grid_charge_kwh, 2
            ),
            "arbitrage_grid_charge_kwh": round(
                self._plan.arbitrage_grid_charge_kwh, 2
            ),
            "pv_stored_kwh": round(simulation.pv_stored_kwh, 2),
            "grid_charge_stored_kwh": round(
                simulation.grid_charge_stored_kwh, 2
            ),
            "forecast_export_kwh": round(simulation.forecast_export_kwh, 2),
            "uncovered_reserve_deficit_kwh": round(
                self._plan.uncovered_reserve_deficit_kwh, 2
            ),
            "window_start_hour": self.forecasts.start_hour,
            "window_end_hour": self.forecasts.end_hour,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            **self._plan.arbitrage_details,
        }
        return DecisionOutcome(
            scenario=self.scenario_name,
            action_type=(
                "charge_scheduled"
                if self._plan.planned_grid_charge_kwh > _EPSILON_KWH
                else "no_action"
            ),
            summary=summary,
            reason=reason,
            details=details,
            diagnostic_details={
                "virtual_arbitrage_sale_kwh": round(
                    simulation.virtual_sale_kwh, 2
                ),
                "hourly_trace": simulation.hourly_trace,
            },
        )

    async def _handle_no_action(self, balance: EnergyBalance) -> None:
        """Apply the zero plan and publish the physical forecast result."""
        action = self._calculate_charge_action(total_gap=0.0, balance=balance)
        entities_changed = await self._apply_charge_action(action)
        if entities_changed is None:
            return
        program_soc_changed = any(
            change["entity_id"] == self.prog_soc_entity
            for change in entities_changed
        )
        if program_soc_changed:
            await self._schedule_completion()

        outcome = self._build_charge_outcome(action, balance)
        outcome.history_windows = self._history_windows()
        outcome.entities_changed = entities_changed
        if entities_changed:
            outcome.action_type = "program_settings_updated"
        await log_decision_unified(
            self.hass,
            self.entry,
            outcome,
            context=self.integration_context,
            logger=_LOGGER,
        )


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


def _simulate_afternoon(
    *,
    forecasts: ForecastData,
    bc: BatteryConfig,
    current_soc: float,
    day_buy_start_hour: int,
    day_buy_end_hour: int,
    sell_start_hour: int,
    protection_rate_kwh: float,
    arbitrage_rate_kwh: float,
    virtual_sale_kwh: float,
) -> _SimulationResult:
    """Simulate hourly physical battery, load, PV and planned grid flows."""
    capacity_kwh = soc_to_kwh(100.0, bc.capacity_ah, bc.voltage)
    min_energy_kwh = capacity_kwh * bc.min_soc / 100.0
    max_energy_kwh = capacity_kwh * bc.max_soc / 100.0
    energy_kwh = min(max(capacity_kwh * current_soc / 100.0, 0.0), capacity_kwh)
    efficiency = bc.efficiency / 100.0
    if capacity_kwh <= 0 or efficiency <= 0:
        efficiency = 0.0

    horizon_hours = build_hour_window(forecasts.start_hour, forecasts.end_hour)
    charge_hours = set(build_hour_window(day_buy_start_hour, day_buy_end_hour))
    sell_applied = False
    consumption_total = 0.0
    pv_surplus_total = 0.0
    load_grid_import_total = 0.0
    protection_grid_total = 0.0
    arbitrage_grid_total = 0.0
    pv_stored_total = 0.0
    grid_stored_total = 0.0
    export_total = 0.0
    virtual_sale_delivered = 0.0
    charge_window_peak_soc = (
        energy_kwh / capacity_kwh * 100.0 if capacity_kwh > 0 else current_soc
    )
    pv_stored_by_hour: list[float] = []
    trace: list[dict[str, float | int]] = []

    for index, hour in enumerate(horizon_hours):
        start_energy_kwh = energy_kwh
        sale_delivered_kwh = 0.0
        if hour == sell_start_hour and not sell_applied and virtual_sale_kwh > 0:
            available_sale_kwh = max(energy_kwh - min_energy_kwh, 0.0) * efficiency
            sale_delivered_kwh = min(virtual_sale_kwh, available_sale_kwh)
            energy_kwh -= sale_delivered_kwh / efficiency
            virtual_sale_delivered += sale_delivered_kwh
            sell_applied = True

        grid_capacity_stored_kwh = 0.0
        protection_source_kwh = 0.0
        protection_stored_kwh = 0.0
        if hour in charge_hours and efficiency > 0:
            current_hour_soc = energy_kwh / capacity_kwh * 100.0
            grid_capacity_stored_kwh = calculate_hourly_charge_capacity(
                current_hour_soc,
                bc.max_soc,
                bc.capacity_ah,
                bc.voltage,
                max_current_a=DEFAULT_MAX_CHARGE_CURRENT,
            )
            protection_requested_stored = protection_rate_kwh * efficiency
            protection_stored_kwh = min(
                protection_requested_stored,
                grid_capacity_stored_kwh,
                max(max_energy_kwh - energy_kwh, 0.0),
            )
            protection_source_kwh = protection_stored_kwh / efficiency
            energy_kwh += protection_stored_kwh
            protection_grid_total += protection_source_kwh
            grid_stored_total += protection_stored_kwh
            grid_capacity_stored_kwh -= protection_stored_kwh
            charge_window_peak_soc = max(
                charge_window_peak_soc,
                energy_kwh / capacity_kwh * 100.0,
            )

        demand_kwh = hourly_demand(
            hour,
            hourly_usage=forecasts.hourly_usage,
            heat_pump_hourly=forecasts.heat_pump_hourly,
            losses_hourly=forecasts.losses_hourly,
            margin=forecasts.margin,
        )
        pv_kwh = max(forecasts.pv_forecast_hourly.get(hour, 0.0), 0.0)
        consumption_total += demand_kwh
        pv_direct_kwh = min(pv_kwh, demand_kwh)
        deficit_kwh = max(demand_kwh - pv_direct_kwh, 0.0)
        pv_surplus_kwh = max(pv_kwh - pv_direct_kwh, 0.0)
        pv_surplus_total += pv_surplus_kwh

        battery_to_load_kwh = 0.0
        load_grid_import_kwh = deficit_kwh
        if deficit_kwh > 0 and efficiency > 0:
            available_load_kwh = max(energy_kwh - min_energy_kwh, 0.0) * efficiency
            battery_to_load_kwh = min(deficit_kwh, available_load_kwh)
            energy_kwh -= battery_to_load_kwh / efficiency
            load_grid_import_kwh -= battery_to_load_kwh
        load_grid_import_total += load_grid_import_kwh

        pv_stored_kwh = 0.0
        pv_input_stored_kwh = 0.0
        if pv_surplus_kwh > 0 and efficiency > 0:
            pv_input_stored_kwh = min(
                pv_surplus_kwh,
                max(max_energy_kwh - energy_kwh, 0.0) / efficiency,
            )
            pv_stored_kwh = pv_input_stored_kwh * efficiency
            energy_kwh += pv_stored_kwh
            pv_stored_total += pv_stored_kwh
        pv_stored_by_hour.append(pv_stored_kwh)
        exported_kwh = pv_surplus_kwh - pv_input_stored_kwh
        export_total += exported_kwh

        arbitrage_source_kwh = 0.0
        arbitrage_stored_kwh = 0.0
        if hour in charge_hours and efficiency > 0:
            arbitrage_requested_stored = arbitrage_rate_kwh * efficiency
            arbitrage_stored_kwh = min(
                arbitrage_requested_stored,
                grid_capacity_stored_kwh,
                max(max_energy_kwh - energy_kwh, 0.0),
            )
            arbitrage_source_kwh = arbitrage_stored_kwh / efficiency
            energy_kwh += arbitrage_stored_kwh
            arbitrage_grid_total += arbitrage_source_kwh
            grid_stored_total += arbitrage_stored_kwh
            charge_window_peak_soc = max(
                charge_window_peak_soc,
                energy_kwh / capacity_kwh * 100.0,
            )

        trace.append(
            {
                "hour": hour,
                "day_offset": int(
                    forecasts.end_hour < forecasts.start_hour
                    and hour < forecasts.start_hour
                ),
                "start_soc": round(start_energy_kwh / capacity_kwh * 100.0, 2),
                "pv_kwh": round(pv_kwh, 3),
                "demand_kwh": round(demand_kwh, 3),
                "protection_grid_charge_kwh": round(protection_source_kwh, 3),
                "arbitrage_grid_charge_kwh": round(arbitrage_source_kwh, 3),
                "battery_to_load_kwh": round(battery_to_load_kwh, 3),
                "load_grid_import_kwh": round(load_grid_import_kwh, 3),
                "pv_stored_kwh": round(pv_stored_kwh, 3),
                "forecast_export_kwh": round(exported_kwh, 3),
                "virtual_sale_kwh": round(sale_delivered_kwh, 3),
                "end_soc": round(energy_kwh / capacity_kwh * 100.0, 2),
            }
        )

    projected_end_soc = (
        energy_kwh / capacity_kwh * 100.0 if capacity_kwh > 0 else current_soc
    )
    return _SimulationResult(
        forecast_consumption_kwh=consumption_total,
        forecast_pv_surplus_kwh=pv_surplus_total,
        projected_load_grid_import_kwh=load_grid_import_total,
        projected_end_soc=projected_end_soc,
        physical_free_space_end_kwh=max(max_energy_kwh - energy_kwh, 0.0),
        protection_grid_charge_kwh=protection_grid_total,
        arbitrage_grid_charge_kwh=arbitrage_grid_total,
        pv_stored_kwh=pv_stored_total,
        grid_charge_stored_kwh=grid_stored_total,
        forecast_export_kwh=export_total,
        virtual_sale_kwh=virtual_sale_delivered,
        unserved_virtual_sale_kwh=max(
            virtual_sale_kwh - virtual_sale_delivered,
            0.0,
        ),
        charge_window_peak_soc=charge_window_peak_soc,
        pv_stored_by_hour=pv_stored_by_hour,
        hourly_trace=trace,
    )


def _requested_grid_was_accepted(
    simulation: _SimulationResult,
    *,
    protection_rate_kwh: float,
    arbitrage_rate_kwh: float,
    charge_hour_count: int,
) -> bool:
    """Return whether every uniformly planned grid kWh was stored."""
    return (
        abs(
            simulation.protection_grid_charge_kwh
            - protection_rate_kwh * charge_hour_count
        )
        <= _EPSILON_KWH
        and abs(
            simulation.arbitrage_grid_charge_kwh
            - arbitrage_rate_kwh * charge_hour_count
        )
        <= _EPSILON_KWH
    )


def _max_uniform_rate(
    *,
    simulate: Callable[[float], _SimulationResult],
    upper_rate_kwh: float,
    accepted: Callable[[_SimulationResult, float], bool],
) -> float:
    """Find the largest uniform hourly rate satisfying a physical predicate."""
    low = 0.0
    high = max(upper_rate_kwh, 0.0)
    for _ in range(_SEARCH_ITERATIONS):
        midpoint = (low + high) / 2.0
        if accepted(simulate(midpoint), midpoint):
            low = midpoint
        else:
            high = midpoint
    return low


def _build_afternoon_plan(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    entry_id: str,
    forecasts: ForecastData,
    bc: BatteryConfig,
    current_soc: float,
    day_buy_start_hour: int,
    day_buy_end_hour: int,
    sell_start_hour: int,
) -> _AfternoonPlan:
    """Plan protection first, then PV capacity, then physical arbitrage."""
    charge_hours = build_hour_window(day_buy_start_hour, day_buy_end_hour)
    charge_hour_count = len(charge_hours)
    efficiency = bc.efficiency / 100.0
    max_source_rate_kwh = (
        DEFAULT_MAX_CHARGE_CURRENT * bc.voltage / 1000.0 / efficiency
        if efficiency > 0
        else 0.0
    )

    def simulate_protection(rate_kwh: float) -> _SimulationResult:
        return _simulate_afternoon(
            forecasts=forecasts,
            bc=bc,
            current_soc=current_soc,
            day_buy_start_hour=day_buy_start_hour,
            day_buy_end_hour=day_buy_end_hour,
            sell_start_hour=sell_start_hour,
            protection_rate_kwh=rate_kwh,
            arbitrage_rate_kwh=0.0,
            virtual_sale_kwh=0.0,
        )

    no_grid_simulation = simulate_protection(0.0)
    capacity_kwh = soc_to_kwh(100.0, bc.capacity_ah, bc.voltage)
    initial_energy_kwh = min(
        max(capacity_kwh * current_soc / 100.0, 0.0),
        capacity_kwh,
    )
    initial_floor_deficit_kwh = max(
        capacity_kwh * bc.min_soc / 100.0 - initial_energy_kwh,
        0.0,
    )

    def protection_is_satisfied(result: _SimulationResult) -> bool:
        """Return whether load demand and an initially breached floor are covered."""
        return (
            result.projected_load_grid_import_kwh <= _EPSILON_KWH
            and result.protection_grid_charge_kwh * efficiency
            >= initial_floor_deficit_kwh - _EPSILON_KWH
        )

    if charge_hour_count == 0 or max_source_rate_kwh <= 0:
        protection_rate_kwh = 0.0
        protection_feasible = protection_is_satisfied(no_grid_simulation)
        protection_simulation = no_grid_simulation
    elif protection_is_satisfied(no_grid_simulation):
        protection_rate_kwh = 0.0
        protection_feasible = True
        protection_simulation = no_grid_simulation
    else:
        max_protection_rate = _max_uniform_rate(
            simulate=simulate_protection,
            upper_rate_kwh=max_source_rate_kwh,
            accepted=lambda result, rate: _requested_grid_was_accepted(
                result,
                protection_rate_kwh=rate,
                arbitrage_rate_kwh=0.0,
                charge_hour_count=charge_hour_count,
            ),
        )
        max_protection_simulation = simulate_protection(max_protection_rate)
        protection_feasible = (
            protection_is_satisfied(max_protection_simulation)
        )
        if protection_feasible:
            low = 0.0
            high = max_protection_rate
            for _ in range(_SEARCH_ITERATIONS):
                midpoint = (low + high) / 2.0
                result = simulate_protection(midpoint)
                if protection_is_satisfied(result):
                    high = midpoint
                else:
                    low = midpoint
            protection_rate_kwh = high
            protection_simulation = simulate_protection(protection_rate_kwh)
        else:
            protection_rate_kwh = max_protection_rate
            protection_simulation = max_protection_simulation

    uncovered_reserve_deficit_kwh = (
        protection_simulation.projected_load_grid_import_kwh
        + max(
            initial_floor_deficit_kwh
            - protection_simulation.protection_grid_charge_kwh * efficiency,
            0.0,
        )
    )
    arbitrage_details: dict[str, float | str] = {
        "arbitrage_reason": "not_applicable"
    }
    arbitrage_rate_kwh = 0.0
    final_simulation = protection_simulation

    if not protection_feasible:
        arbitrage_details["arbitrage_reason"] = "protection_infeasible"
    else:
        sell_price = get_internal_window_price(
            hass,
            entry_id=entry_id,
            unique_id_suffix="evening_sell_window",
            entity_name="Sell window price",
            attribute_name="price",
            fallback_entity_id=config.get(CONF_EVENING_MAX_PRICE_SENSOR),
        )
        if sell_price is None:
            arbitrage_details["arbitrage_reason"] = "missing_sell_price"
        else:
            margin_ok, margin_details = resolve_arbitrage_margin_gate(
                hass,
                entry_id=entry_id,
                sell_price=sell_price,
                min_arbitrage_price=float(
                    config.get(CONF_MIN_ARBITRAGE_PRICE, 0.0) or 0.0
                ),
                buy_reference_unique_id_suffix="day_buy_window",
                buy_reference_entity_name="Day buy window",
            )
            arbitrage_details.update(margin_details)
            horizon_hours = build_hour_window(
                forecasts.start_hour,
                forecasts.end_hour,
            )
            sell_index = (
                horizon_hours.index(sell_start_hour)
                if sell_start_hour in horizon_hours
                else -1
            )
            last_charge_index = charge_hour_count - 1
            if margin_ok and (
                sell_index < 0 or sell_index <= last_charge_index
            ):
                arbitrage_details["arbitrage_reason"] = (
                    "sell_window_outside_horizon"
                )
            elif margin_ok and charge_hour_count == 0:
                arbitrage_details["arbitrage_reason"] = "missing_charge_window"
            elif margin_ok and charge_hour_count > 0:

                def simulate_arbitrage(rate_kwh: float) -> _SimulationResult:
                    virtual_sale_kwh = (
                        rate_kwh * charge_hour_count * efficiency * efficiency
                    )
                    return _simulate_afternoon(
                        forecasts=forecasts,
                        bc=bc,
                        current_soc=current_soc,
                        day_buy_start_hour=day_buy_start_hour,
                        day_buy_end_hour=day_buy_end_hour,
                        sell_start_hour=sell_start_hour,
                        protection_rate_kwh=protection_rate_kwh,
                        arbitrage_rate_kwh=rate_kwh,
                        virtual_sale_kwh=virtual_sale_kwh,
                    )

                def arbitrage_is_feasible(
                    result: _SimulationResult,
                    rate_kwh: float,
                ) -> bool:
                    requested_sale_kwh = (
                        rate_kwh
                        * charge_hour_count
                        * efficiency
                        * efficiency
                    )
                    return (
                        _requested_grid_was_accepted(
                            result,
                            protection_rate_kwh=protection_rate_kwh,
                            arbitrage_rate_kwh=rate_kwh,
                            charge_hour_count=charge_hour_count,
                        )
                        and all(
                            candidate_stored_kwh
                            >= protected_stored_kwh - _EPSILON_KWH
                            for candidate_stored_kwh, protected_stored_kwh in zip(
                                result.pv_stored_by_hour,
                                protection_simulation.pv_stored_by_hour,
                                strict=True,
                            )
                        )
                        and result.projected_load_grid_import_kwh
                        <= protection_simulation.projected_load_grid_import_kwh
                        + _EPSILON_KWH
                        and result.unserved_virtual_sale_kwh <= _EPSILON_KWH
                        and abs(result.virtual_sale_kwh - requested_sale_kwh)
                        <= _EPSILON_KWH
                    )

                arbitrage_rate_kwh = _max_uniform_rate(
                    simulate=simulate_arbitrage,
                    upper_rate_kwh=max_source_rate_kwh,
                    accepted=arbitrage_is_feasible,
                )
                final_simulation = simulate_arbitrage(arbitrage_rate_kwh)
                if (
                    final_simulation.arbitrage_grid_charge_kwh
                    <= _EPSILON_KWH
                ):
                    arbitrage_rate_kwh = 0.0
                    final_simulation = protection_simulation
                    arbitrage_details["arbitrage_reason"] = (
                        "no_physical_capacity"
                    )
                else:
                    arbitrage_details["arbitrage_reason"] = "enabled"

    return _AfternoonPlan(
        protection_grid_charge_kwh=final_simulation.protection_grid_charge_kwh,
        arbitrage_grid_charge_kwh=final_simulation.arbitrage_grid_charge_kwh,
        uncovered_reserve_deficit_kwh=uncovered_reserve_deficit_kwh,
        simulation=final_simulation,
        arbitrage_details=arbitrage_details,
    )
