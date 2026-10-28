"""Tests for the integration setup-time SOC band check."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.energy_optimizer import async_setup_entry
from custom_components.energy_optimizer.const import (
    CONF_MAX_SOC,
    CONF_MIN_SOC,
)


def _mock_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    return hass


def _mock_entry(data: dict) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = data
    entry.options = {}
    entry.async_on_unload = MagicMock()
    return entry


async def _setup_with_entry(data: dict) -> None:
    hass = _mock_hass()
    with (
        patch(
            "custom_components.energy_optimizer.EnergyOptimizerCoordinator"
        ) as coordinator_cls,
        patch("custom_components.energy_optimizer.ActionScheduler"),
        patch("custom_components.energy_optimizer.emit_config_snapshot"),
    ):
        coordinator_cls.return_value.async_restore_night_buy_window_plans = AsyncMock()
        coordinator_cls.return_value.async_config_entry_first_refresh = AsyncMock()
        assert await async_setup_entry(hass, _mock_entry(data)) is True


@pytest.mark.asyncio
async def test_setup_entry_logs_error_for_persisted_infeasible_soc_pair(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A pre-PR entry persisting 95.4 / 95.5 logs a setup-time error."""
    await _setup_with_entry({CONF_MIN_SOC: 95.4, CONF_MAX_SOC: 95.5})

    assert any(
        "Infeasible SOC pair" in record.getMessage() for record in caplog.records
    ), "expected the setup-time error for the persisted infeasible SOC pair"


@pytest.mark.asyncio
async def test_setup_entry_is_silent_for_band_containing_writable_whole_percent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """95.0 / 95.5 admits 95, so no infeasibility error is logged."""
    await _setup_with_entry({CONF_MIN_SOC: 95.0, CONF_MAX_SOC: 95.5})

    assert not any(
        "Infeasible SOC pair" in record.getMessage() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_setup_entry_is_silent_for_default_soc_pair(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing values fall back to the defaults (15 / 100), which are valid."""
    await _setup_with_entry({})

    assert not any(
        "Infeasible SOC pair" in record.getMessage() for record in caplog.records
    )
