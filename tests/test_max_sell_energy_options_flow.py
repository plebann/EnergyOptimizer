"""Regression tests: optional numeric selector in config/options flows.

Issue #40 replaced ``max_sell_energy_entity`` with a NumberSelector boxed as
an optional field. The HA frontend submits an empty box as explicit ``null``,
and a bare selector validates as float only -- so ``null`` raised
``expected float`` on save. Fixing that with ``vol.Any(None, ...)`` made the
field disappear from the modern (2026.x) frontend entirely, because the
wrapper injects a foreign ``allow_none`` key into the serialized selector.

The field is therefore a small ``NumberSelector`` subclass whose validator
accepts empty/None input as None while serializing to the exact plain-number
selector JSON the frontend knows how to render. These tests pin both sides:
the serialized shape (no ``allow_none`` anywhere) and save-time validation of
submissions shaped like what the frontend actually posts.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from voluptuous.error import Invalid

from custom_components.energy_optimizer.config_flow import (
    EnergyOptimizerConfigFlow,
    EnergyOptimizerOptionsFlow,
)
from custom_components.energy_optimizer.const import CONF_MAX_SELL_ENERGY

# One valid entity-id value per entity field of the control_entities step,
# keyed by the exact option strings the flow schema expects.
_SAMPLE_ENTITY_SUBMISSION: dict[str, str] = {
    "work_mode_entity": "select.mode",
    "inverter_export_surplus_switch": "switch.export_surplus",
    "inverter_offgrid_switch": "switch.offgrid",
    "bev_charging_binary_sensor": "binary_sensor.bev_charging",
    "bev_charging_power_sensor": "sensor.bev_power",
    "charge_current_entity": "number.charge_current",
    "discharge_current_entity": "number.discharge_current",
    "export_power_entity": "number.export_power",
    "max_charge_current_entity": "number.max_charge_current",
    "grid_charge_switch": "switch.grid_charge",
}


def _mock_config_entry(data: dict | None = None) -> MagicMock:
    entry = MagicMock(spec=["data", "options"])
    entry.data = dict(data or {})
    entry.options = {}
    return entry


def _submission(max_sell_energy) -> dict:
    """A full control_entities form submission (frontend posts every key)."""
    data = dict(_SAMPLE_ENTITY_SUBMISSION)
    data[CONF_MAX_SELL_ENERGY] = max_sell_energy
    return data


async def _render_options_step(entry_data: dict):
    flow = EnergyOptimizerOptionsFlow(_mock_config_entry(entry_data))
    result = await flow.async_step_control_entities()
    assert result["step_id"] == "control_entities"
    assert not result.get("errors")
    return result["data_schema"]


async def _render_setup_step():
    flow = EnergyOptimizerConfigFlow()
    result = await flow.async_step_control_entities()
    assert result["step_id"] == "control_entities"
    assert not result.get("errors")
    return result["data_schema"]


@pytest.mark.asyncio
async def test_options_flow_scheme_accepts_null_box() -> None:
    """Empty box (null) must validate to nothing, not 'expected float'."""
    schema = await _render_options_step({})
    # The exact submission that previously raised Invalid('expected float').
    schema(_submission(None))


@pytest.mark.asyncio
async def test_options_flow_scheme_accepts_numeric_value() -> None:
    schema = await _render_options_step({})
    result = schema(_submission(2.5))
    assert result[CONF_MAX_SELL_ENERGY] == 2.5


@pytest.mark.asyncio
async def test_options_flow_scheme_rejects_negative() -> None:
    schema = await _render_options_step({})
    with pytest.raises(Invalid):
        schema(_submission(-1.0))


@pytest.mark.asyncio
async def test_options_flow_presets_stored_value_and_clears_it() -> None:
    schema = await _render_options_step({CONF_MAX_SELL_ENERGY: 3.0})
    # UI pre-fills from entry data; a save without touching the box keeps it.
    assert schema(_submission(3.0))[CONF_MAX_SELL_ENERGY] == 3.0
    # Clearing the box saves null -> no cap.
    schema(_submission(None))


@pytest.mark.asyncio
async def test_setup_flow_scheme_accepts_null_box() -> None:
    """Same guarantee for the setup flow (fresh install, never set)."""
    schema = await _render_setup_step()
    validated = schema(_submission(None))
    assert validated.get(CONF_MAX_SELL_ENERGY) is None


@pytest.mark.asyncio
async def test_fields_serialize_to_known_number_selector_shape() -> None:
    """Pin the exact selector JSON the HA frontend receives for this field.

    The 2026.x frontend rendered flows only show fields whose serialized
    variant it recognizes; a plain number box (mode/step/min/unit) is that
    shape, and no extra keys (no ``allow_none`` etc.) may be allowed in.
    """
    import voluptuous_serialize
    from homeassistant.helpers import config_validation as cv

    async def _field(result):
        out = voluptuous_serialize.convert(
            result["data_schema"], custom_serializer=cv.custom_serializer
        )
        return next(f for f in out if f.get("name") == CONF_MAX_SELL_ENERGY)

    opts_result = await EnergyOptimizerOptionsFlow(
        _mock_config_entry({CONF_MAX_SELL_ENERGY: 2.7})
    ).async_step_control_entities(None)
    setup_result = await EnergyOptimizerConfigFlow().async_step_control_entities(
        None
    )

    for result, expect_default in ((opts_result, 2.7), (setup_result, None)):
        field = await _field(result)
        assert field["selector"] == {
            "number": {
                "mode": "box",
                "min": 0.0,
                "step": 0.1,
                "unit_of_measurement": "kWh",
            }
        }, f"unexpected serialized selector for {'options' if expect_default else 'setup'} flow: {field['selector']}"
        assert field["optional"] is True
        assert field["default"] == expect_default


@pytest.mark.asyncio
async def test_empty_string_submission_saves_none_both_flows() -> None:
    """The frontend may echo an empty box back as null or ''; both stay None."""
    schema_opts = await _render_options_step({CONF_MAX_SELL_ENERGY: 1.0})
    schema_setup = await _render_setup_step()
    for schema in (schema_opts, schema_setup):
        assert schema(_submission(""))[CONF_MAX_SELL_ENERGY] is None
