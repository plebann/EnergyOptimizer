"""Tests for config flow entity validation helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.energy_optimizer.config_flow import EnergyOptimizerConfigFlow


def _mock_state(*, domain: str, state: str) -> MagicMock:
    mocked = MagicMock()
    mocked.domain = domain
    mocked.state = state
    return mocked


def _mock_hass_with_state(state_obj: MagicMock | None) -> MagicMock:
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get.return_value = state_obj
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
