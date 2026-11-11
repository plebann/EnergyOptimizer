"""Tests for the Market Window Resolver vocabulary and the static adapter."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_optimizer.market_windows import (
    MarketWindows,
    MarketWindowSource,
    RankedMarketWindow,
    ResolvedHour,
    ResolvedMarketWindow,
)

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


def _ranked(
    start: datetime, end: datetime, *, price: float = 1.0
) -> RankedMarketWindow:
    return RankedMarketWindow(primary=_window(start, end, price=price), secondary=None)


def _snapshot(**overrides: object) -> MarketWindows:
    """Build a fully resolved snapshot anchored at 2026-05-08 12:00 local."""
    fields: dict[str, object] = {
        "now": _dt(8, 12),
        "night_buy": _window(_dt(8, 22), _dt(9, 6), price=0.45),
        "night_buy_completed": _window(_dt(7, 22), _dt(8, 6), price=0.40),
        "night_buy_after": _window(_dt(9, 22), _dt(10, 6), price=0.50),
        "day_buy": _window(_dt(8, 13), _dt(8, 15), price=0.60),
        "day_buy_next": _window(_dt(9, 12), _dt(9, 14), price=0.55),
        "morning_sell": _ranked(_dt(8, 7), _dt(8, 8), price=1.20),
        "morning_sell_tomorrow": _ranked(_dt(9, 7), _dt(9, 8), price=1.10),
        "evening_sell": _ranked(_dt(8, 17), _dt(8, 18), price=1.30),
        "evening_sell_tomorrow": _ranked(_dt(9, 18), _dt(9, 19), price=1.25),
        "consume": _window(_dt(8, 12), _dt(8, 14), price=0.10),
        "consume_tomorrow": _window(_dt(9, 11), _dt(9, 13), price=0.12),
        "morning_sell_buy_reference": _window(_dt(8, 8), _dt(8, 13), price=0.70),
        "high_tariff_start": ResolvedHour(15, MarketWindowSource.CONFIG_ENTITY),
        "high_tariff_end": ResolvedHour(13, MarketWindowSource.CONFIG_ENTITY),
    }
    fields.update(overrides)
    return MarketWindows(**fields)  # type: ignore[arg-type]


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


class TestResolvedMarketWindow:
    def test_hours_are_derived_from_a_window_spanning_midnight(self) -> None:
        night = _window(_dt(8, 22), _dt(9, 6))

        assert (night.hour, night.end_hour) == (22, 6)
        assert night.duration_hours == 8.0
        assert night.plan_date == _dt(9, 6).date()

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

    def test_end_must_be_after_start(self) -> None:
        with pytest.raises(ValueError):
            _window(_dt(8, 15), _dt(8, 15))

    def test_naive_datetimes_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            _window(datetime(2026, 5, 8, 13), datetime(2026, 5, 8, 15))

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
        with pytest.raises(ValueError):
            _window(_dt(8, 13), _dt(8, 15), source=source, reason=reason)


class TestMarketWindows:
    def test_changed_from_nothing_reports_every_window_field(self) -> None:
        assert _snapshot().changed_from(None) == ALL_WINDOW_FIELDS

    def test_changed_from_reports_only_the_field_whose_price_changed(self) -> None:
        previous = _snapshot()
        current = _snapshot(night_buy=_window(_dt(8, 22), _dt(9, 6), price=0.46))

        assert current.changed_from(previous) == {"night_buy"}

    def test_a_later_now_alone_changes_nothing(self) -> None:
        previous = _snapshot()
        current = _snapshot(now=_dt(8, 12, 30))

        assert current.changed_from(previous) == frozenset()

    def test_a_new_secondary_sell_window_changes_the_ranked_field(self) -> None:
        previous = _snapshot()
        current = _snapshot(
            evening_sell=RankedMarketWindow(
                primary=_window(_dt(8, 17), _dt(8, 18), price=1.30),
                secondary=_window(_dt(8, 19), _dt(8, 20), price=1.05),
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
