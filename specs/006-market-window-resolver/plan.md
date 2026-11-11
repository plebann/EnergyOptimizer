# Implementation Plan: Market Window Resolver

**Branch**: `main` | **Date**: 2026-11-10 | **Origin**: `/supermatt:improve-architecture` session (candidate 1 of 2)

**Spec**: GitHub issue #69 (published from this plan; where they differ, the issue wins). **Tickets**: #70–#78, integration branch `feature/market-window-resolver`, frontier starts at #70. **Input**: this document was the spec's source. Vocabulary follows `CONTEXT.md` (Market Window, Resolved Market Window,
Market Window Source, Default Market Window, Morning Sell Buy Reference) and the codebase-design terms
(module, interface, seam, adapter, depth, locality).

## Problem

One concept, "which Market Window applies now, with its start, end and price", is encoded in six places:

| Place | What it knows |
|---|---|
| `calculations/price_windows.py` | pure algorithms computing windows from price lists (stays) |
| `night_buy_window_manager.py` | lifecycle of Night/Day Buy Window plans (stays, moves behind the seam) |
| `entities/sensors/pricing.py` | computes windows from coordinator payloads and publishes them as HA state `"HH:MM"` plus attributes `start_time`, `end_time`, `duration_hours`, `price`, `second_window_*` |
| `helpers.py` (~25 `resolve_*`, `get_internal_window_price`, `get_buy_plan`...) | reads the windows back from the integration's own sensors via entity-registry lookup by unique_id suffix, parses the strings, falls back to manager plans, legacy external entities and default hours |
| `service_handlers/charge_completion.py::resolve_charge_window` | a second parser of the same sensor attributes |
| strategies, scheduler, `common.resolve_arbitrage_margin_gate` | hold the unique_id suffixes (`night_buy_next_window`, `evening_sell_window`...) as literals |

Red flags: **Information Leakage** (sensor attribute format written in one module, parsed in two others),
**Back-door Leakage** (the suffix convention appears in 7 modules and in no interface), **Temporal Decomposition**
(compute → publish → read back), **Special-General Mixture** (each `resolve_*` branches on manager vs sensor vs
default), **Shallow Module** (`helpers.py`: 41 public functions, 1402 lines).

Symptoms: **change amplification** (commit `d97b9ce`, persisting buy windows, touched 15 production files including
all four strategies) and **unknown unknowns** (a strategy cannot tell whether a Night Buy Window came from the plan
manager or from a sensor attribute). Strategy tests mock `hass.states.get` per entity and the entity registry.

Design settled in the session:

| Decision | Choice |
|---|---|
| Scope | all windows the decision engine reads: Night/Day Buy (today, next), Morning/Evening Sell (Primary + Secondary), Consume, High-Tariff start/end, Morning Sell Buy Reference |
| Access | resolver injected into strategies; production instance from `hass.data`; in-memory double for tests |
| Unavailable window | behaviour-preserving: today's default hours, marked `source=DEFAULT` |
| Sensors | `pricing.py` window sensors become projections (format only) |
| Legacy external entities (`CONF_*_MAX_PRICE*`, `CONF_DAYTIME_MIN_PRICE*`) | kept as the lowest-priority Market Window Source |
| `NightBuyWindowPlanManager` | stays a separate class behind the seam; `hass.data["buy_window_manager"]` removed |
| Change detection | scheduler reacts to coordinator updates and asks the snapshot what changed; suffix subscriptions removed |
| Migration | single switchover in one PR, commits ordered as below |
| Glossary | code is right about the Morning Sell Buy Reference; `CONTEXT.md` corrected |

## Proposed Interface

New module `custom_components/energy_optimizer/market_windows.py` (~450 lines).

