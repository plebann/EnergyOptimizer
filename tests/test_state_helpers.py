"""Tests for runtime state-reading helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.energy_optimizer.helpers import (
    get_float_state_info,
    get_float_value,
)


def _mock_hass(state_obj: MagicMock | None) -> MagicMock:
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get.return_value = state_obj
    return hass


def _mock_state(state_value: str | None) -> MagicMock:
    state = MagicMock()
    state.state = state_value
    return state


def test_get_float_state_info_missing_entity_id() -> None:
    hass = _mock_hass(None)
    value, raw, error = get_float_state_info(hass, None)

    assert value is None
    assert raw is None
    assert error == "missing"


def test_get_float_state_info_missing_state_object() -> None:
    hass = _mock_hass(None)
    value, raw, error = get_float_state_info(hass, "sensor.x")

    assert value is None
    assert raw is None
    assert error == "missing"


def test_get_float_state_info_unavailable_state() -> None:
    hass = _mock_hass(_mock_state("unavailable"))
    value, raw, error = get_float_state_info(hass, "sensor.x")

    assert value is None
    assert raw == "unavailable"
    assert error == "unavailable"


def test_get_float_state_info_invalid_numeric() -> None:
    hass = _mock_hass(_mock_state("not-a-number"))
    value, raw, error = get_float_state_info(hass, "sensor.x")

    assert value is None
    assert raw == "not-a-number"
    assert error == "invalid"


def test_get_float_state_info_valid_numeric() -> None:
    hass = _mock_hass(_mock_state("10.5"))
    value, raw, error = get_float_state_info(hass, "sensor.x")

    assert value == 10.5
    assert raw == "10.5"
    assert error is None


def test_get_float_value_returns_default_on_error() -> None:
    hass = _mock_hass(_mock_state("unknown"))
    assert get_float_value(hass, "sensor.x", default=123.0) == 123.0
