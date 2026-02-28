"""Shared base strategy for sell decision engine flows."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..calculations.battery import kwh_to_soc
from ..calculations.energy import calculate_export_power
from ..const import (
    CONF_EXPORT_POWER_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_WORK_MODE_ENTITY,
    DOMAIN,
    STORAGE_KEY_SELL_RESTORE,
    STORAGE_VERSION_SELL_RESTORE,
)
from ..controllers.inverter import set_export_power, set_program_soc, set_work_mode
from ..helpers import get_float_state_info, is_test_sell_mode
from ..utils.logging import DecisionOutcome, log_decision_unified
from .common import (
    BatteryConfig,
    get_battery_config,
    get_required_current_soc_state,
    resolve_entry,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SellRequest:
    """Deferred sell execution request produced by strategy evaluation."""

    surplus_kwh: float
    build_outcome_fn: Callable[[float, float, float], DecisionOutcome]
    build_no_action_fn: Callable[[float], DecisionOutcome]


class BaseSellStrategy(ABC):
    """Template-method base for sell decision strategies."""

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
        self.original_prog_soc: float
        self.restore_hour: int
        self.price: float
        self.threshold_price: float
        self.margin: float
        self.integration_context: Context
        self._now_hour: int

    @property
    @abstractmethod
    def scenario_name(self) -> str:
        """Scenario display name used in outcomes and logs."""

    @property
    @abstractmethod
    def sell_type(self) -> str:
        """Sell type identifier persisted for restore path."""

    @property
    def clamp_surplus_to_pv(self) -> bool:
        """Whether to clamp surplus by today's PV production."""
        return False

    @abstractmethod
    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        """Return configured program SOC entity and current value."""

    @abstractmethod
    def _get_price(self) -> float | None:
        """Return current price metric used by strategy."""

    @abstractmethod
    def _resolve_sell_hour(self) -> int:
        """Return configured sell hour used to compute restore hour."""

    async def _check_early_exit(self) -> DecisionOutcome | None:
        """Optional early-exit hook executed before evaluation."""
        return None

    @abstractmethod
    async def _evaluate_sell(self) -> DecisionOutcome | SellRequest:
        """Evaluate branch logic and return outcome or execution request."""

    async def _log_outcome(self, outcome: DecisionOutcome) -> None:
        """Log outcome in a single unified place."""
        await log_decision_unified(
            self.hass,
            self.entry,
            outcome,
            context=self.integration_context,
            logger=_LOGGER,
        )

    async def run(self) -> None:
        """Execute common sell workflow and delegate decision logic to subclass."""
        self.integration_context = Context()

        entry = resolve_entry(self.hass, self._entry_id)
        if entry is None:
            return
        self.entry = entry
        self.config = entry.data

        current_soc_state = get_required_current_soc_state(self.hass, self.config)
        if current_soc_state is None:
            return
        _, self.current_soc = current_soc_state

        prog_soc_state = self._get_prog_soc_state()
        if prog_soc_state is None:
            return
        self.prog_soc_entity, self.original_prog_soc = prog_soc_state

        sell_hour = self._resolve_sell_hour()
        self.restore_hour = (sell_hour + 1) % 24

        price = self._get_price()
        if price is None:
            return
        self.price = price

        early_outcome = await self._check_early_exit()
        if early_outcome is not None:
            await self._log_outcome(early_outcome)
            return

        self.threshold_price = float(self.config.get(CONF_MIN_ARBITRAGE_PRICE, 0.0) or 0.0)
        self.margin = self._raw_margin if self._raw_margin is not None else 1.1
        self.bc = get_battery_config(self.config)
        self._now_hour = dt_util.as_local(dt_util.utcnow()).hour

        evaluation = await self._evaluate_sell()
        if isinstance(evaluation, SellRequest):
            await self._execute_sell(evaluation)
            return

        await self._log_outcome(evaluation)

    async def _execute_sell(self, request: SellRequest) -> None:
        """Execute shared sell tail: clamp, target, writes and final outcome."""
        surplus_kwh = request.surplus_kwh

        if self.clamp_surplus_to_pv:
            pv_production_entity = self.config.get(CONF_PV_PRODUCTION_SENSOR)
            if pv_production_entity:
                pv_value, _pv_raw, pv_error = get_float_state_info(
                    self.hass,
                    str(pv_production_entity),
                )
                if pv_error is None and pv_value is not None and pv_value >= 0.0:
                    if surplus_kwh > pv_value:
                        _LOGGER.info(
                            "Clamping surplus from %.2f kWh to today's PV production %.2f kWh",
                            surplus_kwh,
                            pv_value,
                        )
                    surplus_kwh = min(surplus_kwh, pv_value)

        target_soc = max(
            self.current_soc - kwh_to_soc(surplus_kwh, self.bc.capacity_ah, self.bc.voltage),
            self.bc.min_soc,
        )
        if target_soc >= self.current_soc:
            outcome = request.build_no_action_fn(surplus_kwh)
            await self._log_outcome(outcome)
            return

        export_power_w = calculate_export_power(surplus_kwh)
        work_mode_entity = self.config.get(CONF_WORK_MODE_ENTITY)
        export_power_entity = self.config.get(CONF_EXPORT_POWER_ENTITY)
        sell_test_mode = is_test_sell_mode(self.hass, self.entry)

        original_work_mode: str | None = None
        if work_mode_entity:
            wm_state = self.hass.states.get(str(work_mode_entity))
            if wm_state is not None:
                original_work_mode = wm_state.state

        if sell_test_mode:
            _LOGGER.info("Test sell mode enabled - skipping %s sell inverter writes", self.sell_type)
        else:
            await set_work_mode(
                self.hass,
                str(work_mode_entity) if work_mode_entity else None,
                "Export First",
                entry=self.entry,
                logger=_LOGGER,
                context=self.integration_context,
            )

            restore_data = {
                "work_mode": original_work_mode,
                "prog_soc_entity": self.prog_soc_entity,
                "prog_soc_value": self.original_prog_soc,
                "restore_hour": self.restore_hour,
                "sell_type": self.sell_type,
                "timestamp": dt_util.utcnow().isoformat(),
            }
            self.hass.data[DOMAIN][self.entry.entry_id]["sell_restore"] = restore_data
            store = Store(
                self.hass,
                STORAGE_VERSION_SELL_RESTORE,
                f"{STORAGE_KEY_SELL_RESTORE}.{self.entry.entry_id}",
            )
            await store.async_save(restore_data)

            await set_program_soc(
                self.hass,
                self.prog_soc_entity,
                target_soc,
                entry=self.entry,
                logger=_LOGGER,
                context=self.integration_context,
            )
            await set_export_power(
                self.hass,
                str(export_power_entity) if export_power_entity else None,
                export_power_w,
                entry=self.entry,
                logger=_LOGGER,
                context=self.integration_context,
            )

        outcome = request.build_outcome_fn(target_soc, surplus_kwh, export_power_w)
        outcome.details["test_sell_mode"] = sell_test_mode

        if not sell_test_mode:
            outcome.entities_changed = [
                {"entity_id": self.prog_soc_entity, "value": target_soc}
            ]
            if work_mode_entity:
                outcome.entities_changed.append(
                    {"entity_id": str(work_mode_entity), "option": "Export First"}
                )
            if export_power_entity:
                outcome.entities_changed.append(
                    {"entity_id": str(export_power_entity), "value": export_power_w}
                )

        await self._log_outcome(outcome)
