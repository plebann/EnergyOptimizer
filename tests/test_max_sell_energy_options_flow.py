"""Regression tests: max_sell_energy numeric box in config/options flows.

Issue #40 replaced ``max_sell_energy_entity`` with a numeric kWh option.
The field must be a plain box-mode number selector (the serialized JSON the
HA frontend renders -- no wrapper-injected keys) and it is required: an
omitted submission is refused by ``vol.Required``, while ``0`` means no cap
(the engine caps only when the stored value is greater than zero).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
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


def _submission(max_sell_energy=None, omit: bool = False) -> dict:
    """A full control_entities form submission (frontend posts every key)."""
    data = dict(_SAMPLE_ENTITY_SUBMISSION)
    if not omit:
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
async def test_options_flow_scheme_accepts_zero_and_values() -> None:
    schema = await _render_options_step({})
    # 0 is a legal value and means "no cap".
    assert schema(_submission(0.0))[CONF_MAX_SELL_ENERGY] == pytest.approx(0.0)
    assert schema(_submission(2.5))[CONF_MAX_SELL_ENERGY] == pytest.approx(2.5)
    # Frontend boxes may submit numeric strings; the selector coerces.
    assert schema(_submission("4.0"))[CONF_MAX_SELL_ENERGY] == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_options_flow_scheme_rejects_negative() -> None:
    schema = await _render_options_step({})
    with pytest.raises(Invalid):
        schema(_submission(-1.0))


@pytest.mark.asyncio
async def test_options_flow_scheme_no_nullable_empty_submissions() -> None:
    """Empty/null submissions are rejected, not silently mapped to no cap."""
    schema = await _render_options_step({})
    for empty in (None, ""):
        with pytest.raises(Invalid):
            schema(_submission(empty))


@pytest.mark.asyncio
async def test_options_flow_scheme_required_default_fill_on_omission() -> None:
    """A required field with a default is back-filled when the key is absent."""
    schema = await _render_options_step({})
    assert schema(_submission(omit=True))[CONF_MAX_SELL_ENERGY] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_options_step_presets_stored_value() -> None:
    """A pre-filled box keeps its stored value unless the user edits it."""
    schema = await _render_options_step({CONF_MAX_SELL_ENERGY: 3.0})
    assert schema(_submission(3.0))[CONF_MAX_SELL_ENERGY] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_setup_flow_scheme_accepts_zero_default() -> None:
    """Fresh install prefills 0 (no cap); saving that stores a number, not empty."""
    schema = await _render_setup_step()
    validated = schema(_submission(0.0))
    assert validated[CONF_MAX_SELL_ENERGY] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_fields_serialize_to_known_number_selector_shape() -> None:
    """Pin the exact selector JSON the HA frontend receives for this field.

    The 2026.x frontend only renders the plain number-box variant; no
    wrapper-injected keys may appear and the field must be required.
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
    setup_result = await EnergyOptimizerConfigFlow().async_step_control_entities(None)

    for result, expect_default in ((opts_result, 2.7), (setup_result, 0.0)):
        field = await _field(result)
        assert field["selector"] == {
            "number": {
                "mode": "box",
                "min": 0.0,
                "step": 0.1,
                "unit_of_measurement": "kWh",
            }
        }, f"unexpected serialized selector: {field['selector']}"
        assert "optional" not in field
        assert "default" in field
        assert field["default"] == expect_default
