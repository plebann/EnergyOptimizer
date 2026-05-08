# Data Model: Okno Najniższej Ceny Sprzedaży w Środku Dnia

## 1. QuarterHourPricePoint

**Purpose**: Normalized sell-price sample for one quarter-hour slot derived from the configured current-day hourly price-series source.

| Field | Type | Description |
|-------|------|-------------|
| `start_local` | `datetime` | Local start timestamp of the quarter-hour slot |
| `end_local` | `datetime` | Local end timestamp of the quarter-hour slot |
| `business_date` | `date` | Business date carried by the source payload |
| `sell_price_value` | `float` | Parsed sell price value used for comparisons |
| `source_period` | `str` | Original textual period from the source payload |
| `source_entity_id` | `str` | Entity ID of the configured source sensor |

**Validation rules**
- `sell_price_value` must be numeric.
- `start_local` and `end_local` must describe one 15-minute slot.
- The point must belong to the current local day.
- Only slots fully inside 08:00-16:00 are candidates for this feature.
- Each point may be derived by splitting one hourly source value into 4 consecutive quarter-hours with the same price.

**Relationships**
- Many `QuarterHourPricePoint` objects feed one `MiddaySellWindowCandidate`.

## 2. MiddaySellWindowCandidate

**Purpose**: One contiguous candidate window evaluated against other windows.

| Field | Type | Description |
|-------|------|-------------|
| `start_local` | `datetime` | Local start timestamp of the candidate window |
| `end_local` | `datetime` | Local end timestamp after 8 quarter-hours |
| `slot_count` | `int` | Number of quarter-hour points; always 8 for valid candidates |
| `total_cost` | `float` | Sum of the 8 normalized sell prices |
| `points` | `list[QuarterHourPricePoint]` | Ordered points making up the candidate |

**Validation rules**
- `slot_count` must equal 8.
- `points` must be contiguous with no missing quarter-hour gaps.
- `start_local` must be `>= 08:00` and `end_local` must be `<= 16:00` on the current local day.
- `total_cost` is derived only from sell-price values.

**Selection rules**
- Choose the candidate with the lowest `total_cost`.
- On equal `total_cost`, choose the earliest `start_local`.

**Relationships**
- Many candidates may be derived from one day of `QuarterHourPricePoint` data.
- Exactly zero or one candidate becomes the published sensor state.

## 3. MiddaySellWindowSensorState

**Purpose**: Published Home Assistant state contract for the derived sensor.

| Field | Type | Description |
|-------|------|-------------|
| `state` | `str \| unavailable` | Published sensor value in `HH:MM-HH:MM` format or `unavailable` |
| `selected_start_local` | `datetime \| None` | Selected start time when a valid window exists |
| `selected_end_local` | `datetime \| None` | Selected end time when a valid window exists |
| `source_entity_id` | `str` | Source entity used to build the current state |
| `evaluation_date_local` | `date` | Current local day used for selection |

**Validation rules**
- `state` must match `HH:MM-HH:MM` when available.
- `state` must be `unavailable` when fewer than 8 contiguous valid points exist inside the required day window.
- The sensor must ignore buy-price state changes for both calculation and published output.

## State Transitions

| From | To | Trigger |
|------|----|---------|
| `unavailable` | `available` | Sufficient valid current-day quarter-hour data appears for at least one 8-slot window |
| `available` | `available` | Cheapest valid window changes after a price-series update |
| `available` | `unavailable` | Source data becomes incomplete, non-numeric, or no longer covers a full 8-slot window |
| `unavailable` | `unavailable` | Updates still do not provide enough contiguous valid data |

## Notes

- No feature-specific persistence is required; the sensor reflects the current local day and current HA price data.
- The entity remains a read-only derived output and does not own configuration or scheduler state.
