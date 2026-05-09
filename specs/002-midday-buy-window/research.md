# Research: Rozszerzenie Sensorów Okna Najniższej Ceny Sprzedaży

## Decision: Reuse shared integration state as the authoritative source for both day-scoped price payloads, with `prices_today` feeding the current-day sensor and `prices_tomorrow` feeding the tomorrow sensor.

**Rationale**
- The updated specification explicitly requires two analogous sensors that differ only by day scope and payload source.
- Reading both payloads from coordinator-owned shared state keeps entity code thin and aligned with the constitution's requirement for centralized reads.
- This approach preserves the existing Home Assistant flow where Energy Optimizer derives outputs from already-configured HA entities rather than introducing new configuration or direct state scraping in entities.
- Isolating each sensor to its own payload prevents cross-day leakage and makes update behavior deterministic.

**Alternatives considered**
- Read source entity attributes directly inside each derived sensor: rejected because it duplicates access logic and weakens the shared-state architecture.
- Drive both sensors from `prices_today` with date offsets: rejected because the specification explicitly names `prices_tomorrow` for the tomorrow sensor.
- Introduce a new config-flow source just for tomorrow data: rejected because it adds configuration burden without domain value.

## Decision: Keep one shared pure calculation path that accepts day-scoped hourly sell-price data, expands each hour into four quarter-hours, and returns both the chosen window and its average price.

**Rationale**
- The business rules for both sensors are identical except for the payload key and target day, so one reusable algorithm minimizes drift and regression risk.
- A pure function can deterministically enforce 08:00-16:00 bounds, 8 contiguous quarter-hours, earliest-start tie-breaks, and `unavailable` handling across both days.
- Returning structured selection data, including average price, lets the entity layer remain focused on HA publishing concerns such as formatting and attribute omission.

**Alternatives considered**
- Duplicate the selection logic in two separate sensor classes: rejected because it doubles maintenance cost and creates divergence risk.
- Compute average price only in the entity layer: rejected because it separates one business rule from the rest of the selection result.
- Store computed windows in scheduler state: rejected because the feature is a read-only derived sensor concern, not scheduler-owned data.

## Decision: Publish two dedicated translation-backed text sensors, each with a `price` attribute when available and no `price` attribute when the sensor is `unavailable`.

**Rationale**
- The specification keeps the existing current-day sensor and adds a second analogous tomorrow sensor, so separate entities are the clearest automation surface.
- Home Assistant naming requirements in this repo favor `_attr_has_entity_name = True`, translation-backed naming, and stable unique IDs tied to the config entry.
- Omitting `price` when the sensor is `unavailable` avoids stale or misleading numeric data and gives automations a clean contract: availability controls attribute presence.
- Publishing the window as state and the average as an attribute satisfies the requirement to preserve the existing primary behavior while extending observability.

**Alternatives considered**
- Publish both day results as attributes on a single sensor: rejected because it weakens automation ergonomics and departs from the existing dedicated-entity pattern.
- Publish `price` as `null` or `0.0` on `unavailable`: rejected because both values can be misread as valid data rather than absence of a valid computation.
- Replace the existing sensor with a generic day-selector entity: rejected because the spec explicitly preserves the current sensor and adds an analogous tomorrow sensor.

## Decision: Extend the shared-state refresh/listener path to trigger independent recalculation for both sensors whenever their source payload changes.

**Rationale**
- The existing integration already refreshes from price updates, so the cheapest-risk change is to reuse that path instead of introducing new loops or schedulers.
- The specification requires that only the affected sensor changes when only one day payload changes, so the update path must keep today and tomorrow results isolated.
- Coordinator-managed payload snapshots make it straightforward to detect day-specific recalculation inputs while keeping entity logic declarative.

**Alternatives considered**
- Poll the payload source on a separate timer: rejected because the coordinator/listener infrastructure already exists.
- Recompute both sensors only on full integration refresh: rejected because the desired behavior is keyed to payload changes for each day.
- Update the tomorrow sensor only at midnight rollover: rejected because tomorrow pricing may arrive or change before midnight and must remain visible for planning.

## Decision: Validate the feature with pure calculation tests plus entity-level tests that cover both sensors, `price`, and `unavailable` attribute omission.

**Rationale**
- The constitution requires deterministic tests for decision-heavy logic, and the expanded feature introduces additional failure modes around day separation and attribute contracts.
- Pure tests are the best fit for quarter-hour expansion, average-price calculation, date scoping, and tie-breaking.
- Entity tests are the best fit for translation-backed identity, state formatting, independent day updates, buy-price isolation, and omission of `price` when unavailable.

**Alternatives considered**
- Rely on manual Home Assistant checks only: rejected because the new dual-day contract is easy to regress silently.
- Cover everything only in entity tests: rejected because pure calculation tests remain the most precise way to prove business rules.
- Skip tests for attribute omission: rejected because the updated clarification explicitly makes attribute presence part of the contract.