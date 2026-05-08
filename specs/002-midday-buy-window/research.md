# Research: Okno Najniższej Ceny Zakupu w Środku Dnia

## Decision: Use the existing quarter-hour price-series source already configured in the integration as the authoritative input for the window calculation.

**Rationale**
- Repo documentation already describes a price sensor with a `prices` attribute containing quarter-hour entries (`dtime`, `period`, `rce_pln`, `business_date`), which is the data shape needed to scan an 8-quarter window.
- The existing `buy_price_sensor` entity in the integration currently mirrors a scalar current value, so it is not sufficient by itself to derive a two-hour window without adding another external dependency.
- Reusing the configured price-series source avoids new config-flow inputs and keeps the feature aligned with the current HA-first model where Energy Optimizer derives outputs from existing Home Assistant entities.
- The implementation still remains semantically based on purchase pricing and must remain fully isolated from the configured sell-price sensor.

**Alternatives considered**
- Use `buy_price_sensor` as the only input: rejected because the current implementation mirrors only the current scalar buy price.
- Require a new external precomputed window sensor in config flow: rejected because it duplicates setup burden and moves core optimizer logic outside the integration.
- Blend buy and sell price sources: rejected because the specification explicitly scopes the feature to purchase pricing only.

## Decision: Keep the quarter-hour parsing and cheapest-window selection in a pure calculation module, and keep the entity layer thin.

**Rationale**
- The constitution requires clear module separation between calculations and Home Assistant entity wiring.
- A pure function that parses current-day price points, filters 08:00-16:00, enforces 8 contiguous quarter-hours, and breaks ties by earliest start is easy to unit-test deterministically.
- A thin entity can focus on formatting the chosen window as `HH:MM-HH:MM`, publishing `unavailable` on insufficient data, and exposing stable HA metadata.

**Alternatives considered**
- Put the full algorithm into the sensor `native_value` property: rejected because it mixes business rules with entity concerns and weakens test isolation.
- Extend `helpers.py` with all new logic: rejected because this feature is a reusable calculation concern rather than a generic HA helper.
- Store the computed window in scheduler state: rejected because the spec defines a derived sensor, not a scheduler-owned artifact.

## Decision: Publish a dedicated translation-backed text sensor for the midday buy window.

**Rationale**
- The specification requires a separate text sensor rather than a hidden attribute on an existing entity.
- A first-class sensor is directly usable in dashboards and automations and fits the repo's current pattern of small, focused entities.
- Home Assistant naming rules in this repo require `_attr_has_entity_name = True`, translation-backed naming, and stable unique IDs tied to the config entry.
- Setting the state to `unavailable` on insufficient data is explicit, testable, and safer than keeping a stale value.

**Alternatives considered**
- Add the window as an attribute on `BuyPriceSensor`: rejected because it would not satisfy the separate-sensor requirement and would be harder to automate against.
- Persist the last valid text value through restarts: rejected because the feature is current-day derived state and stale restoration could mislead users after price data changes.
- Expose the window through a service response only: rejected because the spec requires a sensor entity.

## Decision: Reuse the current refresh/listener path, but add attribute-aware access for the price-series payload.

**Rationale**
- The sensor platform already listens for buy/sell price entity changes and requests coordinator refreshes, so the feature can reuse the same update rhythm.
- The current coordinator caches numeric state values only, while this feature needs raw quarter-hour attributes. The implementation therefore needs one explicit design choice: either extend coordinator data with a raw price snapshot or let the calculation module read the current HA state object directly while still relying on existing refresh triggers.
- Both approaches fit the HA async model, but the plan should preserve centralized state handling where practical.

**Alternatives considered**
- Poll the price-series source independently in a new background loop: rejected because the integration already has coordinator and listener infrastructure.
- Recompute only on hourly scheduler ticks: rejected because the feature should update when price data changes, not only on time-based events.
- Ignore attribute changes and watch only scalar states: rejected because the cheapest window is derived from the attribute payload, not the current scalar state.

## Decision: Validate the feature with both pure algorithm tests and entity-level sensor tests.

**Rationale**
- The constitution requires deterministic coverage for calculation-heavy logic.
- The repo already has lightweight sensor tests in `tests/test_pricing_sensors.py` and time-window-oriented tests in dedicated test files, so extending that split keeps the suite readable.
- The highest-risk failures are algorithmic: incomplete data handling, local-day scoping, tie-breaking, and ensuring sell-price changes never affect the result.

**Alternatives considered**
- Rely on manual Home Assistant verification only: rejected because time-window selection is easy to regress and hard to eyeball across edge cases.
- Cover everything only with entity setup tests: rejected because parsing and tie-breaking are better exercised as pure unit tests.
- Skip timezone/day-boundary tests: rejected because the feature is explicitly scoped to the current local day.
