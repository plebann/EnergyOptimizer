"""Decision-audit support for machine-readable diagnostic logs."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from importlib.resources import files
import inspect
import json
import logging
from pathlib import Path
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_ACTIVE_AUDIT: ContextVar[DecisionAudit | None] = ContextVar(
    "energy_optimizer_active_decision_audit",
    default=None,
)

_CONFIG_SNAPSHOT_PREFIX = "ENERGY_OPTIMIZER_CONFIG_SNAPSHOT v1 "
_REPLAY_PREFIX = "ENERGY_OPTIMIZER_DECISION_REPLAY v1 "
_DUMP_LOGGER = logging.getLogger("custom_components.energy_optimizer.decision_replay")
_LOGGER = logging.getLogger(__name__)
_ENTITY_ID_PATTERN = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
_FIXED_ENTITY_ALIASES = {"sun": "sun.sun"}
_ALGORITHM_REVISIONS: dict[str, str] = {}


def _load_manifest_version() -> str:
    """Load the integration version from the packaged manifest."""
    try:
        content = files("custom_components.energy_optimizer").joinpath(
            "manifest.json"
        ).read_text(encoding="utf-8")
        return str(json.loads(content)["version"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as err:
        _LOGGER.warning("Unable to load Energy Optimizer manifest version: %s", err)
        return "unknown"


_MANIFEST_VERSION = _load_manifest_version()


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


def _entry_snapshot(entry: ConfigEntry) -> dict[str, Any]:
    """Build the stable configuration portion of a replay fixture."""
    settings: dict[str, Any] = {}
    entity_aliases = dict(_FIXED_ENTITY_ALIASES)
    for source in (dict(entry.data), dict(entry.options)):
        for key, value in source.items():
            alias = str(key)
            if isinstance(value, str) and _ENTITY_ID_PATTERN.fullmatch(value):
                entity_aliases[alias] = value
            else:
                settings[alias] = _json_value(value)

    content = {
        "schema_version": 1,
        "settings": settings,
        "entity_aliases": entity_aliases,
    }
    encoded = json.dumps(content, separators=(",", ":"), sort_keys=True)
    return {
        **content,
        "config_snapshot_id": sha256(encoded.encode()).hexdigest()[:16],
    }


def _calling_decision_module() -> str:
    """Return the decision module that owns the active audit."""
    for frame_info in inspect.stack():
        module = inspect.getmodule(frame_info.frame)
        module_name = getattr(module, "__name__", "")
        if (
            module_name.startswith("custom_components.energy_optimizer")
            and ".utils." not in module_name
        ):
            return module_name
    return "unknown"


def _compute_algorithm_revision(module_name: str) -> str:
    """Hash the scenario module and its shared decision dependencies."""
    package_root = Path(__file__).parent.parent
    dependency_paths = [
        package_root / "helpers.py",
        package_root / "controllers" / "inverter.py",
        package_root / "decision_engine" / "common.py",
        package_root / "decision_engine" / "charge_base.py",
        package_root / "decision_engine" / "sell_base.py",
        package_root / "utils" / "forecast.py",
        package_root / "utils" / "heat_pump.py",
        package_root / "utils" / "pv_forecast.py",
        package_root / "utils" / "time_window.py",
    ]
    dependency_paths.extend((package_root / "calculations").glob("*.py"))
    if module_name.startswith("custom_components.energy_optimizer."):
        relative_module = module_name.removeprefix(
            "custom_components.energy_optimizer."
        )
        dependency_paths.append(package_root / f"{relative_module.replace('.', '/')}.py")

    digest = sha256()
    for path in sorted(set(dependency_paths)):
        if not path.is_file():
            continue
        digest.update(path.relative_to(package_root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


async def _get_algorithm_revision(
    hass: HomeAssistant, module_name: str
) -> str:
    """Return the cached revision without blocking the event loop."""
    if revision := _ALGORITHM_REVISIONS.get(module_name):
        return revision
    executor_job = hass.async_add_executor_job(
        _compute_algorithm_revision, module_name
    )
    if inspect.isawaitable(executor_job):
        revision = await executor_job
    else:
        revision = _compute_algorithm_revision(module_name)
    _ALGORITHM_REVISIONS[module_name] = revision
    return revision


@dataclass(slots=True)
class DecisionAudit:
    """Collect replay inputs for one completed decision."""

    hass: HomeAssistant
    entry: ConfigEntry
    trigger: str
    integration_version: str = "unknown"
    algorithm_revision: str = "unknown"
    timestamp: datetime = field(default_factory=dt_util.now)
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)

    def _alias_for(self, source: str | None, key: str) -> str:
        """Return the stable config alias for a dynamic entity input."""
        if source:
            for alias, entity_id in _entry_snapshot(self.entry)["entity_aliases"].items():
                if entity_id == source:
                    return alias
        return key.removeprefix("float_state:").replace(":", "_")

    def record_input(
        self,
        key: str,
        *,
        source: str | None,
        value: Any,
        status: str = "ok",
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Record a value actually read by the decision logic."""
        alias = self._alias_for(source, key)
        input_value = {
            "state": _json_value(value),
            "status": status,
        }
        if attributes:
            input_value["attributes"] = _json_value(attributes)
        self.inputs.setdefault(alias, input_value)

    def record_action(
        self,
        kind: str,
        *,
        entity_id: str | None,
        requested: Any,
        status: str,
    ) -> None:
        """Track actions for wrappers without including service results in replay."""
        self.actions.append(
            {
                "kind": kind,
                "entity_id": entity_id,
                "requested": _json_value(requested),
                "status": status,
            }
        )

    def as_payload(self, decision: Mapping[str, Any]) -> dict[str, Any]:
        """Build the complete replay fixture."""
        local_time = dt_util.as_local(self.timestamp)
        return {
            "schema_version": 1,
            "integration_version": self.integration_version,
            "algorithm_revision": self.algorithm_revision,
            "config_snapshot_id": _entry_snapshot(self.entry)["config_snapshot_id"],
            "timestamp": local_time.isoformat(),
            "timezone": str(local_time.tzinfo),
            "trigger": self.trigger,
            "expected_decision": _json_value(decision),
            "inputs": self.inputs,
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
    module_name = _calling_decision_module()
    audit = DecisionAudit(
        hass=hass,
        entry=entry,
        trigger=trigger,
        integration_version=str(_MANIFEST_VERSION),
        algorithm_revision=await _get_algorithm_revision(hass, module_name),
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
    attributes: Mapping[str, Any] | None = None,
) -> None:
    """Record an input when a decision audit is active."""
    if audit := get_active_audit():
        audit.record_input(
            key,
            source=source,
            value=value,
            status=status,
            attributes=attributes,
        )


def record_step(
    step: str,
    *,
    kind: str,
    inputs: Mapping[str, Any],
    result: Any,
) -> None:
    """Retain the no-op trace API while replay fixtures omit execution traces."""


def record_action(
    kind: str,
    *,
    entity_id: str | None,
    requested: Any,
    status: str,
) -> None:
    """Track actions when an audit is active without exposing them in replay."""
    if audit := get_active_audit():
        audit.record_action(
            kind,
            entity_id=entity_id,
            requested=requested,
            status=status,
        )


def emit_decision_dump(
    _logger: logging.Logger,
    audit: DecisionAudit,
    decision: Mapping[str, Any],
) -> None:
    """Emit a single-line replay fixture through the dedicated logger."""
    _DUMP_LOGGER.info(
        "%s%s",
        _REPLAY_PREFIX,
        json.dumps(audit.as_payload(decision), separators=(",", ":"), sort_keys=True),
    )


def emit_config_snapshot(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Emit a configuration snapshot once for each content revision."""
    snapshot = _entry_snapshot(entry)
    emitted = hass.data.setdefault("energy_optimizer_decision_snapshots", set())
    snapshot_id = snapshot["config_snapshot_id"]
    if snapshot_id in emitted:
        return
    emitted.add(snapshot_id)
    _DUMP_LOGGER.info(
        "%s%s",
        _CONFIG_SNAPSHOT_PREFIX,
        json.dumps(snapshot, separators=(",", ":"), sort_keys=True),
    )