```python
class MarketWindowSource(StrEnum):
    PLAN = "plan"                    # NightBuyWindowPlanManager
    PRICES = "prices"                # coordinator price_payloads + price_windows.py
    CONFIG_ENTITY = "config_entity"  # CONF_HIGH_TARIFF_*_SENSOR
    LEGACY_ENTITY = "legacy_entity"  # CONF_*_MAX_PRICE*, CONF_DAYTIME_MIN_PRICE*
    DEFAULT = "default"              # Default Market Window

@dataclass(frozen=True, slots=True)
class ResolvedMarketWindow:
    start: datetime                  # tz-aware, HA local tz, never naive
    end: datetime                    # > start
    price: float | None              # None when the source carries no price
    source: MarketWindowSource
    reason: Literal["unavailable", "unreliable"] | None = None   # set iff source is DEFAULT

    hour: int                        # start.hour
    end_hour: int                    # end.hour
    duration_hours: float
    plan_date: date                  # end.date(); night plans are keyed by their morning
    is_fallback: bool                # source is DEFAULT
    def start_hour_or(self, default: int) -> int   # caller-specific default (two morning call sites)
    def contains(self, now: datetime) -> bool

@dataclass(frozen=True, slots=True)
class RankedMarketWindow:
    primary: ResolvedMarketWindow
    secondary: ResolvedMarketWindow | None       # Secondary Market Window has no default: None

@dataclass(frozen=True, slots=True)
class ResolvedHour:                              # High-Tariff boundaries are hours, not windows
    hour: int
    source: MarketWindowSource

@dataclass(frozen=True, slots=True)
class MarketWindows:
    """Every Market Window the decision engine reads, anchored at `now`."""
    now: datetime
    night_buy: ResolvedMarketWindow              # active plan: earliest not ended at now (today's "next")
    night_buy_completed: ResolvedMarketWindow    # plan keyed by today's date (night_buy_window sensor only)
    night_buy_after: ResolvedMarketWindow        # night after the active one, from the price payload; DEFAULT = next midnight
    day_buy: ResolvedMarketWindow                # plan keyed by today's local date
    day_buy_next: ResolvedMarketWindow           # plan keyed by night_buy.plan_date
    morning_sell: RankedMarketWindow
    morning_sell_tomorrow: RankedMarketWindow
    evening_sell: RankedMarketWindow
    evening_sell_tomorrow: RankedMarketWindow
    consume: ResolvedMarketWindow
    consume_tomorrow: ResolvedMarketWindow
    morning_sell_buy_reference: ResolvedMarketWindow   # average buy price, sell hour + 1 → tariff end
    high_tariff_start: ResolvedHour
    high_tariff_end: ResolvedHour

    def day_buy_for(self, plan_date: date) -> ResolvedMarketWindow | None
    def changed_from(self, previous: MarketWindows | None) -> frozenset[str]
        # field names whose (start, end, price, source) differ; value equality, not identity

class MarketWindowResolver(Protocol):
    def windows(self, now: datetime | None = None) -> MarketWindows: ...

def market_window_resolver(hass: HomeAssistant, entry_id: str) -> MarketWindowResolver   # the one hass.data lookup
```

Invariants a caller must know:

- `windows()` is synchronous, side-effect free, and never raises. Call it once at the start of a decision run and
  read the snapshot thereafter; the snapshot cannot change under the caller, even across `await`.
- Every field is populated. A window that cannot be resolved is `DEFAULT` with `start`/`end` synthesised on the anchor
  day at today's default hours: Night Buy 22→06 rolled forward when `end <= now` (the `resolve_charge_window` rule),
  Day Buy `(high_tariff_start − 2) → high_tariff_start`, Morning Sell 07, Evening Sell 17, Consume 12:00,
  High-Tariff 15 / 13 with today's range checks. Unavailable and Unreliable both collapse to `DEFAULT`; `reason` differs.
- Datetimes are the truth; hours are projections. Resolution priority per field: PLAN → PRICES → LEGACY_ENTITY →
  DEFAULT; tariff: CONFIG_ENTITY → DEFAULT.
- `secondary` is the only `None`. `price is None` means the Arbitrage Buy Reference is unavailable and the margin gate
  fails closed.

Usage:

