# Market Window Module Design Decisions

## Sources

- [Current Market Window Behavior And Compatibility Rules](002-current-window-behavior-and-compatibility-rules.md)
- `CONTEXT.md`
- `custom_components/energy_optimizer/calculations/price_windows.py`
- `custom_components/energy_optimizer/entities/sensors/pricing.py`
- `custom_components/energy_optimizer/helpers.py`
- `custom_components/energy_optimizer/scheduler/action_scheduler.py`
- `custom_components/energy_optimizer/decision_engine/`

## Result Shape Decision

The deepened Market Window module should preserve distinct category-specific result shapes inside the module and expose a smaller caller-facing interface at the seam.

A single universal result shape would either lose domain meaning or grow many optional fields. Buy Windows need two-hour average-price output and negative-price metadata. Ranked Sell Windows need primary and secondary one-hour outputs plus a secondary-gap attribute. Midday Avoidance Windows can be variable length, can represent zero-price expansion, and have today-only active-state publication. High-Tariff Windows resolve hours rather than price-selected payload windows.

The public interface should expose resolved domain operations rather than raw calculation dataclasses. Internally, the module can keep or evolve `BuyWindowResult`, `RankedSellWindowResult`, and `ConsumeWindowResult` while callers receive the minimum shape they need for their use case: sensor state and attributes, schedule timing context, or decision-engine numeric/time values.

This decision preserves depth: callers learn one Market Window module interface while the module owns parsing, ranking, fallback, default, warning, and publication compatibility rules.

## External Seam Decision

The external seam should live in a new `custom_components/energy_optimizer/market_windows/` package. Pricing sensors, Scheduler, and Decision Engine modules should cross that seam for Market Window behavior. Current-price controls that are not Market Window behavior, especially Export Block Control's direct current sell/legacy price logic, should stay outside the seam.

The Market Window module should own:

- coordinator price-payload parsing for Buy Windows, Ranked Sell Windows, and Midday Avoidance Windows;
- category-specific calculation and tie-breaker rules;
- integration-owned internal sensor preference and configured fallback entity reads;
- default hour/time resolution and allowed ranges;
- unavailable/unreliable result semantics;
- conversion from category-specific domain results into the small caller-facing values used by sensors, Scheduler, and Decision Engine modules.

The initial external interface should be use-case oriented instead of exposing low-level helpers. Candidate operations are:

- resolve a Buy Window for a configured source, day, and buy-window category;
- resolve a Ranked Sell Window for a configured source, day, and sell-window category;
- resolve a Midday Avoidance Window for a configured source and day;
- resolve high-tariff start/end windows;
- read a Market Window price or time value through the internal-sensor-then-fallback policy for Scheduler and Decision Engine callers.

Existing public decision-engine entry points such as `async_run_*()` remain unchanged. Existing helper functions can remain as temporary compatibility wrappers while their implementation moves behind the new seam.

## Adapter And Fallback Policy

Adapters should be internal to the Market Window module. They are implementation detail, not caller interface.

Use these adapters behind the seam:

- `CoordinatorPricePayloadSource`: reads `coordinator.data["price_payloads"]` for configured buy or sell price entities and returns raw day-scoped payloads.
- `InternalEntityWindowSource`: resolves integration-owned internal sensors by config entry and unique-id suffix.
- `ConfiguredEntityWindowSource`: reads user-configured fallback entities and selected attributes from Home Assistant state.
- `DefaultWindowSource`: supplies documented default hours/times when configured sources are missing or invalid where current behavior already has a default.
- `WindowPublisher`: formats resolved results into the exact native values and attributes currently exposed by pricing sensors.

Fallback order must preserve current behavior:

- Price-window sensors use coordinator payloads only for their configured buy or sell source; they do not fall back to helper entities.
- Scheduler and Decision Engine reads prefer integration-owned internal sensors when `entry_id` is available, then configured fallback entities, then category-specific defaults only where current helpers already default.
- Attribute reads prefer the requested attribute when it is present and usable. If the requested attribute is present but unavailable, return no value rather than falling back to entity state.
- Missing configuration, missing state, unavailable state/attribute, invalid values, and out-of-range values should remain distinguishable in logs, but most callers continue to receive `None` or the existing default.
- Duplicate full-hour source entries remain Unreliable Market Window input for Buy and Ranked Sell calculations and make the affected result unavailable.
- Zero and negative prices remain valid wherever the existing calculation rules allow them.

No adapter should be added for current-price export/off-grid control until a later map explicitly broadens Market Window scope.

## Migration Strategy

Migrate in thin, reversible steps. The goal is to move behavior behind the new seam without changing Home Assistant entity ids, translation keys, states, attributes, service behavior, or public decision-engine entry points.

1. Add the `market_windows` package and a focused test surface around the new seam using existing compatibility cases from price-window, pricing-sensor, helper, and scheduled-action tests.
2. Move or wrap pure calculation behavior first, keeping the existing `custom_components.energy_optimizer.calculations.price_windows` functions as compatibility exports until callers are migrated.
3. Move pricing-sensor coordinator payload resolution into the Market Window module, while preserving current sensor classes, unique ids, translation keys, availability behavior, native values, and attributes.
4. Move helper fallback resolution behind the Market Window module. Keep existing helper function names as temporary wrappers so Scheduler and Decision Engine call sites can migrate gradually.
5. Migrate Scheduler timing and scheduled-action snapshot construction to use Market Window resolution values, preserving listener keys, labels, source strings, local-time formatting, derived restore behavior, and event-driven entries.
6. Migrate Decision Engine modules to read Market Window price/time context through the module, preserving `async_run_*()` entry points and current missing-value behavior.
7. Remove compatibility wrappers only after all call sites and tests prove they are no longer needed.

## Test Strategy

Use existing tests as compatibility contracts and add seam-level tests before moving callers.

Focused tests to keep green throughout migration:

- `tests/test_price_windows.py`
- `tests/test_pricing_sensors.py`
- `tests/test_helpers.py`
- `tests/test_scheduled_actions.py`
- `tests/test_solar_charge_block.py`
- `tests/test_export_block_control.py`

New Market Window module tests should cover:

- day isolation and range filtering;
- duplicate and invalid source entries;
- Buy Window and Ranked Sell Window tie-breakers;
- zero and negative price semantics;
- Midday Avoidance zero-price expansion and contiguous-window fallback;
- internal-sensor preference over configured fallbacks;
- attribute-unavailable behavior;
- default high-tariff and Market Window hour/time behavior;
- publication formatting for sensor state and attributes;
- Scheduler timing contexts and derived restore times.

Run the full suite once at the end of each implementation slice. The current known unrelated full-suite risk is the morning-arbitrage `entry_id` test failure; do not fold that repair into the Market Window migration unless a later ticket explicitly asks for it.