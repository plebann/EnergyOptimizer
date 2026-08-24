"""Tests for config flow entity validation helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from custom_components.energy_optimizer.config_flow import EnergyOptimizerConfigFlow
from custom_components.energy_optimizer.const import (
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG2_TIME_START_ENTITY,
)


def _mock_state(
    *,
    domain: str,
    state: str,
    attributes: dict[str, object] | None = None,
) -> MagicMock:
    mocked = MagicMock()
    mocked.domain = domain
    mocked.state = state
    mocked.attributes = attributes or {}
    return mocked


def _mock_hass_with_state(state_obj: MagicMock | None) -> MagicMock:
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get.return_value = state_obj
    return hass


def _mock_hass_with_states(states: dict[str, MagicMock | None]) -> MagicMock:
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get.side_effect = lambda entity_id: states.get(entity_id)
    return hass


def test_validate_entity_missing_entity_id_sets_error() -> None:
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_state(None)

    errors: dict[str, str] = {}
    result = flow._validate_entity(entity_id=None, field="x", errors=errors, value_type=float)

    assert result is None
    assert errors == {"x": "entity_not_found"}


def test_validate_entity_missing_entity_sets_error() -> None:
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_state(None)

    errors: dict[str, str] = {}
    result = flow._validate_entity(
        entity_id="sensor.price",
        field="x",
        errors=errors,
        value_type=float,
    )

    assert result is None
    assert errors == {"x": "entity_not_found"}


def test_validate_entity_non_numeric_sets_error() -> None:
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_state(_mock_state(domain="sensor", state="unknown"))

    errors: dict[str, str] = {}
    result = flow._validate_entity(
        entity_id="sensor.price",
        field="x",
        errors=errors,
        value_type=float,
    )

    assert result is None
    assert errors == {"x": "not_numeric"}


def test_validate_entity_expected_domain_mismatch_sets_error() -> None:
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_state(_mock_state(domain="sensor", state="1"))

    errors: dict[str, str] = {}
    result = flow._validate_entity(
        entity_id="sensor.not_a_number",
        field="x",
        errors=errors,
        expected_domain="number",
        domain_error="not_number_entity",
    )

    assert result is None
    assert errors == {"x": "not_number_entity"}


def test_validate_entity_int_coercion_returns_value() -> None:
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_state(_mock_state(domain="sensor", state="10"))

    errors: dict[str, str] = {}
    result = flow._validate_entity(
        entity_id="sensor.some_int",
        field="x",
        errors=errors,
        value_type=int,
    )

    assert result == 10
    assert errors == {}


def test_validate_entity_int_coercion_invalid_sets_error() -> None:
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_state(_mock_state(domain="sensor", state="10.5"))

    errors: dict[str, str] = {}
    result = flow._validate_entity(
        entity_id="sensor.some_int",
        field="x",
        errors=errors,
        value_type=int,
    )

    assert result is None
    assert errors == {"x": "not_numeric"}


def test_validate_price_entities_validates_optional_buy_and_sell_sources() -> None:
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_states(
        {
            "sensor.price": _mock_state(domain="sensor", state="1.111"),
            "sensor.buy_price": _mock_state(domain="sensor", state="1.327"),
            "sensor.sell_price": _mock_state(domain="sensor", state="1.428"),
        }
    )

    result = asyncio.run(
        flow._validate_price_entities(
            {
                "price_sensor": "sensor.price",
                "buy_price_sensor": "sensor.buy_price",
                "sell_price_sensor": "sensor.sell_price",
            }
        )
    )

    assert result == {}


def test_validate_price_entities_rejects_non_numeric_buy_source() -> None:
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_states(
        {
            "sensor.price": _mock_state(domain="sensor", state="1.111"),
            "sensor.buy_price": _mock_state(domain="sensor", state="unknown"),
        }
    )

    result = asyncio.run(
        flow._validate_price_entities(
            {
                "price_sensor": "sensor.price",
                "buy_price_sensor": "sensor.buy_price",
            }
        )
    )

    assert result == {"buy_price_sensor": "not_numeric"}


def test_program2_requires_start_time_control() -> None:
    """Program 2 SOC configuration requires its writable start-time control."""
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_states(
        {"number.program2_soc": _mock_state(domain="number", state="50")}
    )

    result = asyncio.run(
        flow._validate_program_entities(
            {CONF_PROG2_SOC_ENTITY: "number.program2_soc"}
        )
    )

    assert result == {CONF_PROG2_TIME_START_ENTITY: "entity_not_found"}


def test_program2_rejects_read_only_start_time_sensor() -> None:
    """Program 2 start time must be a writable time helper/control."""
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_states(
        {
            "number.program2_soc": _mock_state(domain="number", state="50"),
            "sensor.program2_start": _mock_state(domain="sensor", state="04:00"),
        }
    )

    result = asyncio.run(
        flow._validate_program_entities(
            {
                CONF_PROG2_SOC_ENTITY: "number.program2_soc",
                CONF_PROG2_TIME_START_ENTITY: "sensor.program2_start",
            }
        )
    )

    assert result == {CONF_PROG2_TIME_START_ENTITY: "not_time_entity"}


def test_program2_rejects_date_only_input_datetime() -> None:
    """Program 2 requires an input_datetime helper with a time component."""
    flow = EnergyOptimizerConfigFlow()
    flow.hass = _mock_hass_with_states(
        {
            "number.program2_soc": _mock_state(domain="number", state="50"),
            "input_datetime.program2_start": _mock_state(
                domain="input_datetime",
                state="2026-08-24",
                attributes={"has_time": False},
            ),
        }
    )

    result = asyncio.run(
        flow._validate_program_entities(
            {
                CONF_PROG2_SOC_ENTITY: "number.program2_soc",
                CONF_PROG2_TIME_START_ENTITY: "input_datetime.program2_start",
            }
        )
    )

    assert result == {CONF_PROG2_TIME_START_ENTITY: "not_time_entity"}
