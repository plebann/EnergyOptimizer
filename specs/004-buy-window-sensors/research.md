# Research: Cztery Sensory Optymalnych Okien Zakupu Energii

## Decision: Reuse coordinator-managed buy-price payloads `prices_today` and `prices_tomorrow` as the only source for buy-window selection.

**Rationale**
- The existing pricing sensors already read payload snapshots from `coordinator.data["price_payloads"]` instead of scraping source entity attributes directly.
- The clarified specification explicitly fixes the payload contract to `prices_today` and `prices_tomorrow` with hourly `time` and `price` fields, so reusing the shared-state path is the lowest-risk extension.
- Keeping day-scoped payload access in coordinator-managed shared state remains aligned with the constitution rule that reads should be centralized and entities should stay thin.

**Alternatives considered**
- Read the configured buy-price entity attributes directly inside each sensor: rejected because it duplicates access logic and bypasses the current shared-state pattern.
- Introduce a new buy-window-specific payload schema: rejected because the existing buy-price payload shape already satisfies the clarified feature contract.
- Persist selected windows across refreshes: rejected because the feature is a pure projection of current coordinator state.

## Decision: Add a generalized two-hour minimum-average buy-window helper to `calculations/price_windows.py` instead of embedding selection logic in sensor classes.

**Rationale**
- The current module already hosts pure price-window helpers for midday sell windows and ranked one-hour sell windows, so it is the natural place for another deterministic selection helper.
- The new feature needs day-aware filtering, contiguous two-hour candidate building, and asymmetric tie-breaking for night and day ranges; those are domain rules that belong in a pure calculation layer.
- Centralizing the logic in pure functions keeps tests deterministic and allows the entity layer to focus on HA state and attribute publication.

**Alternatives considered**
- Implement the buy-window algorithm directly in `entities/sensors/pricing.py`: rejected because it would mix business rules with HA presentation and complicate unit testing.
- Create a separate calculations module just for feature 004: rejected because `price_windows.py` already owns closely related window-selection logic and avoids unnecessary fragmentation.
- Reuse ranked sell-window helpers with inverted sorting only: rejected because the new feature evaluates contiguous two-hour averages and custom tie policies rather than single-hour max-price ranking.

## Decision: Represent each candidate as a contiguous two-hour window built from two valid full-hour buy-price records.

**Rationale**
- The clarified spec restricts candidate starts to full hours and fixes window length at exactly 2 hours.
- Requiring two contiguous valid hourly records yields a clear controlled-degradation rule: any missing, invalid, or noncontiguous hour breaks that candidate.
- This preserves predictable behavior for both current-day and tomorrow payloads and avoids partial or inferred windows.

**Alternatives considered**
- Derive two-hour windows from a single hourly point or from overlapping partial slices: rejected because it contradicts the clarified two-hour window contract.
- Allow starts on non-hour timestamps if they appear in payload data: rejected because clarification fixed candidate starts to full hours only.
- Treat sparse payloads as implicitly fillable from neighboring values: rejected because it would invent data and weaken the reliability of derived sensors.

## Decision: Apply range-specific deterministic tie-breaking after minimizing average buy price.

**Rationale**
- The spec defines two different tie-break policies: night windows should end closest to `06:00`, while day windows should start closest to `13:00`, with earlier start as a further deterministic fallback for day ties.
- Encoding these as explicit ordering rules in the calculation layer makes the behavior provable with pure tests.
- This produces stable results regardless of payload order and avoids ambiguous outputs in automation-facing sensors.

**Alternatives considered**
- Use earliest start as the universal tiebreaker: rejected because it contradicts the clarified business rule for night and day windows.
- Use payload order as the tie resolver: rejected because it makes behavior dependent on source ordering rather than a domain rule.
- Add a second pass to re-rank only equal-price candidates: rejected because a single stable ordering is simpler and yields the same outcome.

## Decision: Publish four dedicated translation-backed text sensors with state `HH:MM` and attributes `price` and `is_negative`.

**Rationale**
- The feature scope calls for four distinct outputs: today night, today day, tomorrow night, and tomorrow day.
- Four dedicated entities preserve the repository pattern of exposing derived pricing outputs as explicit Home Assistant sensors rather than burying them inside source entities.
- Publishing `price` and `is_negative` as attributes matches the clarified contract while keeping state lightweight and automation-friendly.

**Alternatives considered**
- Collapse night and day data into one per-day sensor with attributes: rejected because it weakens automation ergonomics and departs from the current explicit-entity pattern.
- Replace existing pricing sensors with buy-window sensors: rejected because the clarified scope is additive and existing sensors must not change behavior or count.
- Publish a verbose `HH:MM-HH:MM` state: rejected because the spec fixes state to start time only and the end time is implied by the fixed 2-hour duration.

## Decision: Treat empty `prices_tomorrow`, invalid records, and incomplete two-hour slices as controlled degradation to `unavailable` for only the affected sensor slice.

**Rationale**
- The constitution requires controlled degradation when optional or missing data prevents a reliable result.
- The clarified spec explicitly states that empty `prices_tomorrow` means tomorrow sensors remain `unavailable`, not that they should guess a result or affect today's sensors.
- Per-slice degradation keeps unaffected today/night/day slices stable and easy to reason about.

**Alternatives considered**
- Make all four sensors unavailable when one payload is incomplete: rejected because it violates scope isolation between today/tomorrow and night/day.
- Publish partial attributes when only some candidate data is valid: rejected because it would imply a reliable recommendation where none exists.
- Interpret empty `prices_tomorrow` as a valid zero-candidate success case: rejected because the clarified contract treats it as missing data.

## Decision: Validate the feature with focused pure-function tests plus HA-facing sensor tests and additive registration regression coverage.

**Rationale**
- The constitution requires deterministic tests for decision-heavy logic, and this feature adds both new calculation rules and new published entities.
- Pure tests are the best place to prove candidate building, range filtering, tie-breaking, tomorrow isolation, and negative-price handling.
- Entity tests are the best place to prove `HH:MM` state formatting, attribute names, `unavailable` behavior, and stable translation-backed sensor identity.

**Alternatives considered**
- Rely on manual Home Assistant verification only: rejected because the selection logic and tie-break behavior are easy to regress silently.
- Cover everything with entity tests only: rejected because core window-selection rules remain easier and faster to verify in pure tests.
- Skip registration regression checks: rejected because the feature is additive and must not alter the existing sensor surface.