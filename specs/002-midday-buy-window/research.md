# Research: Rozszerzenie Sensorów Okna Najniższej Ceny Zakupu

## Decision: Reuse coordinator-managed buy-price payload snapshots as the authoritative source for both day-scoped sensors.

**Rationale**
- The specification requires that the current-day sensor use `prices_today` and the tomorrow sensor use `prices_tomorrow`.
- Reading both payloads from shared coordinator state keeps entity code thin and consistent with the integration's existing architecture.
- This preserves the Home Assistant-first design where the integration derives outputs from already-configured entities rather than performing ad hoc reads inside derived sensors.
- Isolating each sensor to its own payload prevents cross-day leakage and makes updates deterministic.

**Alternatives considered**
- Read source entity attributes directly inside each sensor: rejected because it duplicates access logic and weakens the shared-state architecture.
- Drive both sensors from only `prices_today` with date offsets: rejected because the spec explicitly assigns `prices_tomorrow` to the tomorrow sensor.
- Introduce a separate storage layer for computed windows: rejected because the feature is a read-only derived-sensor concern.

## Decision: Keep one shared pure calculation path for both midday buy-window variants.

**Rationale**
- The today and tomorrow sensors differ only by payload scope and the today-only `is_active` attribute.
- A shared selector minimizes drift and regression risk across today/tomorrow behavior.
- Centralizing the selection rules in one pure path makes it straightforward to enforce local-day filtering, quasi-zero precedence, standard 8-quarter-hour fallback, and earliest-start tie-breaking.
- Returning a structured result keeps the entity layer focused on Home Assistant publishing concerns like formatting and attribute omission.

**Alternatives considered**
- Duplicate the selector in two separate sensors: rejected because it doubles maintenance cost and invites behavioral drift.
- Compute `price` or active-window state entirely in the entity layer: rejected because it would split the business contract across too many places.
- Push the decision into scheduler logic: rejected because the feature is observational, not scheduler-owned.

## Decision: Give zero and quasi-zero buy prices business priority over the standard midday minimum window.

**Rationale**
- The updated specification explicitly states that prices equal to zero or below `0.05 PLN/kWh` represent a higher-value operational case than the normal cheapest-window search.
- Publishing the full span from the first to the last such occurrence ensures the user sees the entire free or quasi-free opportunity range instead of an arbitrary two-hour subset.
- Applying this rule before the standard selector produces a deterministic contract that is easy to test and explain.

**Alternatives considered**
- Keep the previous cheapest 8-quarter-hour selector even on quasi-zero days: rejected because it would violate the clarified business priority.
- Publish only the first quasi-zero hour: rejected because the spec requires the full span from first to last qualifying occurrence.
- Treat only exact zero as special: rejected because the spec explicitly includes values below `0.05 PLN/kWh`.

## Decision: Publish `price` for both sensors, but publish `is_active` only for the current-day sensor.

**Rationale**
- The specification extends both sensors with `price` as an informational attribute tied to the selected window.
- `is_active` has business meaning only for the current-day window because it answers whether the present local time falls inside the currently recommended interval.
- Omitting `is_active` for tomorrow avoids publishing a misleading attribute for a future interval that cannot be active yet.
- Omitting dependent attributes when a sensor is unavailable keeps the Home Assistant contract clean and prevents stale values.

**Alternatives considered**
- Publish `is_active` for both sensors: rejected because the spec explicitly excludes it for tomorrow.
- Publish `price` or `is_active` as null-like placeholders when unavailable: rejected because that weakens the signal that no trustworthy result exists.
- Move `is_active` into a separate helper sensor: rejected because the spec defines it as an informational attribute on the today window sensor.

## Decision: Validate the feature with pure calculation tests plus entity-level publication tests.

**Rationale**
- The constitution requires deterministic tests for decision-heavy logic, and this feature adds multiple behavior branches: quasi-zero precedence, standard fallback, day separation, attribute omission, and today-only `is_active`.
- Pure tests are the best fit for verifying selection rules and day-scoped payload interpretation.
- Entity tests are the best fit for verifying translation-backed identity, `HH:MM-HH:MM` formatting, today/tomorrow attribute differences, and `unavailable` output behavior.
- Focused tests make it easier to prove that sell-price changes do not affect these buy-window sensors.

**Alternatives considered**
- Rely on manual Home Assistant checks only: rejected because the day-specific and quasi-zero contracts are easy to regress silently.
- Cover everything only with entity tests: rejected because the selection algorithm is easier to verify precisely in unit tests.
- Skip explicit tests for omitted attributes: rejected because attribute omission is part of the contract, not an incidental detail.
