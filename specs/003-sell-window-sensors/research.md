# Research: Cztery Sensory Optymalnych Okien Sprzedazy Energii

## Decision: Reuse coordinator-managed `prices_today` and `prices_tomorrow` payloads as the only source for hourly sell-window ranking.

**Rationale**
- The active integration already exposes sell-price payloads through `coordinator.data["price_payloads"]`, and the existing pricing sensors consume them without direct entity scraping.
- The clarified specification says each input record already represents one full hour, so the cleanest extension is to rank those hourly records directly instead of introducing a second normalization layer.
- Keeping day-scoped payload access inside shared coordinator state remains aligned with the constitution rule that reads should be centralized and entities should stay thin.

**Alternatives considered**
- Read the configured sell-price entity attributes directly inside each sensor: rejected because it duplicates access logic and bypasses the current shared-state pattern.
- Add new config entries for separate morning/evening sources: rejected because the payloads already contain the required data and the feature is derived-only.
- Persist ranked windows separately across refreshes: rejected because the feature is a pure projection of current coordinator state.

## Decision: Replace the current specialized midday cheapest-window selector with a generalized hourly max-price ranking helper that accepts a day scope and time range.

**Rationale**
- The current code in `calculations/price_windows.py` is specialized for 8 quarter-hours between 08:00 and 16:00 and returns `HH:MM-HH:MM`; the new feature needs four one-hour windows across two different ranges and a state of `HH:MM`.
- A generalized helper can evaluate morning and evening slices with one code path, preserve deterministic tie-breaking, and expose both the best and second-best candidates without duplicating business logic.
- Centralizing ranking in a pure function keeps tests deterministic and lets the entity layer focus on HA state/attribute publication.

**Alternatives considered**
- Keep the midday helper and add a second implementation just for morning/evening ranking: rejected because it would split similar business rules across two algorithms.
- Perform ranking entirely in the entity class: rejected because ranking, sorting, and availability rules are domain logic that belong in the calculations layer.
- Continue expanding hours into quarter-hours and then re-collapse to hourly outputs: rejected because the clarified input contract already provides one price per hour and candidate starts are limited to full hours.

## Decision: Publish four dedicated translation-backed text sensors in addition to the existing pricing sensors.

**Rationale**
- The specification requires adding four new result sensors: today morning, today evening, tomorrow morning, and tomorrow evening.
- Four dedicated entities provide the cleanest automation and dashboard surface and match the existing repo pattern of publishing derived pricing sensors as explicit Home Assistant entities.
- Keeping the current sensor set unchanged preserves backward compatibility for existing dashboards, automations, and expectations inside the integration.

**Alternatives considered**
- Replace the two midday sensors with the four new sensors: rejected because the clarified scope is additive and existing sensors must not change their count or functionality.
- Collapse morning and evening data into one multi-attribute sensor per day: rejected because it weakens automation ergonomics and departs from the existing explicit-entity pattern.
- Publish the ranking only as attributes on the sell-price sensor: rejected because it hides a primary decision output inside a source entity.

## Decision: Use descending sell price with ascending start time as the single ranking order, then take the first two candidates from that sorted list.

**Rationale**
- The clarified spec explicitly says the best window should be earlier and the second-best later when their prices are equal.
- A single stable sort order makes best and second-best selection deterministic across both today/tomorrow and morning/evening variants.
- This rule is easy to prove with pure unit tests and avoids special branching once candidates are normalized.

**Alternatives considered**
- Compare only the best candidate and then run a second pass for the runner-up: rejected because it adds complexity without changing the outcome.
- Break ties by later start or source order: rejected because it contradicts the clarified business rule.
- Randomize equal-price ordering: rejected because it would make automation results and tests unstable.

## Decision: Publish `price` and `second_window_price` rounded to 3 decimals, `second_window_gap_pct` rounded to 1 decimal, and omit only the percentage attribute when the best price is zero.

**Rationale**
- The spec clarifications define exact output precision, so rounding belongs in the output contract and test suite.
- Omitting only `second_window_gap_pct` for zero-valued best windows avoids division-by-zero semantics while preserving otherwise valid ranked windows.
- Keeping the price attributes available even when percentage is omitted gives users the numeric comparison needed for decision-making.

**Alternatives considered**
- Publish all numeric values without rounding: rejected because Home Assistant state diffs and tests become noisier without business value.
- Make the entire sensor unavailable when the best price is zero: rejected because zero is still a valid sell price and the ranking itself remains valid.
- Publish `second_window_gap_pct` as `0.0` when best price is zero: rejected because that value would misrepresent an undefined comparison as a measured result.

## Decision: Validate the feature with focused pure-function tests plus entity tests that cover additive publication, coexistence with existing sensors, tie-breaks, and controlled degradation.

**Rationale**
- The constitution requires deterministic tests for decision-heavy logic, and this feature changes the ranking algorithm while extending the published entity surface.
- Pure tests are the best place to prove range filtering, sorting, day separation, and percentage calculation.
- Entity tests are the best place to prove `HH:MM` state formatting, translation-backed variants, rounded attributes, `unavailable` semantics for missing top-two candidates, and the absence of regressions in existing sensors.

**Alternatives considered**
- Rely on manual Home Assistant verification only: rejected because the ranking and coexistence behavior is easy to regress silently.
- Cover everything in entity tests only: rejected because core ranking rules remain easier and faster to verify in pure tests.
- Skip coexistence regression testing for existing sensors: rejected because the clarified scope explicitly forbids changing existing sensor count or behavior.