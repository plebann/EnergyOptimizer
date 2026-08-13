"""Tests for machine-readable decision dump logging."""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

from custom_components.energy_optimizer.utils.decision_dump import (
    DecisionAudit,
    emit_decision_dump,
)


def test_emit_decision_dump_produces_one_line_json(
    monkeypatch,
) -> None:
    """A completed decision dump is parseable and contains the agreed sections."""
    entry = MagicMock()
    entry.data = {"battery_soc_sensor": "sensor.battery_soc"}
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
        value=None,
        status="unavailable",
    )
    audit.record_step(
        "reserve_sufficient",
        kind="gate",
        inputs={"reserve_kwh": 3.2, "required_kwh": 2.1},
        result=True,
    )
    audit.record_action(
        "set_program_soc",
        entity_id="number.program2_soc",
        requested=75,
        status="executed",
    )
    logger = MagicMock(spec=logging.Logger)

    emit_decision_dump(
        logger,
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
    prefix = "ENERGY_OPTIMIZER_DECISION_DUMP v1 "
    assert message.startswith(prefix)
    assert "\n" not in message
    payload = json.loads(message.removeprefix(prefix))
    assert payload["schema_version"] == 1
    assert payload["integration_version"] == "0.0.0"
    assert payload["trigger"] == "scheduler:morning_charge"
    assert payload["config"]["data"] == entry.data
    assert payload["inputs"] == [
        {
            "key": "battery_soc",
            "source": "sensor.battery_soc",
            "value": None,
            "status": "unavailable",
        }
    ]
    assert payload["trace"][0]["result"] is True
    assert payload["actions"][0]["status"] == "executed"