```python
# BaseChargeStrategy.run / BaseSellStrategy.run, first statement
self.windows = self._resolver.windows()

# MorningChargeStrategy._resolve_forecast_params
night = self.windows.night_buy
end_datetime = None if night.is_fallback else night.end
day_buy = self.windows.day_buy_for(night.plan_date) or self.windows.day_buy
return night.end_hour, day_buy.start_hour_or(self.windows.high_tariff_end.hour), kwargs

# EveningSellStrategy
ranked = self.windows.evening_sell
current = ranked.secondary if (ranked.secondary and not self._is_primary) else ranked.primary
ok, details = resolve_arbitrage_margin_gate(
    sell_price=current.price, min_arbitrage_price=..., buy_reference=self.windows.night_buy)

# ActionScheduler._handle_coordinator_update
new = self._resolver.windows()
for name in new.changed_from(self._windows):
    for reschedule in self._RESCHEDULE[name]:
        reschedule()
self._windows = new

# EveningSellWindowSensor (projection)
r = self._resolver.windows().evening_sell
self._attr_available = not r.primary.is_fallback
self._attr_native_value = f"{r.primary.start:%H:%M}"

# test
resolver = StaticMarketWindowResolver(market_windows(
    evening_sell=RankedMarketWindow(primary=window(17, 18, price=1.20), secondary=window(19, 20, price=1.05)),
    night_buy=window(22, 6, price=0.45, next_day=True)))
strategy = EveningSellStrategy(hass, entry_id="e1", margin=None, resolver=resolver)
```

Hidden behind the seam: manager `get_plan`/`get_active_plan` and slot selection; `coordinator.data["price_payloads"]`
shape and which price entity feeds which window; the calls into `build_best_buy_window_result`,
`build_ranked_sell_window_result`, `build_consume_window_result`, `build_average_buy_price_result`,
`build_night_buy_window_plan`; legacy entity ids and `"HH:MM"` parsing; tariff range checks; every default hour;
the unique_id suffixes and the `start_time`/`end_time`/`duration_hours` attribute names (written once by sensors,
parsed nowhere); which warnings to log.

Internal structure of the production adapter (not in the interface): one ordered Market Window Source chain per
snapshot field, so adding a source is a chain position and adding a window is a field plus a chain.

## Cohesion Statement

- **Single responsibility**: answers which Resolved Market Window applies at a given moment.
- **Owns**: source priority, slot selection (today / active / next), parsing of entity states, default hours,
  fallback synthesis, change detection between two snapshots.
- **Stays out**:
  - computing windows from price lists: `calculations/price_windows.py`, `night_buy_window.py` (pure, already tested);
  - plan lifecycle, persistence, rotation and Morning Charge start claim: `NightBuyWindowPlanManager` and
    `EnergyOptimizerCoordinator`;
  - decisions and inverter writes: strategies and `controllers/inverter.py`;
  - `resolve_prog4_start_time`: inverter program control, not a Market Window;
  - Sell Restore payloads (candidate 2 of the architecture review).

## Dependency Strategy

Category: **in-process**. The adapter reads `coordinator.data` (one dict reference taken once per `windows()` call,
replaced atomically per refresh), the manager's in-memory plans, and `hass.states` for tariff and legacy entities.
The HA `Store` behind the manager is local-substitutable and not part of this interface.

Two adapters at one seam:

- `CoordinatorMarketWindowResolver(hass, entry, coordinator, manager)` (production), created in
  `__init__.async_setup_entry` after `coordinator.async_config_entry_first_refresh()`, stored as
  `hass.data[DOMAIN][entry_id]["market_windows"]`. The `"buy_window_manager"` key is removed; the resolver is the
  manager's only reader besides the coordinator.
- `StaticMarketWindowResolver(windows)` (tests), ~20 lines in the same module, returning a fixed snapshot.

Strategy constructors gain `resolver: MarketWindowResolver | None = None`; `async_run_*` passes
`market_window_resolver(hass, entry.entry_id)`. Module-level helpers (`_calculate_morning_arbitrage_kwh`,
`resolve_arbitrage_margin_gate`, `solar_charge_block`, `program4_solar_reset`) receive `windows: MarketWindows` or the
single value they need instead of `hass, entry_id`. `sensor.py` passes the resolver to window sensors.

