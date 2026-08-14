"""Tests for machine-readable decision replay logging."""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

from custom_components.energy_optimizer.utils.decision_dump import (
    DecisionAudit,
    emit_config_snapshot,
    emit_decision_dump,
)


def test_emit_decision_dump_produces_replay_fixture(monkeypatch) -> None:
    """A completed decision emits a compact, standalone replay fixture."""
    entry = MagicMock()
    entry.data = {"battery_soc_sensor": "sensor.battery_soc", "max_soc": 98}
    entry.options = {}
    audit = DecisionAudit(
        hass=MagicMock(),
        entry=entry,
        trigger="scheduler:morning_charge",
        integration_version="0.0.0",
    )
    audit.record_input(
        "battery_soc",
        source="sensor.battery_soc",
        value="42.5",
    )
    logger = MagicMock(spec=logging.Logger)
    monkeypatch.setattr(
        "custom_components.energy_optimizer.utils.decision_dump._DUMP_LOGGER",
        logger,
    )

    emit_decision_dump(
        MagicMock(spec=logging.Logger),
        audit,
        {
            "scenario": "Morning Grid Charge",
            "action_type": "charge_scheduled",
            "summary": "Battery scheduled to charge to 75%",
            "reason": "Deficit",
            "details": {"target_soc": 75},
        },
    )

    message = logger.info.call_args.args[0] % logger.info.call_args.args[1:]
    prefix = "ENERGY_OPTIMIZER_DECISION_REPLAY v1 "
    assert message.startswith(prefix)
    assert "\n" not in message
    payload = json.loads(message.removeprefix(prefix))
    assert payload["schema_version"] == 1
    assert payload["integration_version"] == "0.0.0"
    assert payload["algorithm_revision"]
    assert payload["config_snapshot_id"]
    assert payload["trigger"] == "scheduler:morning_charge"
    assert payload["expected_decision"]["action_type"] == "charge_scheduled"
    assert payload["inputs"] == {
        "battery_soc_sensor": {"state": "42.5", "status": "ok"}
    }
    assert "config" not in payload
    assert "trace" not in payload
    assert "actions" not in payload


def test_emit_config_snapshot_is_deduplicated(monkeypatch) -> None:
    """A configuration snapshot is emitted once per content revision."""
    hass = MagicMock()
    hass.data = {}
    entry = MagicMock()
    entry.data = {"battery_soc_sensor": "sensor.battery_soc", "max_soc": 98}
    entry.options = {}
    logger = MagicMock(spec=logging.Logger)
    monkeypatch.setattr(
        "custom_components.energy_optimizer.utils.decision_dump._DUMP_LOGGER",
        logger,
    )

    emit_config_snapshot(hass, entry)
    emit_config_snapshot(hass, entry)

    assert logger.info.call_count == 1
    message = logger.info.call_args.args[0] % logger.info.call_args.args[1:]
    payload = json.loads(
        message.removeprefix("ENERGY_OPTIMIZER_CONFIG_SNAPSHOT v1 ")
    )
    assert payload["settings"] == {"max_soc": 98}
    assert payload["entity_aliases"] == {
        "battery_soc_sensor": "sensor.battery_soc",
        "sun": "sun.sun",
    }
