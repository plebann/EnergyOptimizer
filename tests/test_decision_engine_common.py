"""Tests for decision engine common helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.energy_optimizer.decision_engine.common import (
    build_no_action_outcome,
    mark_secure_energy,
    resolve_arbitrage_margin_gate,
    resolve_entry,
)
from custom_components.energy_optimizer.const import DOMAIN
from tests.conftest import market_windows, window

pytestmark = pytest.mark.enable_socket


def _mock_entry(entry_id: str, domain: str = DOMAIN) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.domain = domain
    entry.data = {}
    return entry


def test_resolve_entry_with_id_valid() -> None:
    hass = MagicMock()
    entry = _mock_entry("abc")
    hass.config_entries.async_get_entry.return_value = entry

    result = resolve_entry(hass, "abc")

    assert result is entry


def test_resolve_entry_with_id_invalid_domain() -> None:
    hass = MagicMock()
    entry = _mock_entry("abc", domain="other")
    hass.config_entries.async_get_entry.return_value = entry

    result = resolve_entry(hass, "abc")

    assert result is None


def test_resolve_entry_single_entry() -> None:
    hass = MagicMock()
    entry = _mock_entry("abc")
    hass.config_entries.async_entries.return_value = [entry]

    result = resolve_entry(hass, None)

    assert result is entry


def test_resolve_entry_multiple_entries() -> None:
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = [_mock_entry("a"), _mock_entry("b")]

    result = resolve_entry(hass, None)

    assert result is None


def test_resolve_entry_no_entries() -> None:
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []

    result = resolve_entry(hass, None)

    assert result is None


def test_arbitrage_margin_gate_enabled_carries_reference_source() -> None:
    reference = window(22, 6, price=200.0, next_day=True)

    margin_ok, details = resolve_arbitrage_margin_gate(
        sell_price=700.0, min_arbitrage_price=400.0, buy_reference=reference
    )

    assert margin_ok is True
    assert details == {
        "sell_price": 700.0,
        "min_arbitrage_price": 400.0,
        "buy_reference_price": 200.0,
        "arbitrage_margin": 500.0,
        "arbitrage_reason": "enabled",
        "buy_reference_source": "prices",
    }


def test_arbitrage_margin_gate_below_threshold_closes() -> None:
    reference = window(22, 6, price=400.0, next_day=True)

    margin_ok, details = resolve_arbitrage_margin_gate(
        sell_price=700.0, min_arbitrage_price=300.0, buy_reference=reference
    )

    assert margin_ok is False
    assert details["arbitrage_reason"] == "margin_below_threshold"
    assert details["arbitrage_margin"] == 300.0


def test_arbitrage_margin_gate_fails_closed_without_reference_price() -> None:
    reference = market_windows().night_buy

    margin_ok, details = resolve_arbitrage_margin_gate(
        sell_price=700.0, min_arbitrage_price=400.0, buy_reference=reference
    )

    assert reference.price is None
    assert margin_ok is False
    assert details == {
        "sell_price": 700.0,
        "min_arbitrage_price": 400.0,
        "arbitrage_reason": "missing_buy_reference_price",
        "buy_reference_source": "default",
    }


@pytest.mark.parametrize("program_number", [2, 4])
def test_mark_secure_energy_reports_secured_not_charged_energy(
    program_number: int,
) -> None:
    outcome = build_no_action_outcome(
        scenario="Morning Grid Charge",
        reason="no gap",
        current_soc=20,
        reserve_kwh=0.5,
        required_kwh=0.5,
        pv_forecast_kwh=0,
    )

    mark_secure_energy(
        outcome,
        current_soc=20.0,
        target_soc=30.0,
        gap_kwh=0.0,
        program_number=program_number,
    )

    assert outcome.action_type == "secure_energy"
    assert outcome.summary == "Energy reserve secured at 30% without grid charging"
    assert outcome.details["current_soc"] == 20
    assert outcome.details["target_soc"] == 30.0
    assert outcome.details["gap_kwh"] == 0.0
    assert outcome.details["program_number"] == program_number
    assert outcome.details["grid_charge_kwh"] == 0.0