## Testing Strategy

New `tests/test_market_windows.py` at the interface (production adapter with a stub coordinator payload, a real
`NightBuyWindowPlanManager` fed in memory, and `hass.states` stubs):

- each field resolves from each source in priority order; legacy entity only when prices are absent;
- DEFAULT synthesis: night roll-forward when `end <= now`, day from tariff hours, tariff range checks;
- `secondary is None` for DEFAULT and single-candidate rankings;
- `day_buy_for(plan_date)`, `night_buy_after` from payload and its midnight fallback;
- `morning_sell_buy_reference` averages sell hour + 1 → tariff end;
- `changed_from` reports exactly the fields whose start/end/price/source changed; snapshots are tz-aware local;
- `StaticMarketWindowResolver` returns the given snapshot unchanged.

Old tests to remove (own commit, after the new ones are green): window cases in `tests/test_helpers.py`
(`resolve_*`, `get_internal_window_price`, `get_buy_plan`, `get_active_night_plan`), window computation cases in
`tests/test_pricing_sensors.py` (formatting cases stay and switch to a static resolver), `resolve_charge_window` cases
in `tests/test_charge_completion.py`, the registry/state mocks for windows in `test_decision_engine_morning.py`,
`test_decision_engine_morning_sell.py`, `test_decision_engine_evening_sell.py`, `test_afternoon_charge.py`,
`test_morning_arbitrage.py`, `test_solar_charge_block.py`, `test_program4_solar_reset.py`, the suffix subscription
cases in `test_scheduled_actions.py`, and `tests/test_buy_window_plan_lifecycle.py` cases that go through helpers.

Test environment: nothing new; the stub coordinator is a `MagicMock` with a `data` dict.

## Migration Strategy

Single switchover in one PR (decision Q8), with the commits below in order so each is bisectable and the suite is
green after every commit. Two sources of truth coexist only between commits 2 and 8 inside the PR.

Call-site mapping (every production use of the old functions):

| Old | New |
|---|---|
| `resolve_night_buy_window_tomorrow_{start_hour,end_hour,start_datetime,end_datetime,duration_hours}` | `w.night_buy.{hour,end_hour,start,end,duration_hours}` |
| `resolve_night_buy_window_{start_hour,end_hour,duration_hours}` | `w.night_buy_completed.*` |
| `resolve_day_buy_window_{start_hour,end_hour,duration_hours}` | `w.day_buy.{hour,end_hour,duration_hours}`; morning keeps its default via `start_hour_or(w.high_tariff_end.hour)` |
| `resolve_day_buy_window_tomorrow_start_hour(for_date)` | `w.day_buy_for(plan_date)` or `w.day_buy_next` |
| `resolve_morning_max_price_hour`, `resolve_morning_sell_tomorrow_hour` | `w.morning_sell.primary.hour`, `w.morning_sell_tomorrow.primary.hour` |
| `resolve_evening_max_price_hour`, `resolve_evening_second_max_price_hour` | `w.evening_sell.primary.hour`, `w.evening_sell.secondary` |
| `resolve_daytime_min_price_time` | `w.consume.start.time()` |
| `resolve_tariff_start_hour`, `resolve_tariff_end_hour` | `w.high_tariff_start.hour`, `w.high_tariff_end.hour` |
| `get_internal_window_price(suffix, attribute)` | `.price` of the matching field (`second_window_price` → `evening_sell.secondary.price`) |
| `resolve_charge_window("morning" / "afternoon")` | `(w.night_buy.start, w.night_buy.end)` / `(w.day_buy.start, w.day_buy.end)` |
| `_resolve_next_night_start` | `w.night_buy_after.start` |
| `MorningSellBuyReferenceSensor._get_result` | `w.morning_sell_buy_reference` |
| `resolve_arbitrage_margin_gate(hass, entry_id, sell_price, min, suffix, name, fallback)` | `resolve_arbitrage_margin_gate(sell_price, min_arbitrage_price, buy_reference)` |
| `arbitrage_buy_reference_suffix` / `_name` properties | `arbitrage_buy_reference -> ResolvedMarketWindow` |
| scheduler suffix subscriptions (6) and `get_internal_sensor_entity_id` | `_handle_coordinator_update` + `changed_from` + `_RESCHEDULE` map; tariff entity subscription stays |

