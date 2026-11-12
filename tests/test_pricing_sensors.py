"""Tests for price-related Energy Optimizer sensors."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_SELL_PRICE_SENSOR,
)
from custom_components.energy_optimizer.coordinator import EnergyOptimizerCoordinator
from custom_components.energy_optimizer.entities.sensors.pricing import (
    BuyPriceSensor,
    DayBuyWindowSensor,
    DayBuyWindowTomorrowSensor,
    EveningSellWindowSensor,
    EveningSellWindowTomorrowSensor,
    ConsumeWindowSensor,
    ConsumeWindowTomorrowSensor,
    MinArbitrageMarginSensor,
    MorningSellBuyReferenceSensor,
    MorningSellWindowSensor,
    MorningSellWindowTomorrowSensor,
    NightBuyWindowSensor,
    NightBuyWindowTomorrowSensor,
    SellPriceSensor,
    SnapshotCache,
)
from custom_components.energy_optimizer.market_windows import (
    RankedMarketWindow,
    StaticMarketWindowResolver,
)
from tests.conftest import MARKET_WINDOWS_NOW, market_windows, window

TZ = timezone(timedelta(hours=2))
LOCAL_TZ = MARKET_WINDOWS_NOW.tzinfo


def _mock_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {}
    entry.options = {}
    return entry


def _hourly_entry_for_day(day: int, hour: int, price: float | str) -> dict[str, object]:
    dt = datetime(2026, 5, day, hour, 0, tzinfo=TZ)
    return {"time": dt.isoformat(), "price": price}


def _payload_for_day(day: int, low_start_hour: int = 10, low_hours: int = 2) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for hour in range(8, 16):
        is_low = low_start_hour <= hour < low_start_hour + low_hours
        entries.append(_hourly_entry_for_day(day, hour, 0.5 if is_low else 1.0))
    return entries


def _payload(low_start_hour: int = 10, low_hours: int = 2) -> list[dict[str, object]]:
    return _payload_for_day(8, low_start_hour, low_hours)


def _sensor(sensor_cls, **fields):
    """A window sensor fed by a static resolver holding the given snapshot fields."""
    coordinator = MagicMock()
    coordinator.data = {}
    return sensor_cls(
        coordinator,
        _mock_entry(),
        {},
        StaticMarketWindowResolver(market_windows(**fields)),
    )


def _ranked(
    primary: tuple[int, float], secondary: tuple[int, float] | None, next_day: bool = False
) -> RankedMarketWindow:
    return RankedMarketWindow(
        primary=window(primary[0], primary[0] + 1, primary[1], next_day),
        secondary=(
            window(secondary[0], secondary[0] + 1, secondary[1], next_day)
            if secondary
            else None
        ),
    )


def _at(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: now)


@pytest.fixture(autouse=True)
def _now(monkeypatch: pytest.MonkeyPatch) -> None:
    _at(monkeypatch, MARKET_WINDOWS_NOW)


def test_price_sensors_round_source_values_to_three_decimals() -> None:
    coordinator = MagicMock()
    coordinator.data = {
        "states": {
            "sensor.buy_price": 1.3274,
            "sensor.sell_price": 1.4286,
        }
    }
    config = {
        CONF_BUY_PRICE_SENSOR: "sensor.buy_price",
        CONF_SELL_PRICE_SENSOR: "sensor.sell_price",
    }

    buy_sensor = BuyPriceSensor(coordinator, _mock_entry(), config)
    sell_sensor = SellPriceSensor(coordinator, _mock_entry(), config)

    assert buy_sensor.native_value == 1.327
    assert sell_sensor.native_value == 1.429


def test_min_arbitrage_margin_sensor_exposes_configured_value() -> None:
    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    sensor = MinArbitrageMarginSensor(
        coordinator,
        _mock_entry(),
        {CONF_MIN_ARBITRAGE_PRICE: 0.2574},
    )

    assert sensor.native_value == 0.257


# --- Consume windows ---------------------------------------------------------


@pytest.mark.unit
def test_consume_window_sensor_publishes_the_snapshot_window() -> None:
    sensor = _sensor(ConsumeWindowSensor, consume=window(10, 12, 0.5))

    assert sensor.native_value == "10:00-12:00"
    assert sensor.extra_state_attributes == {"price": 0.5, "is_active": "off"}


@pytest.mark.unit
def test_consume_window_tomorrow_sensor_publishes_the_snapshot_window() -> None:
    sensor = _sensor(
        ConsumeWindowTomorrowSensor, consume_tomorrow=window(11, 13, 0.5, next_day=True)
    )

    assert sensor.native_value == "11:00-13:00"
    assert sensor.extra_state_attributes == {"price": 0.5}


@pytest.mark.unit
def test_consume_window_sensor_rounds_price_to_two_decimals() -> None:
    sensor = _sensor(ConsumeWindowSensor, consume=window(8, 10, 0.5449))

    assert sensor.native_value == "08:00-10:00"
    assert sensor.extra_state_attributes["price"] == 0.54


@pytest.mark.unit
@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(10, 30, "on"), (9, 59, "off"), (12, 0, "off")],
)
def test_consume_window_sensor_is_active_follows_the_window(
    monkeypatch: pytest.MonkeyPatch, hour: int, minute: int, expected: str
) -> None:
    _at(monkeypatch, datetime(2026, 5, 8, hour, minute, tzinfo=LOCAL_TZ))

    sensor = _sensor(ConsumeWindowSensor, consume=window(10, 12, 0.5))

    assert sensor.extra_state_attributes["is_active"] == expected


@pytest.mark.unit
def test_consume_window_sensors_keep_unknown_state_for_a_default_window() -> None:
    for sensor in (_sensor(ConsumeWindowSensor), _sensor(ConsumeWindowTomorrowSensor)):
        assert sensor.native_value is None
        assert sensor.extra_state_attributes == {}


@pytest.mark.unit
def test_consume_window_sensors_have_translation_keys_and_prefixed_unique_ids() -> None:
    today = _sensor(ConsumeWindowSensor)
    tomorrow = _sensor(ConsumeWindowTomorrowSensor)

    assert today.translation_key == "consume_window"
    assert today.unique_id == "entry-1_consume_window"
    assert tomorrow.translation_key == "consume_window_tomorrow"
    assert tomorrow.unique_id == "entry-1_consume_window_tomorrow"


@pytest.mark.unit
def test_consume_window_sensor_reads_the_resolver_on_every_update() -> None:
    snapshot = market_windows(consume=window(10, 12, 0.5))
    resolver = MagicMock()
    resolver.windows.return_value = snapshot
    coordinator = MagicMock()
    coordinator.data = {}
    sensor = ConsumeWindowSensor(coordinator, _mock_entry(), {}, resolver)

    assert sensor.native_value == "10:00-12:00"

    resolver.windows.return_value = replace(snapshot, consume=window(8, 10, 0.5))

    assert sensor.native_value == "08:00-10:00"


# --- Ranked sell windows -----------------------------------------------------


@pytest.mark.unit
def test_morning_sell_window_sensor_publishes_primary_and_secondary_window() -> None:
    sensor = _sensor(MorningSellWindowSensor, morning_sell=_ranked((7, 0.91), (5, 0.85)))

    assert sensor.native_value == "07:00"
    assert sensor.extra_state_attributes == {
        "price": 0.91,
        "second_window_start": "05:00",
        "second_window_price": 0.85,
        "second_window_gap_pct": 6.6,
    }


@pytest.mark.unit
def test_evening_sell_window_sensor_publishes_primary_and_secondary_window() -> None:
    sensor = _sensor(EveningSellWindowSensor, evening_sell=_ranked((17, 0.95), (20, 0.91)))

    assert sensor.native_value == "17:00"
    assert sensor.extra_state_attributes == {
        "price": 0.95,
        "second_window_start": "20:00",
        "second_window_price": 0.91,
        "second_window_gap_pct": 4.2,
    }


@pytest.mark.unit
def test_tomorrow_sell_window_sensors_read_their_own_fields() -> None:
    morning = _sensor(
        MorningSellWindowTomorrowSensor,
        morning_sell_tomorrow=_ranked((4, 0.9), (5, 0.7), next_day=True),
    )
    evening = _sensor(
        EveningSellWindowTomorrowSensor,
        evening_sell_tomorrow=_ranked((17, 0.954), (20, 0.912), next_day=True),
    )

    assert morning.native_value == "04:00"
    assert evening.native_value == "17:00"
    assert evening.extra_state_attributes == {
        "price": 0.954,
        "second_window_start": "20:00",
        "second_window_price": 0.912,
        "second_window_gap_pct": 4.4,
    }


@pytest.mark.unit
def test_ranked_sell_window_sensor_omits_gap_when_best_price_is_zero() -> None:
    sensor = _sensor(MorningSellWindowSensor, morning_sell=_ranked((4, 0.0), (5, -0.1)))

    assert sensor.native_value == "04:00"
    assert sensor.extra_state_attributes == {
        "price": 0.0,
        "second_window_start": "05:00",
        "second_window_price": -0.1,
    }


@pytest.mark.unit
def test_ranked_sell_window_sensor_is_unavailable_for_a_default_window() -> None:
    sensor = _sensor(EveningSellWindowSensor)

    assert sensor.native_value is None
    assert sensor.available is False
    assert sensor.extra_state_attributes == {}


@pytest.mark.unit
def test_ranked_sell_window_sensors_have_translation_keys_and_prefixed_unique_ids() -> None:
    morning = _sensor(MorningSellWindowSensor)
    evening_tomorrow = _sensor(EveningSellWindowTomorrowSensor)

    assert morning.translation_key == "morning_sell_window"
    assert morning.unique_id == "entry-1_morning_sell_window"
    assert evening_tomorrow.translation_key == "evening_sell_window_tomorrow"
    assert evening_tomorrow.unique_id == "entry-1_evening_sell_window_tomorrow"


# --- Buy windows -------------------------------------------------------------


@pytest.mark.unit
def test_day_buy_window_sensor_publishes_state_and_attributes() -> None:
    sensor = _sensor(DayBuyWindowSensor, day_buy=window(11, 13, 0.25))

    assert sensor.native_value == "11:00-13:00"
    assert sensor.extra_state_attributes == {
        "end": "13:00",
        "duration_hours": 2,
        "price": 0.25,
        "is_negative": False,
        "start_time": "2026-05-08T11:00:00+02:00",
        "end_time": "2026-05-08T13:00:00+02:00",
        "plan_date": "2026-05-08",
        "is_active": "on",
    }


@pytest.mark.unit
def test_day_buy_window_sensor_is_inactive_before_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _at(monkeypatch, datetime(2026, 5, 8, 10, 59, tzinfo=LOCAL_TZ))

    sensor = _sensor(DayBuyWindowSensor, day_buy=window(11, 13, 0.25))

    assert sensor.extra_state_attributes["is_active"] == "off"


@pytest.mark.unit
def test_day_buy_next_window_sensor_publishes_attributes_without_is_active() -> None:
    sensor = _sensor(
        DayBuyWindowTomorrowSensor, day_buy_next=window(11, 13, 0.2, next_day=True)
    )

    assert sensor.native_value == "11:00-13:00"
    assert sensor.extra_state_attributes == {
        "end": "13:00",
        "duration_hours": 2,
        "price": 0.2,
        "is_negative": False,
        "start_time": "2026-05-09T11:00:00+02:00",
        "end_time": "2026-05-09T13:00:00+02:00",
        "plan_date": "2026-05-09",
    }


@pytest.mark.unit
def test_buy_window_sensor_sets_is_negative_only_for_a_negative_price() -> None:
    negative = _sensor(DayBuyWindowSensor, day_buy=window(11, 13, -0.25))
    zero = _sensor(DayBuyWindowSensor, day_buy=window(10, 12, 0.0))

    assert negative.extra_state_attributes["is_negative"] is True
    assert negative.extra_state_attributes["price"] == -0.25
    assert zero.extra_state_attributes["is_negative"] is False
    assert zero.available is True


@pytest.mark.unit
def test_night_buy_window_sensor_projects_the_completed_night(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _at(monkeypatch, datetime(2026, 5, 9, 2, 30, tzinfo=LOCAL_TZ))

    sensor = _sensor(
        NightBuyWindowSensor,
        night_buy_completed=window(22, 4, 0.5),
        night_buy=window(1, 2, 9.0),
    )

    assert sensor.native_value == "22:00-04:00"
    assert sensor.extra_state_attributes["plan_date"] == "2026-05-09"
    assert sensor.extra_state_attributes["is_active"] == "on"


@pytest.mark.unit
def test_night_buy_window_sensor_is_inactive_at_the_window_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _at(monkeypatch, datetime(2026, 5, 9, 4, 0, tzinfo=LOCAL_TZ))

    sensor = _sensor(NightBuyWindowSensor, night_buy_completed=window(22, 4, 0.5))

    assert sensor.extra_state_attributes["is_active"] == "off"


@pytest.mark.unit
def test_night_buy_next_window_sensor_projects_night_buy_without_is_active() -> None:
    sensor = _sensor(
        NightBuyWindowTomorrowSensor, night_buy=window(1, 3, 0.5, next_day=True)
    )

    assert sensor.native_value == "01:00-03:00"
    assert sensor.extra_state_attributes["plan_date"] == "2026-05-09"
    assert "is_active" not in sensor.extra_state_attributes


@pytest.mark.unit
@pytest.mark.parametrize(
    ("sensor_cls", "unique_id"),
    [
        (NightBuyWindowSensor, "night_buy_window"),
        (NightBuyWindowTomorrowSensor, "night_buy_next_window"),
        (DayBuyWindowSensor, "day_buy_window"),
        (DayBuyWindowTomorrowSensor, "day_buy_next_window"),
        (MorningSellBuyReferenceSensor, "morning_sell_buy_reference"),
    ],
)
def test_buy_window_sensors_are_unavailable_for_a_default_window(
    sensor_cls, unique_id: str
) -> None:
    sensor = _sensor(sensor_cls)

    assert sensor.native_value is None
    assert sensor.available is False
    assert sensor.extra_state_attributes == {}
    assert sensor.translation_key == unique_id
    assert sensor.unique_id == f"entry-1_{unique_id}"


@pytest.mark.unit
def test_morning_sell_buy_reference_sensor_projects_the_snapshot_reference() -> None:
    sensor = _sensor(
        MorningSellBuyReferenceSensor, morning_sell_buy_reference=window(8, 13, 0.3)
    )

    assert sensor.native_value == "08:00"
    assert sensor.extra_state_attributes == {
        "end": "13:00",
        "duration_hours": 5,
        "price": 0.3,
        "is_negative": False,
    }


@pytest.mark.asyncio
async def test_coordinator_copies_price_payloads_to_avoid_in_place_source_mutation() -> None:
    prices_today = _payload(low_start_hour=10)
    prices_tomorrow = _payload_for_day(9, low_start_hour=11)

    state = MagicMock()
    state.state = "1.0"
    state.attributes = {
        "prices_today": prices_today,
        "prices_tomorrow": prices_tomorrow,
    }

    hass = MagicMock()
    hass.states.get.return_value = state

    entry = _mock_entry()
    entry.data = {CONF_SELL_PRICE_SENSOR: "sensor.sell"}

    coordinator = EnergyOptimizerCoordinator(hass, entry)
    data = await coordinator._async_update_data()

    snapshot_today = data["price_payloads"]["sensor.sell"]["prices_today"]
    snapshot_tomorrow = data["price_payloads"]["sensor.sell"]["prices_tomorrow"]

    assert snapshot_today == prices_today
    assert snapshot_tomorrow == prices_tomorrow
    assert snapshot_today is not prices_today
    assert snapshot_tomorrow is not prices_tomorrow

    prices_tomorrow.clear()

    assert snapshot_tomorrow != prices_tomorrow
    assert snapshot_tomorrow


@pytest.mark.unit
def test_buy_window_sensor_keeps_the_sign_of_an_average_rounded_to_negative_zero() -> None:
    """The resolver rounds -0.0004 to -0.0; the sensor still reports it as negative."""
    tiny_negative = _sensor(DayBuyWindowSensor, day_buy=window(11, 13, round(-0.0004, 3)))
    reference = _sensor(
        MorningSellBuyReferenceSensor,
        morning_sell_buy_reference=window(8, 13, round(-0.0004, 3)),
    )
    zero = _sensor(DayBuyWindowSensor, day_buy=window(11, 13, 0.0))

    assert tiny_negative.extra_state_attributes["is_negative"] is True
    assert reference.extra_state_attributes["is_negative"] is True
    assert zero.extra_state_attributes["is_negative"] is False


# --- Shared snapshot ---------------------------------------------------------


def _counting_cache(coordinator):
    resolver = MagicMock()
    resolver.windows.side_effect = lambda now=None: market_windows()
    return resolver, SnapshotCache(coordinator, resolver)


@pytest.mark.unit
def test_snapshot_cache_resolves_once_per_refresh_and_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    resolver, cache = _counting_cache(coordinator)

    first = cache.windows(MARKET_WINDOWS_NOW)
    assert cache.windows(MARKET_WINDOWS_NOW + timedelta(seconds=30)) is first
    assert resolver.windows.call_count == 1

    coordinator.data = {"states": {}}
    assert cache.windows(MARKET_WINDOWS_NOW) is not first
    assert resolver.windows.call_count == 2

    cache.windows(MARKET_WINDOWS_NOW + timedelta(minutes=1))
    assert resolver.windows.call_count == 3


@pytest.mark.unit
def test_window_sensors_of_one_platform_share_one_snapshot() -> None:
    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    resolver, cache = _counting_cache(coordinator)
    sensors = [
        cls(coordinator, _mock_entry(), {}, cache)
        for cls in (ConsumeWindowSensor, DayBuyWindowSensor, MorningSellWindowSensor)
    ]

    for sensor in sensors:
        sensor.native_value
        sensor.extra_state_attributes

    assert resolver.windows.call_count == 1
