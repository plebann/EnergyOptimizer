"""Tests for Energy Optimizer service registration and dispatch."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import DOMAIN, SERVICE_MORNING_PEAK_SELL
from custom_components.energy_optimizer.services import async_register_services


@pytest.mark.asyncio
async def test_async_register_services_registers_morning_peak_sell() -> None:
    hass = MagicMock()
    hass.services.async_register = MagicMock()

    await async_register_services(hass)

    service_names = [call.args[1] for call in hass.services.async_register.call_args_list]
    assert SERVICE_MORNING_PEAK_SELL in service_names


@pytest.mark.asyncio
async def test_morning_peak_sell_handler_dispatches_to_decision_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = MagicMock()
    hass.services.async_register = MagicMock()
    run_morning_sell = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.services.async_run_morning_sell",
        run_morning_sell,
    )

    await async_register_services(hass)

    call_args = next(
        call
        for call in hass.services.async_register.call_args_list
        if call.args[0] == DOMAIN and call.args[1] == SERVICE_MORNING_PEAK_SELL
    )
    handler = call_args.args[2]

    service_call = MagicMock()
    service_call.data = {"entry_id": "entry-1", "margin": 1.2}

    await handler(service_call)

    run_morning_sell.assert_awaited_once_with(
        hass,
        entry_id="entry-1",
        margin=1.2,
    )
