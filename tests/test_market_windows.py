"""Tests for the Market Window Resolver vocabulary and the static adapter."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_HIGH_TARIFF_END_HOUR_SENSOR,
    CONF_HIGH_TARIFF_START_HOUR_SENSOR,
    CONF_SELL_PRICE_SENSOR,
    DOMAIN,
)
from custom_components.energy_optimizer.market_windows import (
    CoordinatorMarketWindowResolver,
    MarketWindows,
    MarketWindowSource,
    RankedMarketWindow,
    ResolvedHour,
    ResolvedMarketWindow,
    StaticMarketWindowResolver,
    default_market_windows,
    market_window_resolver,
)
from custom_components.energy_optimizer.night_buy_window import NightBuyWindowPlan
from custom_components.energy_optimizer.night_buy_window_manager import (
    NightBuyWindowPlanManager,
)
from tests.conftest import MARKET_WINDOWS_NOW, market_windows, window

TZ = ZoneInfo("Europe/Warsaw")


def _dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, day, hour, minute, tzinfo=TZ)


def _window(
    start: datetime,
    end: datetime,
    *,
    price: float | None = 0.5,
    source: MarketWindowSource = MarketWindowSource.PRICES,
    reason: str | None = None,
) -> ResolvedMarketWindow:
    return ResolvedMarketWindow(
        start=start, end=end, price=price, source=source, reason=reason
    )


def _primary(
    start_hour: int, end_hour: int, *, price: float, next_day: bool = False
) -> RankedMarketWindow:
    return RankedMarketWindow(
        primary=window(start_hour, end_hour, price=price, next_day=next_day),
        secondary=None,
    )


def _snapshot(**overrides: object) -> MarketWindows:
    """A snapshot at MARKET_WINDOWS_NOW (2026-05-08 12:00) of price-resolved windows.

    Only ``night_buy_completed`` (last night, which the conftest builder cannot
    place) keeps its default.
    """
    resolved: dict[str, object] = {
        "night_buy": window(22, 6, price=0.45),
        "night_buy_after": window(22, 6, price=0.50, next_day=True),
        "day_buy": window(13, 15, price=0.60),
        "day_buy_next": window(12, 14, price=0.55, next_day=True),
        "morning_sell": _primary(7, 8, price=1.20),
        "morning_sell_tomorrow": _primary(7, 8, price=1.10, next_day=True),
        "evening_sell": _primary(17, 18, price=1.30),
        "evening_sell_tomorrow": _primary(18, 19, price=1.25, next_day=True),
        "consume": window(12, 14, price=0.10),
        "consume_tomorrow": window(11, 13, price=0.12, next_day=True),
        "morning_sell_buy_reference": window(8, 13, price=0.70),
        "high_tariff_start": ResolvedHour(15, MarketWindowSource.CONFIG_ENTITY),
        "high_tariff_end": ResolvedHour(13, MarketWindowSource.CONFIG_ENTITY),
    }
    return market_windows(**{**resolved, **overrides})


ALL_WINDOW_FIELDS = frozenset(
    {
        "night_buy",
        "night_buy_completed",
        "night_buy_after",
        "day_buy",
        "day_buy_next",
        "morning_sell",
        "morning_sell_tomorrow",
        "evening_sell",
        "evening_sell_tomorrow",
        "consume",
        "consume_tomorrow",
        "morning_sell_buy_reference",
        "high_tariff_start",
        "high_tariff_end",
    }
)


class TestMarketWindowSource:
    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("PLAN", "plan"),
            ("PRICES", "prices"),
            ("CONFIG_ENTITY", "config_entity"),
            ("LEGACY_ENTITY", "legacy_entity"),
            ("DEFAULT", "default"),
        ],
    )
    def test_names_every_market_window_source(self, name: str, value: str) -> None:
        assert MarketWindowSource[name] == value

    def test_has_no_other_source(self) -> None:
        assert len(MarketWindowSource) == 5


class TestResolvedMarketWindow:
    def test_hours_are_derived_from_a_window_spanning_midnight(self) -> None:
        night = _window(_dt(8, 22), _dt(9, 6))

        assert (night.hour, night.end_hour) == (22, 6)
        assert night.duration_hours == 8.0
        assert night.plan_date == _dt(9, 6).date()

    def test_plan_date_is_the_local_date_the_window_ends_on(self) -> None:
        ends_after_midnight_local = _window(
            _dt(8, 22), datetime(2026, 5, 8, 22, 30, tzinfo=UTC)
        )

        assert ends_after_midnight_local.plan_date == _dt(9, 0).date()

    def test_duration_counts_elapsed_hours_across_a_dst_change(self) -> None:
        autumn_night = _window(
            datetime(2026, 10, 24, 22, tzinfo=TZ), datetime(2026, 10, 25, 6, tzinfo=TZ)
        )

        assert autumn_night.duration_hours == 9.0

    def test_default_window_is_a_fallback_and_yields_the_callers_default_hour(
        self,
    ) -> None:
        default = _window(
            _dt(8, 13),
            _dt(8, 15),
            price=None,
            source=MarketWindowSource.DEFAULT,
            reason="unavailable",
        )

        assert default.is_fallback is True
        assert default.start_hour_or(9) == 9

    def test_resolved_window_keeps_its_own_start_hour(self) -> None:
        resolved = _window(_dt(8, 13), _dt(8, 15))

        assert resolved.is_fallback is False
        assert resolved.start_hour_or(9) == 13

    def test_contains_is_inclusive_of_start_and_exclusive_of_end(self) -> None:
        night = _window(_dt(8, 22), _dt(9, 6))

        assert night.contains(_dt(8, 22)) is True
        assert night.contains(_dt(9, 2, 30)) is True
        assert night.contains(_dt(9, 6)) is False
        assert night.contains(_dt(8, 21, 59)) is False

    def test_contains_compares_instants_in_the_repeated_dst_hour(self) -> None:
        # 2026-10-25: Warsaw repeats 02:00-03:00; fold=1 is the second pass.
        second_two = datetime(2026, 10, 25, 2, tzinfo=TZ, fold=1)
        first_two_thirty = datetime(2026, 10, 25, 2, 30, tzinfo=TZ)
        after_fold = _window(second_two, datetime(2026, 10, 25, 4, tzinfo=TZ))

        assert after_fold.contains(first_two_thirty) is False
        assert after_fold.contains(first_two_thirty.astimezone(UTC)) is False
        assert after_fold.contains(second_two.astimezone(UTC)) is True

    def test_windows_differing_only_by_dst_fold_are_not_equal(self) -> None:
        six = datetime(2026, 10, 25, 6, tzinfo=TZ)
        five_hours = _window(datetime(2026, 10, 25, 2, tzinfo=TZ), six)
        four_hours = _window(datetime(2026, 10, 25, 2, tzinfo=TZ, fold=1), six)

        assert five_hours != four_hours
        assert hash(five_hours) != hash(four_hours)

    def test_windows_at_the_same_instants_are_equal_in_any_zone(self) -> None:
        local = _window(_dt(8, 22), _dt(9, 6))
        utc = _window(_dt(8, 22).astimezone(UTC), _dt(9, 6).astimezone(UTC))

        assert local == utc
        assert hash(local) == hash(utc)

    def test_a_resolved_window_cannot_be_changed(self) -> None:
        resolved = _window(_dt(8, 13), _dt(8, 15))

        with pytest.raises(FrozenInstanceError):
            resolved.price = 9.9  # type: ignore[misc]

    def test_end_must_be_after_start(self) -> None:
        at_fifteen = _dt(8, 15)

        with pytest.raises(ValueError):
            _window(at_fifteen, at_fifteen)

    def test_end_after_start_is_judged_by_instant_in_the_repeated_dst_hour(
        self,
    ) -> None:
        first_two = datetime(2026, 10, 25, 2, tzinfo=TZ)
        second_two = datetime(2026, 10, 25, 2, tzinfo=TZ, fold=1)
        first_two_thirty = datetime(2026, 10, 25, 2, 30, tzinfo=TZ)

        repeated_hour = _window(first_two, second_two)
        assert repeated_hour.duration_hours == 1.0

        with pytest.raises(ValueError):
            _window(second_two, first_two_thirty)

    def test_naive_datetimes_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            _window(datetime(2026, 5, 8, 13), datetime(2026, 5, 8, 15))

    def test_a_non_finite_price_is_rejected(self) -> None:
        start, end = _dt(8, 13), _dt(8, 15)

        with pytest.raises(ValueError):
            _window(start, end, price=float("nan"))

    @pytest.mark.parametrize(
        ("source", "reason"),
        [
            (MarketWindowSource.PRICES, "unavailable"),
            (MarketWindowSource.DEFAULT, None),
        ],
    )
    def test_reason_is_set_exactly_when_the_source_is_default(
        self, source: MarketWindowSource, reason: str | None
    ) -> None:
        start, end = _dt(8, 13), _dt(8, 15)

        with pytest.raises(ValueError):
            _window(start, end, source=source, reason=reason)


class TestMarketWindows:
    def test_changed_from_nothing_reports_every_window_field(self) -> None:
        assert _snapshot().changed_from(None) == ALL_WINDOW_FIELDS

    def test_changed_from_reports_only_the_field_whose_price_changed(self) -> None:
        previous = _snapshot()
        current = _snapshot(night_buy=window(22, 6, price=0.46))

        assert current.changed_from(previous) == {"night_buy"}

    def test_changed_from_sees_a_night_buy_moved_across_the_dst_fold(self) -> None:
        six = datetime(2026, 10, 25, 6, tzinfo=TZ)
        previous = _snapshot(
            night_buy=_window(datetime(2026, 10, 25, 2, tzinfo=TZ), six)
        )
        current = _snapshot(
            night_buy=_window(datetime(2026, 10, 25, 2, tzinfo=TZ, fold=1), six)
        )

        assert current.changed_from(previous) == {"night_buy"}

    def test_a_later_now_alone_changes_nothing(self) -> None:
        previous = _snapshot()
        current = _snapshot(now=_dt(8, 12, 30))

        assert current.changed_from(previous) == frozenset()

    def test_a_new_secondary_sell_window_changes_the_ranked_field(self) -> None:
        previous = _snapshot()
        current = _snapshot(
            evening_sell=RankedMarketWindow(
                primary=window(17, 18, price=1.30),
                secondary=window(19, 20, price=1.05),
            )
        )

        assert current.changed_from(previous) == {"evening_sell"}

    def test_a_tariff_hour_falling_back_to_default_is_a_change(self) -> None:
        previous = _snapshot()
        current = _snapshot(
            high_tariff_end=ResolvedHour(13, MarketWindowSource.DEFAULT)
        )

        assert current.changed_from(previous) == {"high_tariff_end"}

    def test_day_buy_for_todays_plan_date_is_the_day_buy_window(self) -> None:
        snapshot = _snapshot()

        assert snapshot.day_buy_for(_dt(8, 0).date()) is snapshot.day_buy

    def test_day_buy_for_the_next_plan_date_is_the_next_day_buy_window(
        self,
    ) -> None:
        snapshot = _snapshot()

        assert snapshot.day_buy_for(_dt(9, 0).date()) is snapshot.day_buy_next

    def test_day_buy_for_an_unplanned_date_is_none(self) -> None:
        assert _snapshot().day_buy_for(_dt(10, 0).date()) is None

    def test_a_snapshot_cannot_change_under_its_reader(self) -> None:
        snapshot = _snapshot()

        with pytest.raises(FrozenInstanceError):
            snapshot.night_buy = snapshot.night_buy_after  # type: ignore[misc]


class TestDefaultMarketWindows:
    def test_night_buy_defaults_to_tonight_22_to_06(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        assert defaults.night_buy == ResolvedMarketWindow(
            start=_dt(8, 22),
            end=_dt(9, 6),
            price=None,
            source=MarketWindowSource.DEFAULT,
            reason="unavailable",
        )

    def test_night_buy_default_after_midnight_is_the_coming_night(self) -> None:
        defaults = default_market_windows(_dt(9, 2))

        assert (defaults.night_buy.start, defaults.night_buy.end) == (
            _dt(9, 22),
            _dt(10, 6),
        )
        assert defaults.night_buy.contains(_dt(9, 2)) is False

    def test_day_buy_defaults_to_the_two_hours_before_the_high_tariff_start(
        self,
    ) -> None:
        defaults = default_market_windows(_dt(8, 12))

        assert (defaults.day_buy.start, defaults.day_buy.end) == (
            _dt(8, 13),
            _dt(8, 15),
        )
        assert defaults.day_buy.is_fallback is True

    def test_a_default_buy_window_already_ended_rolls_forward_one_day(self) -> None:
        defaults = default_market_windows(_dt(8, 16))

        assert (defaults.day_buy.start, defaults.day_buy.end) == (
            _dt(9, 13),
            _dt(9, 15),
        )

    def test_a_default_buy_window_ending_exactly_now_rolls_forward(self) -> None:
        defaults = default_market_windows(_dt(8, 15))

        assert defaults.day_buy.start == _dt(9, 13)

    def test_morning_sell_defaults_to_07_with_no_secondary_window(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        assert defaults.morning_sell == RankedMarketWindow(
            primary=ResolvedMarketWindow(
                start=_dt(8, 7),
                end=_dt(8, 8),
                price=None,
                source=MarketWindowSource.DEFAULT,
                reason="unavailable",
            ),
            secondary=None,
        )

    def test_evening_sell_defaults_to_17(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        primary = defaults.evening_sell.primary
        assert (primary.start, primary.end) == (_dt(8, 17), _dt(8, 18))
        assert defaults.evening_sell.secondary is None

    def test_tomorrows_sell_windows_default_to_the_same_hours_tomorrow(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        assert defaults.morning_sell_tomorrow.primary.start == _dt(9, 7)
        assert defaults.evening_sell_tomorrow.primary.start == _dt(9, 17)

    def test_consume_defaults_to_12_00_today_and_tomorrow(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        assert (defaults.consume.start, defaults.consume.end) == (_dt(8, 12), _dt(8, 13))
        assert defaults.consume_tomorrow.start == _dt(9, 12)
        assert defaults.consume.is_fallback is True

    def test_high_tariff_defaults_to_start_15_and_end_13(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        assert defaults.high_tariff_start == ResolvedHour(15, MarketWindowSource.DEFAULT)
        assert defaults.high_tariff_end == ResolvedHour(13, MarketWindowSource.DEFAULT)

    def test_morning_sell_buy_reference_defaults_to_the_hour_after_the_sell_until_tariff_end(
        self,
    ) -> None:
        defaults = default_market_windows(_dt(8, 12))

        reference = defaults.morning_sell_buy_reference
        assert (reference.start, reference.end, reference.price) == (
            _dt(8, 8),
            _dt(8, 13),
            None,
        )

    def test_night_buy_after_defaults_to_midnight_after_the_active_night(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        assert (defaults.night_buy_after.start, defaults.night_buy_after.end) == (
            _dt(10, 0),
            _dt(10, 6),
        )

    def test_completed_night_defaults_to_the_night_that_ended_this_morning(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        completed = defaults.night_buy_completed
        assert (completed.start, completed.end) == (_dt(7, 22), _dt(8, 6))
        assert completed.plan_date == _dt(8, 0).date()
        assert completed.is_fallback is True

    def test_next_day_buy_defaults_to_the_morning_the_night_buy_ends_on(self) -> None:
        defaults = default_market_windows(_dt(8, 12))

        assert (defaults.day_buy_next.start, defaults.day_buy_next.end) == (
            _dt(9, 13),
            _dt(9, 15),
        )
        assert defaults.day_buy_for(defaults.night_buy.plan_date) is defaults.day_buy_next

    def test_after_the_day_buy_rolled_forward_both_day_buy_defaults_coincide(
        self,
    ) -> None:
        defaults = default_market_windows(_dt(8, 16))

        assert defaults.day_buy_next == defaults.day_buy
        assert defaults.day_buy_next.start == _dt(9, 13)
        assert defaults.day_buy_for(defaults.night_buy.plan_date) == defaults.day_buy_next

    def test_an_unreliable_reason_is_carried_by_every_default_window(self) -> None:
        defaults = default_market_windows(_dt(8, 12), reason="unreliable")

        assert defaults.night_buy.reason == "unreliable"
        assert defaults.evening_sell.primary.reason == "unreliable"
        assert defaults.consume.reason == "unreliable"


class TestStaticMarketWindowResolver:
    def test_returns_the_given_snapshot_unchanged_whatever_now_is(self) -> None:
        snapshot = _snapshot()
        resolver = StaticMarketWindowResolver(snapshot)

        assert resolver.windows() is snapshot
        assert resolver.windows(now=_dt(9, 3)) is snapshot


class TestBuilders:
    def test_window_builds_a_price_window_on_the_anchor_day(self) -> None:
        built = window(13, 15, price=0.6)

        assert (built.start, built.end, built.price, built.source) == (
            _dt(8, 13),
            _dt(8, 15),
            0.6,
            MarketWindowSource.PRICES,
        )

    def test_window_spanning_midnight_can_be_placed_on_the_next_day(self) -> None:
        built = window(22, 6, price=0.45, next_day=True)

        assert (built.start, built.end) == (_dt(9, 22), _dt(10, 6))

    def test_market_windows_overrides_one_field_and_defaults_the_rest(self) -> None:
        snapshot = market_windows(night_buy=window(22, 6, price=0.45))

        assert snapshot.night_buy == window(22, 6, price=0.45)
        assert snapshot.now == _dt(8, 12)
        assert snapshot.evening_sell == default_market_windows(_dt(8, 12)).evening_sell


class TestMarketWindowResolverAccessor:
    def test_returns_the_resolver_stored_under_market_windows(self) -> None:
        hass = MagicMock()
        resolver = StaticMarketWindowResolver(_snapshot())
        hass.data = {DOMAIN: {"entry-1": {"market_windows": resolver}}}

        assert market_window_resolver(hass, "entry-1") is resolver


# --- Production adapter -----------------------------------------------------

NOW = MARKET_WINDOWS_NOW  # 2026-05-08 12:00 Europe/Warsaw
BUY = "sensor.buy"
SELL = "sensor.sell"


def _state(value: object, **attributes: object) -> MagicMock:
    state = MagicMock()
    state.state = value
    state.attributes = attributes
    return state


def _hass(states: dict[str, object] | None = None) -> MagicMock:
    """A hass stub whose `states.get` answers from `states` (a value or a state)."""
    hass = MagicMock()
    hass.data = {}
    table = {
        entity_id: value if isinstance(value, MagicMock) else _state(value)
        for entity_id, value in (states or {}).items()
    }
    hass.states.get = lambda entity_id: table.get(entity_id)
    return hass


def _entry(**data: object) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_BUY_PRICE_SENSOR: BUY, CONF_SELL_PRICE_SENSOR: SELL, **data}
    entry.options = {}
    return entry


def _coordinator(payloads: dict[str, dict[str, list]] | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {"states": {}, "price_payloads": payloads or {}}
    return coordinator


def _manager(
    hass: MagicMock,
    entry: MagicMock,
    *,
    night: NightBuyWindowPlan | None = None,
    night_next: NightBuyWindowPlan | None = None,
    day: NightBuyWindowPlan | None = None,
    day_next: NightBuyWindowPlan | None = None,
) -> NightBuyWindowPlanManager:
    """A real plan manager fed in memory (prior art: test_night_buy_window_manager)."""
    manager = NightBuyWindowPlanManager(hass, entry)
    manager._current = night
    manager._upcoming = night_next
    manager._day_current = day
    manager._day_upcoming = day_next
    return manager


def _plan(start: datetime, end: datetime, price: float) -> NightBuyWindowPlan:
    return NightBuyWindowPlan(start=start, end=end, price=price)


def _hourly(day: int, prices_by_hour: dict[int, float]) -> list[dict[str, object]]:
    return [
        {"time": _dt(day, hour).isoformat(), "price": price}
        for hour, price in prices_by_hour.items()
    ]


def _resolver(
    *,
    hass: MagicMock | None = None,
    entry: MagicMock | None = None,
    coordinator: MagicMock | None = None,
    **plans: NightBuyWindowPlan | None,
) -> CoordinatorMarketWindowResolver:
    hass = hass or _hass()
    entry = entry or _entry()
    return CoordinatorMarketWindowResolver(
        hass, entry, coordinator or _coordinator(), _manager(hass, entry, **plans)
    )


class TestCoordinatorMarketWindowResolverDefaults:
    def test_without_plans_prices_or_entities_every_window_is_a_default(self) -> None:
        resolver = _resolver()

        assert resolver.windows(NOW) == default_market_windows(NOW)


class TestCoordinatorMarketWindowResolverHighTariff:
    def test_start_hour_comes_from_the_configured_entity(self) -> None:
        resolver = _resolver(
            hass=_hass({"sensor.tariff_start": "16"}),
            entry=_entry(**{CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.tariff_start"}),
        )

        assert resolver.windows(NOW).high_tariff_start == ResolvedHour(
            16, MarketWindowSource.CONFIG_ENTITY
        )

    def test_end_hour_comes_from_the_configured_entity(self) -> None:
        resolver = _resolver(
            hass=_hass({"sensor.tariff_end": "14:00"}),
            entry=_entry(**{CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end"}),
        )

        assert resolver.windows(NOW).high_tariff_end == ResolvedHour(
            14, MarketWindowSource.CONFIG_ENTITY
        )

    def test_a_start_hour_outside_0_to_23_falls_back_to_the_default(self) -> None:
        resolver = _resolver(
            hass=_hass({"sensor.tariff_start": "24"}),
            entry=_entry(**{CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.tariff_start"}),
        )

        assert resolver.windows(NOW).high_tariff_start == ResolvedHour(
            15, MarketWindowSource.DEFAULT
        )

    def test_an_end_hour_below_7_falls_back_to_the_default(self) -> None:
        resolver = _resolver(
            hass=_hass({"sensor.tariff_end": "6"}),
            entry=_entry(**{CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end"}),
        )

        assert resolver.windows(NOW).high_tariff_end == ResolvedHour(
            13, MarketWindowSource.DEFAULT
        )

    def test_an_end_hour_of_24_is_accepted(self) -> None:
        resolver = _resolver(
            hass=_hass({"sensor.tariff_end": "24"}),
            entry=_entry(**{CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end"}),
        )

        assert resolver.windows(NOW).high_tariff_end.hour == 24

    def test_an_unparseable_or_unavailable_state_falls_back_to_the_default(self) -> None:
        resolver = _resolver(
            hass=_hass({"sensor.tariff_start": "soon", "sensor.tariff_end": "unavailable"}),
            entry=_entry(
                **{
                    CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.tariff_start",
                    CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end",
                }
            ),
        )

        snapshot = resolver.windows(NOW)
        assert snapshot.high_tariff_start == ResolvedHour(15, MarketWindowSource.DEFAULT)
        assert snapshot.high_tariff_end == ResolvedHour(13, MarketWindowSource.DEFAULT)

    def test_default_day_buy_windows_end_at_the_configured_tariff_start(self) -> None:
        resolver = _resolver(
            hass=_hass({"sensor.tariff_start": "16"}),
            entry=_entry(**{CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.tariff_start"}),
        )

        snapshot = resolver.windows(NOW)
        assert (snapshot.day_buy.start, snapshot.day_buy.end) == (_dt(8, 14), _dt(8, 16))
        assert snapshot.day_buy.is_fallback is True
        assert (snapshot.day_buy_next.start, snapshot.day_buy_next.end) == (
            _dt(9, 14),
            _dt(9, 16),
        )


LAST_NIGHT = _plan(_dt(7, 22), _dt(8, 6), 0.40)
TONIGHT = _plan(_dt(8, 22), _dt(9, 6), 0.45)
TODAY_DAY = _plan(_dt(8, 13), _dt(8, 15), 0.60)
TOMORROW_DAY = _plan(_dt(9, 12), _dt(9, 14), 0.55)


def _plan_window(plan: NightBuyWindowPlan) -> ResolvedMarketWindow:
    return ResolvedMarketWindow(
        start=plan.start, end=plan.end, price=plan.price, source=MarketWindowSource.PLAN
    )


class TestCoordinatorMarketWindowResolverPlans:
    def test_night_buy_is_the_earliest_plan_not_ended_at_now(self) -> None:
        resolver = _resolver(night=LAST_NIGHT, night_next=TONIGHT)

        assert resolver.windows(NOW).night_buy == _plan_window(TONIGHT)

    def test_night_buy_completed_is_the_plan_keyed_by_todays_date(self) -> None:
        resolver = _resolver(night=LAST_NIGHT, night_next=TONIGHT)

        assert resolver.windows(NOW).night_buy_completed == _plan_window(LAST_NIGHT)

    def test_day_buy_is_the_plan_keyed_by_todays_local_date(self) -> None:
        resolver = _resolver(day=TODAY_DAY, day_next=TOMORROW_DAY)

        assert resolver.windows(NOW).day_buy == _plan_window(TODAY_DAY)

    def test_day_buy_next_is_the_plan_keyed_by_the_night_buy_plan_date(self) -> None:
        resolver = _resolver(night_next=TONIGHT, day=TODAY_DAY, day_next=TOMORROW_DAY)

        snapshot = resolver.windows(NOW)
        assert snapshot.day_buy_next == _plan_window(TOMORROW_DAY)
        assert snapshot.day_buy_for(_dt(9, 0).date()) is snapshot.day_buy_next
        assert snapshot.day_buy_for(_dt(8, 0).date()) is snapshot.day_buy

    def test_with_every_plan_ended_the_night_buy_is_tonights_default(self) -> None:
        resolver = _resolver(night=LAST_NIGHT)

        night = resolver.windows(_dt(8, 7)).night_buy
        assert (night.start, night.end, night.source, night.reason) == (
            _dt(8, 22),
            _dt(9, 6),
            MarketWindowSource.DEFAULT,
            "unavailable",
        )


def _buy_payload(**lists: list[dict[str, object]]) -> dict[str, dict[str, list]]:
    return {BUY: lists}


class TestCoordinatorMarketWindowResolverNightBuyAfter:
    def test_night_buy_after_is_built_from_the_combined_buy_prices(self) -> None:
        after_tonight = _hourly(9, {22: 0.50, 23: 0.50}) + _hourly(
            10, {0: 0.90, 1: 0.90, 2: 0.90, 3: 0.90, 4: 0.90, 5: 0.90}
        )
        resolver = _resolver(
            coordinator=_coordinator(_buy_payload(prices=after_tonight)),
            night_next=TONIGHT,
        )

        after = resolver.windows(NOW).night_buy_after
        assert (after.start, after.end, after.price, after.source) == (
            _dt(9, 22),
            _dt(10, 0),
            0.50,
            MarketWindowSource.PRICES,
        )

    def test_without_prices_night_buy_after_defaults_to_the_midnight_after_the_active_night(
        self,
    ) -> None:
        resolver = _resolver(night_next=TONIGHT)

        after = resolver.windows(_dt(9, 5)).night_buy_after
        assert (after.start, after.end, after.source) == (
            _dt(10, 0),
            _dt(10, 6),
            MarketWindowSource.DEFAULT,
        )


def _sell_payload(**lists: list[dict[str, object]]) -> dict[str, dict[str, list]]:
    return {SELL: lists}


MORNING_PRICES = {4: 0.80, 5: 0.90, 6: 1.00, 7: 1.20, 8: 1.10, 9: 0.95}
EVENING_PRICES = {16: 1.00, 17: 1.30, 18: 1.25, 19: 1.05, 20: 0.90, 21: 0.80}


class TestCoordinatorMarketWindowResolverSellWindows:
    def test_morning_sell_ranks_todays_sell_prices_between_4_and_10(self) -> None:
        resolver = _resolver(
            coordinator=_coordinator(_sell_payload(prices_today=_hourly(8, MORNING_PRICES)))
        )

        assert resolver.windows(NOW).morning_sell == RankedMarketWindow(
            primary=window(7, 8, price=1.20), secondary=window(8, 9, price=1.10)
        )

    def test_evening_sell_ranks_todays_sell_prices_between_16_and_22(self) -> None:
        resolver = _resolver(
            coordinator=_coordinator(_sell_payload(prices_today=_hourly(8, EVENING_PRICES)))
        )

        assert resolver.windows(NOW).evening_sell == RankedMarketWindow(
            primary=window(17, 18, price=1.30), secondary=window(18, 19, price=1.25)
        )

    def test_tomorrows_sell_windows_rank_only_tomorrows_prices(self) -> None:
        resolver = _resolver(
            coordinator=_coordinator(
                _sell_payload(
                    prices_today=_hourly(8, MORNING_PRICES) + _hourly(8, EVENING_PRICES),
                    prices_tomorrow=_hourly(9, {5: 1.50, 6: 1.40, 7: 0.50})
                    + _hourly(9, {18: 1.10, 19: 1.60, 20: 1.20}),
                )
            )
        )

        snapshot = resolver.windows(NOW)
        assert snapshot.morning_sell_tomorrow == RankedMarketWindow(
            primary=window(5, 6, price=1.50, next_day=True),
            secondary=window(6, 7, price=1.40, next_day=True),
        )
        assert snapshot.evening_sell_tomorrow == RankedMarketWindow(
            primary=window(19, 20, price=1.60, next_day=True),
            secondary=window(20, 21, price=1.20, next_day=True),
        )
        assert snapshot.morning_sell.primary == window(7, 8, price=1.20)

    def test_a_single_candidate_yields_a_default_primary_and_no_secondary(self) -> None:
        resolver = _resolver(
            coordinator=_coordinator(_sell_payload(prices_today=_hourly(8, {17: 1.30})))
        )

        ranked = resolver.windows(NOW).evening_sell
        assert ranked.primary == default_market_windows(NOW).evening_sell.primary
        assert ranked.secondary is None


def _consume_prices(day: int, cheap_start: int) -> list[dict[str, object]]:
    return _hourly(
        day, {hour: 0.5 if cheap_start <= hour < cheap_start + 2 else 1.0 for hour in range(8, 16)}
    )


class TestCoordinatorMarketWindowResolverConsume:
    def test_consume_is_the_cheapest_two_hours_of_todays_sell_prices(self) -> None:
        resolver = _resolver(
            coordinator=_coordinator(_sell_payload(prices_today=_consume_prices(8, 10)))
        )

        assert resolver.windows(NOW).consume == window(10, 12, price=0.5)

    def test_consume_tomorrow_uses_only_tomorrows_sell_prices(self) -> None:
        resolver = _resolver(
            coordinator=_coordinator(
                _sell_payload(
                    prices_today=_consume_prices(8, 10), prices_tomorrow=_consume_prices(9, 13)
                )
            )
        )

        snapshot = resolver.windows(NOW)
        assert snapshot.consume_tomorrow == window(13, 15, price=0.5, next_day=True)
        assert snapshot.consume == window(10, 12, price=0.5)


BUY_PRICES_TODAY = {6: 0.30, 7: 0.40, 8: 0.60, 9: 0.70, 10: 0.80, 11: 0.70, 12: 0.70, 13: 0.95, 14: 0.99}


class TestCoordinatorMarketWindowResolverBuyReference:
    def test_averages_buy_prices_from_the_hour_after_the_morning_sell_to_the_tariff_end(
        self,
    ) -> None:
        resolver = _resolver(
            coordinator=_coordinator(_buy_payload(prices_today=_hourly(8, BUY_PRICES_TODAY)))
        )

        reference = resolver.windows(NOW).morning_sell_buy_reference
        assert (reference.start, reference.end, reference.source) == (
            _dt(8, 8),
            _dt(8, 13),
            MarketWindowSource.PRICES,
        )
        assert reference.price == pytest.approx(0.70)

    def test_follows_the_resolved_morning_sell_hour_and_tariff_end(self) -> None:
        resolver = _resolver(
            hass=_hass({"sensor.tariff_end": "12"}),
            entry=_entry(**{CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end"}),
            coordinator=_coordinator(
                {
                    **_buy_payload(prices_today=_hourly(8, BUY_PRICES_TODAY)),
                    **_sell_payload(prices_today=_hourly(8, {7: 1.00, 8: 1.20, 9: 1.10})),
                }
            ),
        )

        reference = resolver.windows(NOW).morning_sell_buy_reference
        assert (reference.start, reference.end) == (_dt(8, 9), _dt(8, 12))
        assert reference.price == pytest.approx(0.75)

    def test_without_buy_prices_the_reference_defaults_to_the_same_span_without_a_price(
        self,
    ) -> None:
        resolver = _resolver(
            coordinator=_coordinator(_sell_payload(prices_today=_hourly(8, {7: 1.00, 8: 1.20, 9: 1.10})))
        )

        reference = resolver.windows(NOW).morning_sell_buy_reference
        assert (reference.start, reference.end, reference.price, reference.source) == (
            _dt(8, 9),
            _dt(8, 13),
            None,
            MarketWindowSource.DEFAULT,
        )
