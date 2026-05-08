# Research: Okno Najniższej Ceny Sprzedaży w Środku Dnia

## Decision: Use the existing hourly `sell-price sensor` data exposed through shared integration state as the authoritative input for the window calculation, and expand each hour into four quarter-hours during selection.

**Rationale**
- The clarified input for this feature is hourly sell-price data, while the business rule still defines the output window length in quarter-hours.
- Expanding each hourly entry into 4 consecutive quarter-hours with the same price preserves the requested quarter-hour window semantics without requiring a different external source.
- Reusing the configured hourly `sell-price sensor` avoids new config-flow inputs and keeps the feature aligned with the current HA-first model where Energy Optimizer derives outputs from existing Home Assistant entities.
- Reading the payload through shared integration state aligns the feature with the project constitution's preference for centralized data access instead of direct reads from entity code.
- The implementation remains semantically based on sell pricing and must remain fully isolated from the configured buy-price sensor.

**Alternatives considered**
- Use `buy_price_sensor` as the only input: rejected because the feature is explicitly scoped to sell-price data.
- Require a new external precomputed window sensor in config flow: rejected because it duplicates setup burden and moves core optimizer logic outside the integration.
- Blend buy and sell price sources: rejected because the specification explicitly scopes the feature to sell pricing only.

## Decision: Keep the hourly-to-quarter-hour expansion and cheapest-window selection in a pure calculation module, and keep the entity layer thin.

**Rationale**
- The constitution requires clear module separation between calculations and Home Assistant entity wiring.
- A pure function that parses current-day hourly price points, expands them to quarter-hours, filters 08:00-16:00, enforces 8 contiguous quarter-hours, and breaks ties by earliest start is easy to unit-test deterministically.
- A thin entity can focus on formatting the chosen window as `HH:MM-HH:MM`, publishing `unavailable` on insufficient data, and exposing stable HA metadata.

**Alternatives considered**
- Put the full algorithm into the sensor `native_value` property: rejected because it mixes business rules with entity concerns and weakens test isolation.
- Extend `helpers.py` with all new logic: rejected because this feature is a reusable calculation concern rather than a generic HA helper.
- Store the computed window in scheduler state: rejected because the spec defines a derived sensor, not a scheduler-owned artifact.

## Decision: Publish a dedicated translation-backed text sensor for the midday sell window.

**Rationale**
- The specification requires a separate text sensor rather than a hidden attribute on an existing entity.
- A first-class sensor is directly usable in dashboards and automations and fits the repo's current pattern of small, focused entities.
- Home Assistant naming rules in this repo require `_attr_has_entity_name = True`, translation-backed naming, and stable unique IDs tied to the config entry.
- Setting the state to `unavailable` on insufficient data is explicit, testable, and safer than keeping a stale value.

**Alternatives considered**
- Add the window as an attribute on `SellPriceSensor`: rejected because it would not satisfy the separate-sensor requirement and would be harder to automate against.
- Persist the last valid text value through restarts: rejected because the feature is current-day derived state and stale restoration could mislead users after price data changes.
- Expose the window through a service response only: rejected because the spec requires a sensor entity.

## Decision: Reuse the current refresh/listener path and extend shared integration state with the hourly sell-price payload.

**Rationale**
- The sensor platform already listens for buy/sell price entity changes and requests coordinator refreshes, so the feature can reuse the same update rhythm.
- The current coordinator caches numeric state values only, while this feature needs raw hourly attributes that will be expanded into quarter-hours.
- Extending shared state with the hourly `sell-price sensor` payload keeps the entity layer thin and matches the repo's centralized-read preference better than direct entity-state access inside the result sensor.

**Alternatives considered**
- Poll the price-series source independently in a new background loop: rejected because the integration already has coordinator and listener infrastructure.
- Recompute only on hourly scheduler ticks: rejected because the feature should update when price data changes, not only on time-based events.
- Read directly from the Home Assistant state object inside the result sensor: rejected because shared state is the better fit for the architecture rules of this repository.
- Ignore attribute changes and watch only scalar states: rejected because the cheapest window is derived from the attribute payload, not the current scalar state.

## Decision: Validate the feature with both pure algorithm tests and entity-level sensor tests.

**Rationale**
- The constitution requires deterministic coverage for calculation-heavy logic.
- The repo already has lightweight sensor tests in `tests/test_pricing_sensors.py` and time-window-oriented tests in dedicated test files, so extending that split keeps the suite readable.
- The highest-risk failures are algorithmic: hourly-to-quarter-hour expansion, incomplete data handling, local-day scoping, tie-breaking, and ensuring buy-price changes never affect the result.

**Alternatives considered**
- Rely on manual Home Assistant verification only: rejected because time-window selection is easy to regress and hard to eyeball across edge cases.
- Cover everything only with entity setup tests: rejected because parsing and tie-breaking are better exercised as pure unit tests.
- Skip timezone/day-boundary tests: rejected because the feature is explicitly scoped to the current local day.
