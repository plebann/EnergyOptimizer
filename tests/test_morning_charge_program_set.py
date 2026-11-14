"""Morning Charge writes its temporary SOC to the Morning Charge Program Set."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_DAILY_LOAD_SENSOR,
    CONF_GRID_CHARGE_CURRENT_ENTITY,
    CONF_HIGH_TARIFF_END_HOUR_SENSOR,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG1_SOC_ENTITY,
    CONF_PROG1_TIME_START_ENTITY,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG2_TIME_START_ENTITY,
    CONF_PROG3_TIME_START_ENTITY,
    CONF_PROG6_SOC_ENTITY,
    CONF_PROG6_TIME_START_ENTITY,
    CONF_TEST_MODE,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.morning_charge import (
    async_run_morning_charge,
)
from custom_components.energy_optimizer.market_windows import (
    MarketWindows,
    StaticMarketWindowResolver,
)
from tests.conftest import market_windows, window

pytestmark = pytest.mark.enable_socket

CONFIG = {
    CONF_PROG6_SOC_ENTITY: "number.prog6_soc",
    CONF_PROG6_TIME_START_ENTITY: "time.prog6_start",
    CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
    CONF_PROG1_TIME_START_ENTITY: "time.prog1_start",
    CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
    CONF_PROG2_TIME_START_ENTITY: "time.prog2_start",
    CONF_GRID_CHARGE_CURRENT_ENTITY: "number.grid_charge_current",
    CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
    CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
    CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
    CONF_BATTERY_CAPACITY_AH: 100,
    CONF_BATTERY_VOLTAGE: 50,
    CONF_MIN_SOC: 10,
    CONF_MAX_SOC: 100,
    CONF_BATTERY_EFFICIENCY: 100,
    CONF_TEST_MODE: False,
}

STATES = {
    "number.prog6_soc": "10",
    "time.prog6_start": "22:00:00",
    "number.prog1_soc": "10",
    "time.prog1_start": "01:30:00",
    "number.prog2_soc": "10",
    "time.prog2_start": "04:00:00",
    "number.grid_charge_current": "0",
    "sensor.battery_soc": "20",
    "sensor.daily_load": "48",
    "sensor.tariff_end_hour": "13",
}


def _hass(
    states: dict[str, str],
    windows: MarketWindows | None = None,
    config: dict[str, object] | None = None,
) -> MagicMock:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.domain = DOMAIN
    entry.data = config or CONFIG
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry
    hass.states.get.side_effect = lambda entity_id: (
        MagicMock(state=states[entity_id], attributes={})
        if entity_id in states
        else None
    )
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.bus = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry-1": {
                "last_optimization_sensor": MagicMock(),
                "optimization_history_sensor": MagicMock(),
                "market_windows": StaticMarketWindowResolver(
                    windows or market_windows()
                ),
            }
        }
    }
    return hass


def _writes(hass: MagicMock) -> list[tuple[str, str, object]]:
    """Return (domain, entity_id, value) of every control write, in order."""
    writes: list[tuple[str, str, object]] = []
    for call in hass.services.async_call.call_args_list:
        domain, service, data = call.args[:3]
        if service in ("set_value", "set_datetime"):
            writes.append(
                (domain, data["entity_id"], data.get("value", data.get("time")))
            )
    return writes


def _outcome(hass: MagicMock) -> tuple[str, dict[str, object]]:
    return hass.data[DOMAIN]["entry-1"]["last_optimization_sensor"].log_optimization.call_args.args


@pytest.fixture(autouse=True)
def _schedule_completion(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    schedule = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.async_schedule_charge_completion",
        schedule,
    )
    return schedule


@pytest.mark.asyncio
async def test_window_across_midnight_writes_the_same_target_to_programs_6_and_1() -> None:
    """A 23-04 window covers P6 and P1; P2 starts as the window ends."""
    hass = _hass(STATES, market_windows(night_buy=window(23, 4, 0.4)))

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    soc_writes = [w for w in _writes(hass) if w[1].endswith("_soc")]
    assert [w[1] for w in soc_writes] == ["number.prog6_soc", "number.prog1_soc"]
    assert soc_writes[0][2] == soc_writes[1][2] > 10
    scenario, details = _outcome(hass)
    assert details["programs"] == [6, 1]


@pytest.mark.asyncio
async def test_window_inside_morning_programs_writes_programs_1_and_2() -> None:
    hass = _hass(STATES, market_windows(night_buy=window(3, 6, 0.4, next_day=True)))

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    soc_writes = [w for w in _writes(hass) if w[1].endswith("_soc")]
    assert [w[1] for w in soc_writes] == ["number.prog1_soc", "number.prog2_soc"]


@pytest.mark.asyncio
async def test_no_program_start_time_is_ever_written() -> None:
    hass = _hass(STATES, market_windows(night_buy=window(23, 4, 0.4)))

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    assert [w for w in _writes(hass) if w[0] in ("time", "input_datetime")] == []


@pytest.mark.asyncio
async def test_program_already_holding_the_target_is_not_written() -> None:
    hass = _hass(STATES, market_windows(night_buy=window(23, 4, 0.4)))
    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)
    target = [w for w in _writes(hass) if w[1] == "number.prog6_soc"][0][2]

    states = {**STATES, "number.prog6_soc": str(target)}
    hass = _hass(states, market_windows(night_buy=window(23, 4, 0.4)))
    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    soc_writes = [w[1] for w in _writes(hass) if w[1].endswith("_soc")]
    assert soc_writes == ["number.prog1_soc"]


@pytest.mark.asyncio
async def test_a_failed_write_rolls_back_programs_already_written() -> None:
    hass = _hass(STATES, market_windows(night_buy=window(23, 4, 0.4)))

    async def _call(domain: str, service: str, data: dict, **_kwargs: object) -> None:
        if data.get("entity_id") == "number.prog1_soc" and data["value"] != 10:
            raise HomeAssistantError("write failed")

    hass.services.async_call = AsyncMock(side_effect=_call)

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    soc_writes = [(w[1], w[2]) for w in _writes(hass) if w[1].endswith("_soc")]
    assert soc_writes[0][0] == "number.prog6_soc"
    assert soc_writes[0][1] > 10
    assert soc_writes[-1] == ("number.prog6_soc", 10.0)
    assert not [w for w in _writes(hass) if w[1] == "number.grid_charge_current"]
    _, details = _outcome(hass)
    assert "target_soc" not in details


@pytest.mark.asyncio
async def test_unreadable_program_start_time_fails_the_run_without_writes() -> None:
    states = {k: v for k, v in STATES.items() if k != "time.prog1_start"}
    hass = _hass(states, market_windows(night_buy=window(23, 4, 0.4)))

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    assert _writes(hass) == []
    _, details = _outcome(hass)
    assert "target_soc" not in details


@pytest.mark.asyncio
async def test_time_only_program_still_bounds_the_previous_program_interval() -> None:
    """P3 (start time, no SOC control) at 05:00 ends P2; 05-06 touches no writable program."""
    config = {**CONFIG, CONF_PROG3_TIME_START_ENTITY: "time.prog3_start"}
    states = {**STATES, "time.prog3_start": "05:00:00"}
    hass = _hass(states, market_windows(night_buy=window(5, 6, 0.4)), config)

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    assert [w for w in _writes(hass) if w[1].endswith("_soc")] == []


@pytest.mark.asyncio
async def test_invalid_program_set_leaves_the_max_charge_current_untouched() -> None:
    """A run that fails program validation writes nothing, not even the max current."""
    config = {**CONFIG, CONF_CHARGE_CURRENT_ENTITY: "number.max_charge_current"}
    states = {
        **{k: v for k, v in STATES.items() if k != "time.prog1_start"},
        "number.max_charge_current": "0",
    }
    hass = _hass(states, market_windows(night_buy=window(23, 4, 0.4)), config)

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    assert _writes(hass) == []


@pytest.mark.asyncio
async def test_overlapping_runs_for_one_entry_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading, writing and recording the plan never interleave between runs."""
    import asyncio

    from custom_components.energy_optimizer.decision_engine.morning_charge import (
        MorningChargeStrategy,
    )

    events: list[str] = []

    async def _run(self: object) -> None:
        events.append("in")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        events.append("out")

    monkeypatch.setattr(MorningChargeStrategy, "run", _run)
    hass = _hass(STATES)

    await asyncio.gather(
        async_run_morning_charge(hass, entry_id="entry-1"),
        async_run_morning_charge(hass, entry_id="entry-1"),
    )

    assert events == ["in", "out", "in", "out"]