Behaviour-preserving constraints to watch: Afternoon Charge default `(tariff_start − 2)` vs Morning Charge default
`tariff_end` for the Day Buy start; `_resolve_charge_time_hours` falls back to 2.0 h when `night_buy.is_fallback`;
sensors keep writing `start_time`/`end_time`/`duration_hours`/`plan_date` attributes for external automations.

## Implementation Steps

1. **Types, defaults, static adapter** (new `market_windows.py`, `tests/test_market_windows.py`): dataclasses,
   `MarketWindowResolver` protocol, defaults table, `StaticMarketWindowResolver`, `changed_from`, `day_buy_for`.
   Tests first. No callers yet. ~150 lines + ~150 test lines.
2. **Production adapter**: `CoordinatorMarketWindowResolver` with per-field source chains; tests against stub
   coordinator data and an in-memory manager. Create it in `__init__.async_setup_entry`, store under
   `"market_windows"`, add `market_window_resolver()` accessor. ~300 lines + ~250 test lines.
3. **Decision engine common + bases**: `BaseChargeStrategy`/`BaseSellStrategy` accept `resolver`, take the snapshot at
   run start; `resolve_arbitrage_margin_gate` new signature; `arbitrage_buy_reference` property. Files:
   `decision_engine/common.py`, `charge_base.py`, `sell_base.py`.
4. **Strategies**: migrate `morning_charge.py`, `afternoon_charge.py`, `evening_sell.py`, `morning_sell.py`,
   `evening_behavior.py`, `solar_charge_block.py`, `program4_solar_reset.py`, `daytime_min_price_restore.py` per the
   mapping table; `async_run_*` pass the resolver. Rewrite the window setup in their tests to
   `StaticMarketWindowResolver`. One commit per strategy.
5. **Charge completion**: delete `resolve_charge_window`; `_resolve_completion_window` in both charge strategies reads
   the snapshot. Update `tests/test_charge_completion.py`.
6. **Scheduler**: remove the six suffix subscriptions and `get_internal_sensor_entity_id` use; add `_RESCHEDULE` map and
   snapshot-based `_handle_coordinator_update`; `_schedule_*` and `_build_scheduled_actions_snapshot` read
   `self._windows` and report `source`. Update `tests/test_scheduled_actions.py`.
7. **Sensors**: `pricing.py` window sensors and `MorningSellBuyReferenceSensor` become projections taking the resolver
   from `sensor.py`; drop their `price_windows` imports and `helpers` calls. Update `tests/test_pricing_sensors.py`.
8. **Delete the old module surface**: remove the `resolve_*` window family, `get_internal_window_price`,
   `get_internal_sensor_entity_id`, `get_buy_plan`, `get_active_night_plan`, `get_day_plan_for_active_night`,
   `_buy_window_manager` from `helpers.py`; remove `hass.data["buy_window_manager"]` from `coordinator.py`;
   remove `get_buy_price_payload` if the adapter is its last caller. Separate commit: delete the old tests listed above.
9. **Docs**: note the module in `docs/EnergyOptimizer_Architecture.md` (data layer) and `CHANGELOG.md`.

Estimated scope: ~450 new production lines, ~1100 deleted; 13 production files, 10 test files; one PR, ~12 commits.
Verification per step: full `pytest` green; after step 8, `grep -rn "unique_id_suffix\|night_buy_next_window"
custom_components` returns only `__init__.py` (entity-registry migration) and `pricing.py` (`_attr_unique_id`).
