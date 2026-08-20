"""Tests for Energy Optimizer config entry migrations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from custom_components.energy_optimizer import async_migrate_entry
from custom_components.energy_optimizer.const import DOMAIN


def _migration_context(
    *,
    version: int,
    registry_entities: dict[tuple[str, str, str], str] | None = None,
) -> tuple[MagicMock, SimpleNamespace, MagicMock]:
    registry = MagicMock()
    registered_entity_ids = set((registry_entities or {}).values())
    registry.async_get_entity_id.side_effect = (
        lambda *key: (registry_entities or {}).get(key)
    )

    def generate_entity_id(domain: str, suggested_object_id: str) -> str:
        entity_id = f"{domain}.{suggested_object_id}"
        suffix = 2
        while entity_id in registered_entity_ids:
            entity_id = f"{domain}.{suggested_object_id}_{suffix}"
            suffix += 1
        return entity_id

    registry.async_generate_entity_id.side_effect = generate_entity_id

    hass = MagicMock()
    entry = SimpleNamespace(entry_id="entry-1", version=version)
    hass.config_entries.async_update_entry.side_effect = (
        lambda config_entry, *, version: setattr(config_entry, "version", version)
    )
    return hass, entry, registry


@pytest.mark.asyncio
async def test_migrate_consume_window_entities_with_legacy_default_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, registry = _migration_context(
        version=2,
        registry_entities={
            (
                "sensor",
                DOMAIN,
                "entry-1_midday_sell_window",
            ): "sensor.energy_optimizer_midday_sell_window",
            (
                "sensor",
                DOMAIN,
                "entry-1_midday_sell_window_tomorrow",
            ): "sensor.energy_optimizer_midday_sell_window_tomorrow",
        },
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.er.async_get",
        lambda _: registry,
    )

    assert await async_migrate_entry(hass, entry)

    assert registry.async_update_entity.call_args_list == [
        call(
            "sensor.energy_optimizer_midday_sell_window",
            new_entity_id="sensor.energy_optimizer_consume_window",
            new_unique_id="entry-1_consume_window",
        ),
        call(
            "sensor.energy_optimizer_midday_sell_window_tomorrow",
            new_entity_id="sensor.energy_optimizer_consume_window_tomorrow",
            new_unique_id="entry-1_consume_window_tomorrow",
        ),
    ]
    hass.config_entries.async_update_entry.assert_called_once_with(entry, version=3)


@pytest.mark.asyncio
async def test_migration_retains_customized_entity_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, registry = _migration_context(
        version=2,
        registry_entities={
            (
                "sensor",
                DOMAIN,
                "entry-1_midday_sell_window",
            ): "sensor.customized_today",
            (
                "sensor",
                DOMAIN,
                "entry-1_midday_sell_window_tomorrow",
            ): "sensor.customized_tomorrow",
        },
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.er.async_get",
        lambda _: registry,
    )

    assert await async_migrate_entry(hass, entry)

    assert registry.async_update_entity.call_args_list == [
        call(
            "sensor.customized_today",
            new_unique_id="entry-1_consume_window",
        ),
        call(
            "sensor.customized_tomorrow",
            new_unique_id="entry-1_consume_window_tomorrow",
        ),
    ]
    registry.async_generate_entity_id.assert_not_called()


@pytest.mark.asyncio
async def test_migration_uses_available_entity_id_when_default_is_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, registry = _migration_context(
        version=2,
        registry_entities={
            (
                "sensor",
                DOMAIN,
                "entry-1_midday_sell_window",
            ): "sensor.energy_optimizer_midday_sell_window",
            (
                "sensor",
                DOMAIN,
                "other-entry_consume_window",
            ): "sensor.energy_optimizer_consume_window",
        },
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.er.async_get",
        lambda _: registry,
    )

    assert await async_migrate_entry(hass, entry)

    registry.async_generate_entity_id.assert_called_once_with(
        "sensor",
        "energy_optimizer_consume_window",
    )
    registry.async_update_entity.assert_called_once_with(
        "sensor.energy_optimizer_midday_sell_window",
        new_entity_id="sensor.energy_optimizer_consume_window_2",
        new_unique_id="entry-1_consume_window",
    )


@pytest.mark.asyncio
async def test_migration_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    hass, entry, registry = _migration_context(
        version=2,
        registry_entities={
            (
                "sensor",
                DOMAIN,
                "entry-1_midday_sell_window",
            ): "sensor.energy_optimizer_midday_sell_window",
        },
    )
    async_get = MagicMock(return_value=registry)
    monkeypatch.setattr(
        "custom_components.energy_optimizer.er.async_get",
        async_get,
    )

    assert await async_migrate_entry(hass, entry)
    assert await async_migrate_entry(hass, entry)

    async_get.assert_called_once_with(hass)
    registry.async_update_entity.assert_called_once()
    hass.config_entries.async_update_entry.assert_called_once_with(entry, version=3)


@pytest.mark.asyncio
async def test_migration_tolerates_entry_without_old_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, registry = _migration_context(version=2)
    monkeypatch.setattr(
        "custom_components.energy_optimizer.er.async_get",
        lambda _: registry,
    )

    assert await async_migrate_entry(hass, entry)

    registry.async_update_entity.assert_not_called()
    hass.config_entries.async_update_entry.assert_called_once_with(entry, version=3)


@pytest.mark.asyncio
async def test_new_entry_does_not_run_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, _ = _migration_context(version=3)
    async_get = MagicMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.er.async_get",
        async_get,
    )

    assert await async_migrate_entry(hass, entry)

    async_get.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()
