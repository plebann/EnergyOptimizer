# Data Model: Rozszerzenie Sensorów Okna Najniższej Ceny Sprzedaży

## 1. DayScopedPricePayload

**Purpose**: Hourly sell-price payload for one specific local business day, sourced from shared integration state.

| Field | Type | Description |
|-------|------|-------------|
| `payload_key` | `str` | Source key used by the integration, either `prices_today` or `prices_tomorrow` |
| `evaluation_date_local` | `date` | Local business day represented by the payload |
| `entries` | `list[HourlyPriceEntry]` | Hourly source entries for that day |
| `source_entity_id` | `str` | Entity ID of the configured sell-price source |

**Validation rules**
- `payload_key` must be one of `prices_today` or `prices_tomorrow`.
- `entries` may be empty, but an empty payload cannot produce an available sensor state.
- `evaluation_date_local` must match the day semantics of the payload key.
- The payload must be treated as sell-price data only and must not be mixed with buy-price state.

**Relationships**
- One `DayScopedPricePayload` produces zero or more `QuarterHourPricePoint` objects.
- One payload drives exactly one published derived sensor.

## 2. HourlyPriceEntry

**Purpose**: One hourly sell-price source item before quarter-hour expansion.

| Field | Type | Description |
|-------|------|-------------|
| `start_local` | `datetime` | Local start timestamp of the represented hour |
| `end_local` | `datetime` | Local end timestamp of the represented hour |
| `sell_price_value` | `float` | Sell-price value for the hour |
| `source_period` | `str` | Original textual period from the source payload |

**Validation rules**
- `sell_price_value` must be numeric.
- `end_local` must be exactly one hour after `start_local`.
- The entry must belong to the payload's `evaluation_date_local`.

## 3. QuarterHourPricePoint

**Purpose**: Normalized quarter-hour sell-price sample derived from one hourly entry.

| Field | Type | Description |
|-------|------|-------------|
| `start_local` | `datetime` | Local start timestamp of the quarter-hour slot |
| `end_local` | `datetime` | Local end timestamp of the quarter-hour slot |
| `evaluation_date_local` | `date` | Local business date inherited from the payload |
| `sell_price_value` | `float` | Parsed sell price value used for comparisons and averaging |
| `payload_key` | `str` | Source key that produced the point |

**Validation rules**
- `start_local` and `end_local` must describe one 15-minute slot.
- The point must belong to the payload's `evaluation_date_local`.
- Only slots fully inside 08:00-16:00 are candidates for this feature.
- Each hourly entry must expand into 4 consecutive quarter-hour points with the same `sell_price_value`.

**Relationships**
- Many `QuarterHourPricePoint` objects feed one `MiddaySellWindowCandidate`.

## 4. MiddaySellWindowCandidate

**Purpose**: One contiguous 8-slot candidate window evaluated against other windows for a single day-scoped payload.

| Field | Type | Description |
|-------|------|-------------|
| `start_local` | `datetime` | Local start timestamp of the candidate window |
| `end_local` | `datetime` | Local end timestamp after 8 quarter-hours |
| `slot_count` | `int` | Number of quarter-hour points; always 8 for valid candidates |
| `total_cost` | `float` | Sum of the 8 sell-price values |
| `average_price` | `float` | Arithmetic mean of the 8 sell-price values before final sensor publication |
| `points` | `list[QuarterHourPricePoint]` | Ordered points making up the candidate |

**Validation rules**
- `slot_count` must equal 8.
- `points` must be contiguous with no quarter-hour gaps.
- `start_local` must be `>= 08:00` and `end_local` must be `<= 16:00` for the evaluated local day.
- `total_cost` and `average_price` are derived only from sell-price values.

**Selection rules**
- Choose the candidate with the lowest `total_cost`.
- On equal `total_cost`, choose the earliest `start_local`.

**Relationships**
- Many candidates may be derived from one `DayScopedPricePayload`.
- Exactly zero or one candidate becomes the published sensor state for a given day.

## 5. MiddaySellWindowSensorState

**Purpose**: Published Home Assistant state contract for one day-scoped derived sensor.

| Field | Type | Description |
|-------|------|-------------|
| `sensor_key` | `str` | Stable identifier for the derived sensor, e.g. current-day or tomorrow variant |
| `state` | `str \| unavailable` | Published sensor value in `HH:MM-HH:MM` format or `unavailable` |
| `price` | `float \| omitted` | Rounded average price in PLN/kWh when available; omitted when unavailable |
| `selected_start_local` | `datetime \| None` | Selected start time when a valid window exists |
| `selected_end_local` | `datetime \| None` | Selected end time when a valid window exists |
| `evaluation_date_local` | `date` | Local day used for selection |
| `payload_key` | `str` | Source key used for this sensor instance |
| `source_entity_id` | `str` | Source entity used to build the current state |

**Validation rules**
- `state` must match `HH:MM-HH:MM` when available.
- `price` must be rounded to 2 decimal places when present.
- `price` must be omitted when `state` is `unavailable`.
- The sensor must ignore buy-price state changes for both calculation and published output.

## State Transitions

| From | To | Trigger |
|------|----|---------|
| `unavailable` | `available` | Sufficient valid quarter-hour data appears for that sensor's day-scoped payload |
| `available` | `available` | The cheapest valid window or rounded `price` changes after a payload update for that same day |
| `available` | `unavailable` | Source data for that day becomes incomplete, non-numeric, or no longer covers a full 8-slot window |
| `unavailable` | `unavailable` | Updates still do not provide enough contiguous valid data for that sensor's day |

## Notes

- No feature-specific persistence is required; both sensors reflect current shared Home Assistant price data for their respective day scopes.
- The entity layer remains read-only and does not own scheduler or configuration state.
- The same calculation model applies to both sensors; only the payload key and evaluated local day differ.