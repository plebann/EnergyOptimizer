"""Decision-audit support for machine-readable diagnostic logs."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from importlib.resources import files
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_ACTIVE_AUDIT: ContextVar[DecisionAudit | None] = ContextVar(
    "energy_optimizer_active_decision_audit",
    default=None,
)

_DUMP_PREFIX = "ENERGY_OPTIMIZER_DECISION_DUMP v1 "
_MANIFEST_VERSION = json.loads(
    files("custom_components.energy_optimizer").joinpath("manifest.json").read_text(
        encoding="utf-8"
    )
)["version"]


def _json_value(value: Any) -> Any:
    """Convert supported diagnostic values to JSON-compatible values."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


@dataclass(slots=True)
class DecisionAudit:
    """Collect inputs, evaluated rules, and commands for one completed decision."""

    hass: HomeAssistant
    entry: ConfigEntry
    trigger: str
    integration_version: str = "unknown"
    timestamp: datetime = field(default_factory=dt_util.now)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)

    def record_input(
        self,
        key: str,
        *,
        source: str | None,
        value: Any,
        status: str = "ok",
    ) -> None:
        """Record a value actually read by the decision logic."""
        self.inputs.append(
            {
                "key": key,
                "source": source,
                "value": _json_value(value),
                "status": status,
            }
        )

    def record_step(
        self,
        step: str,
        *,
        kind: str,
        inputs: Mapping[str, Any],
        result: Any,
    ) -> None:
        """Record an evaluated calculation or decision gate."""
        self.trace.append(
            {
                "step": step,
                "kind": kind,
                "inputs": _json_value(inputs),
                "result": _json_value(result),
            }
        )

    def record_action(
        self,
        kind: str,
        *,
        entity_id: str | None,
        requested: Any,
        status: str,
    ) -> None:
        """Record the planned action and its execution result."""
        self.actions.append(
            {
                "kind": kind,
                "entity_id": entity_id,
                "requested": _json_value(requested),
                "status": status,
            }
        )

    def as_payload(self, decision: Mapping[str, Any]) -> dict[str, Any]:
        """Build the complete versioned diagnostic payload."""
        local_time = dt_util.as_local(self.timestamp)
        return {
            "schema_version": 1,
            "integration_version": self.integration_version,
            "timestamp": local_time.isoformat(),
            "timezone": str(local_time.tzinfo),
            "trigger": self.trigger,
            "config": {
                "data": _json_value(dict(self.entry.data)),
                "options": _json_value(dict(self.entry.options)),
            },
            "decision": _json_value(decision),
            "inputs": self.inputs,
            "trace": self.trace,
            "actions": self.actions,
        }


def activate_audit(audit: DecisionAudit) -> Token[DecisionAudit | None]:
    """Make an audit available to helpers in the current async task."""
    return _ACTIVE_AUDIT.set(audit)


def deactivate_audit(token: Token[DecisionAudit | None]) -> None:
    """Restore the prior audit context."""
    _ACTIVE_AUDIT.reset(token)


@asynccontextmanager
async def active_decision_audit(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    trigger: str,
):
    """Activate and reliably clear an audit for one public decision run."""
    audit = DecisionAudit(
        hass=hass,
        entry=entry,
        trigger=trigger,
        integration_version=str(_MANIFEST_VERSION),
    )
    token = activate_audit(audit)
    try:
        yield audit
    finally:
        deactivate_audit(token)


def get_active_audit() -> DecisionAudit | None:
    """Return the audit active for the current task."""
    return _ACTIVE_AUDIT.get()


def record_input(
    key: str,
    *,
    source: str | None,
    value: Any,
    status: str = "ok",
) -> None:
    """Record an input when a decision audit is active."""
    if audit := get_active_audit():
        audit.record_input(key, source=source, value=value, status=status)


def record_step(
    step: str,
    *,
    kind: str,
    inputs: Mapping[str, Any],
    result: Any,
) -> None:
    """Record a trace step when a decision audit is active."""
    if audit := get_active_audit():
        audit.record_step(step, kind=kind, inputs=inputs, result=result)


def record_action(
    kind: str,
    *,
    entity_id: str | None,
    requested: Any,
    status: str,
) -> None:
    """Record an action when a decision audit is active."""
    if audit := get_active_audit():
        audit.record_action(
            kind,
            entity_id=entity_id,
            requested=requested,
            status=status,
        )


def emit_decision_dump(
    logger: logging.Logger,
    audit: DecisionAudit,
    decision: Mapping[str, Any],
) -> None:
    """Emit a single-line JSON dump for a completed decision."""
    logger.info(
        "%s%s",
        _DUMP_PREFIX,
        json.dumps(audit.as_payload(decision), separators=(",", ":"), sort_keys=True),
    )
