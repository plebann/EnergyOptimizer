"""Shared base strategy for charge decision engine flows."""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context

from ..const import CONF_CHARGE_CURRENT_ENTITY
from ..controllers.inverter import set_charge_current, set_program_soc
from ..utils.logging import log_decision_unified
from ..utils.pv_forecast import get_pv_compensation_factor
from .common import (
    BatteryConfig,
    ChargeAction,
    EnergyBalance,
    ForecastData,
    calculate_charge_action,
    gather_forecasts,
    get_battery_config,
    get_required_current_soc_state,
    resolve_entry,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..utils.logging import DecisionOutcome

_LOGGER = logging.getLogger(__name__)


class BaseChargeStrategy(ABC):
    """Template-method base for charge decision strategies."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry_id: str | None,
        margin: float | None,
    ) -> None:
        """Initialize strategy with runtime inputs."""
        self.hass = hass
        self._entry_id = entry_id
        self._raw_margin = margin

        self.entry: ConfigEntry
        self.config: dict[str, Any]
        self.bc: BatteryConfig
        self.current_soc: float
        self.prog_soc_entity: str
        self.prog_soc_value: float
        self.margin: float
        self.integration_context: Context
        self.forecasts: ForecastData
        self.pv_compensation_factor: float | None

    @property
    @abstractmethod
    def scenario_name(self) -> str:
        """Scenario display name used in outcomes and logs."""

    @abstractmethod
    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        """Return configured program SOC entity and current value."""

    @abstractmethod
    def _resolve_forecast_params(self) -> tuple[int, int, dict[str, Any]]:
        """Return start hour, end hour and extra gather_forecasts kwargs."""

    @abstractmethod
    def _evaluate_charge(self) -> tuple[float, EnergyBalance]:
        """Return total gap and energy balance for current strategy."""

    @abstractmethod
    def _build_charge_outcome(
        self,
        action: ChargeAction,
        balance: EnergyBalance,
    ) -> DecisionOutcome:
        """Build charge outcome payload."""

    @abstractmethod
    async def _handle_no_action(self, balance: EnergyBalance) -> None:
        """Handle no-action path, including any SOC updates and logging."""

    async def _check_early_exit(self) -> bool:
        """Optional early-exit hook. Return True to stop processing."""
        return False

    def _post_forecast_setup(self) -> None:
        """Optional post-forecast hook."""

    async def run(self) -> None:
        """Execute common charge workflow and delegate strategy specifics."""
        self.integration_context = Context()

        entry = resolve_entry(self.hass, self._entry_id)
        if entry is None:
            return
        self.entry = entry
        self.config = entry.data

        prog_soc_state = self._get_prog_soc_state()
        if prog_soc_state is None:
            return
        self.prog_soc_entity, self.prog_soc_value = prog_soc_state

        current_soc_state = get_required_current_soc_state(self.hass, self.config)
        if current_soc_state is None:
            return
        _, self.current_soc = current_soc_state

        if await self._check_early_exit():
            return

        self.bc = get_battery_config(self.config)
        self.margin = self._raw_margin if self._raw_margin is not None else 1.1

        start_hour, end_hour, extra_kwargs = self._resolve_forecast_params()
        self.forecasts = await gather_forecasts(
            self.hass,
            self.config,
            start_hour=start_hour,
            end_hour=end_hour,
            margin=self.margin,
            entry_id=self.entry.entry_id,
            **extra_kwargs,
        )

        self.pv_compensation_factor = get_pv_compensation_factor(
            self.hass,
            self.entry.entry_id,
        )
        self._post_forecast_setup()

        total_gap, balance = self._evaluate_charge()
        if total_gap <= 0.0:
            await self._handle_no_action(balance)
            return

        action = calculate_charge_action(
            self.bc,
            gap_kwh=total_gap,
            current_soc=self.current_soc,
        )

        charge_current_entity = self.config.get(CONF_CHARGE_CURRENT_ENTITY)

        await set_program_soc(
            self.hass,
            self.prog_soc_entity,
            action.target_soc,
            entry=self.entry,
            logger=_LOGGER,
            context=self.integration_context,
        )
        await set_charge_current(
            self.hass,
            charge_current_entity,
            action.charge_current,
            entry=self.entry,
            logger=_LOGGER,
            context=self.integration_context,
        )

        outcome = self._build_charge_outcome(action, balance)
        outcome.entities_changed = [
            {"entity_id": self.prog_soc_entity, "value": action.target_soc},
            {"entity_id": charge_current_entity, "value": action.charge_current},
        ]
        await log_decision_unified(
            self.hass,
            self.entry,
            outcome,
            context=self.integration_context,
            logger=_LOGGER,
        )
