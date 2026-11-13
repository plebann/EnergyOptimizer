"""Tests for decision engine common helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.energy_optimizer.decision_engine.common import (
    build_no_action_outcome,
    classify_no_grid_decision,
    resolve_arbitrage_margin_gate,
    resolve_entry,
)
from custom_components.energy_optimizer.const import DOMAIN
from custom_components.energy_optimizer.utils.logging import DecisionOutcome
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


def _no_grid_outcome() -> DecisionOutcome:
    return build_no_action_outcome(
        scenario="Morning Grid Charge",
        reason="no gap",
        current_soc=20,
        reserve_kwh=0.5,
        required_kwh=0.5,
        pv_forecast_kwh=0,
    )


def _classify(
    *,
    needed_reserve_kwh: float,
    current_soc: float = 20.0,
    target_soc: float = 30.0,
    program_number: int = 2,
) -> DecisionOutcome:
    # 100 Ah * 50 V = 5 kWh, so 1 % SOC = 0.05 kWh; min_soc 10 % -> 0.5 kWh at 20 %.
    outcome = _no_grid_outcome()
    classify_no_grid_decision(
        outcome,
        needed_reserve_kwh=needed_reserve_kwh,
        current_soc=current_soc,
        target_soc=target_soc,
        min_soc=10.0,
        capacity_ah=100.0,
        voltage=50.0,
        gap_kwh=0.0,
        program_number=program_number,
    )
    return outcome


@pytest.mark.parametrize("program_number", [2, 4])
def test_independent_reserve_target_above_soc_is_secure_energy(
    program_number: int,
) -> None:
    outcome = _classify(needed_reserve_kwh=1.0, program_number=program_number)

    assert outcome.action_type == "secure_energy"
    assert outcome.summary == "Energy reserve secured at 30% without grid charging"
    assert outcome.details["current_soc"] == 20
    assert outcome.details["target_soc"] == 30.0
    assert outcome.details["gap_kwh"] == 0.0
    assert outcome.details["program_number"] == program_number
    assert outcome.details["grid_charge_kwh"] == 0.0


@pytest.mark.parametrize(
    ("needed_reserve_kwh", "current_soc", "target_soc"),
    [
        (0.0, 20.0, 10.0),  # no reserve need: floor write only
        (0.0, 5.0, 10.0),  # below the floor but nothing to protect
        (0.5, 20.3, 21.0),  # target above SOC only through ceil rounding
        (0.5, 20.0, 21.0),  # reserve exactly met, safety margin on top
        (1.0, 40.0, 30.0),  # reserve already above the target
        (1.0, 30.0, 30.0),  # target equals current SOC
    ],
)
def test_target_without_independent_reserve_above_soc_is_no_action(
    needed_reserve_kwh: float, current_soc: float, target_soc: float
) -> None:
    outcome = _classify(
        needed_reserve_kwh=needed_reserve_kwh,
        current_soc=current_soc,
        target_soc=target_soc,
    )

    assert outcome.action_type == "no_action"
    assert "grid_charge_kwh" not in outcome.details


def test_reserve_need_at_epsilon_is_no_action() -> None:
    assert _classify(needed_reserve_kwh=0.001, current_soc=10.0).action_type == (
        "no_action"
    )
    assert _classify(needed_reserve_kwh=0.0005, current_soc=10.0).action_type == (
        "no_action"
    )


def test_reserve_need_just_above_epsilon_is_secure_energy() -> None:
    outcome = _classify(needed_reserve_kwh=0.0011, current_soc=10.0, target_soc=11.0)

    assert outcome.action_type == "secure_energy"


def test_reserve_shortfall_at_epsilon_is_no_action() -> None:
    # needed 0.5005 vs reserve 0.5 kWh above min_soc: shortfall is below epsilon.
    outcome = _classify(needed_reserve_kwh=0.5005, current_soc=20.0, target_soc=21.0)

    assert outcome.action_type == "no_action"
