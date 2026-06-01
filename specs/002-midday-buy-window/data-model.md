# Data Model: Rozszerzenie Sensorów Okna Najniższej Ceny Zakupu

## 1. HourlyBuyPriceEntry

**Purpose**: One hourly buy-price record consumed from `prices_today` or `prices_tomorrow`.

| Field | Type | Description |
|-------|------|-------------|
| `start_local` | `datetime` | Local start timestamp of the represented full hour |
| `end_local` | `datetime` | Local end timestamp exactly one hour after `start_local` |
| `business_date` | `date` | Local day derived from `start_local` |
| `buy_price_value` | `float` | Parsed buy-price value for that hour |
| `source_entity_id` | `str` | Configured buy-price source entity |

**Validation rules**
- `buy_price_value` must be numeric.
- `end_local` must equal `start_local + 1 hour`.
- The record must belong to the evaluated local business day.
- Duplicate hourly starts for the same day are treated as invalid for deterministic selection.

**Relationships**
- Many `HourlyBuyPriceEntry` objects form one `DayScopedBuyPricePayload`.
- The same entries can feed either a `QuasiZeroMiddayBuyWindow` result or a `StandardMiddayBuyWindowCandidate` result.

## 2. DayScopedBuyPricePayload

**Purpose**: One day-specific payload of buy-price entries sourced from coordinator-managed shared state.

| Field | Type | Description |
|-------|------|-------------|
| `payload_key` | `str` | Either `prices_today` or `prices_tomorrow` |
| `evaluation_date_local` | `date` | Local date the payload is expected to represent |
| `source_entity_id` | `str` | Configured buy-price source entity |
| `entries` | `list[HourlyBuyPriceEntry]` | Hourly buy-price entries for that day |

**Validation rules**
- `payload_key` must be either `prices_today` or `prices_tomorrow`.
- All valid entries must belong to `evaluation_date_local`.
- The payload is treated as buy-price data only and must not mix with sell-price state.
- An empty or invalid payload cannot produce an available sensor state.

**Relationships**
- One payload feeds exactly one day-scoped sensor variant.
- One payload may produce zero or more standard candidates, or one quasi-zero span result.

## 3. StandardMiddayBuyWindowCandidate

**Purpose**: One standard contiguous midday candidate used when the evaluated day contains no quasi-zero buy prices.

| Field | Type | Description |
|-------|------|-------------|
| `start_local` | `datetime` | Local start timestamp of the candidate window |
| `end_local` | `datetime` | Local end timestamp after 8 quarter-hours / 2 hours |
| `slot_count` | `int` | Number of quarter-hour slots represented; always 8 for valid standard candidates |
| `average_price` | `float` | Arithmetic mean of the two hourly buy-price values backing the window |
| `source_entries` | `tuple[HourlyBuyPriceEntry, HourlyBuyPriceEntry]` | Ordered hourly records forming the window |

**Validation rules**
- `slot_count` must equal 8.
- `start_local` must be `>= 08:00` and `end_local` must be `<= 16:00` for the evaluated day.
- The second source entry must start exactly one hour after the first.
- `average_price` must be derived only from buy-price values.

**Selection rules**
- This candidate type is used only when no quasi-zero buy-price entries exist in the evaluated day.
- The chosen candidate is the one with the lowest `average_price`.
- On equal `average_price`, the earliest `start_local` wins.

## 4. QuasiZeroMiddayBuyWindow

**Purpose**: Priority result used when the evaluated day contains at least one buy-price entry below `0.05 PLN/kWh`.

| Field | Type | Description |
|-------|------|-------------|
| `start_local` | `datetime` | Start of the first quasi-zero hourly entry in the day |
| `end_local` | `datetime` | End of the last quasi-zero hourly entry in the day |
| `slot_count` | `int` | Number of quarter-hour slots covered by the full selected span |
| `average_price` | `float` | Arithmetic mean of all hourly buy-price values between the first and last quasi-zero entries, inclusive |
| `selected_entries` | `list[HourlyBuyPriceEntry]` | Ordered hourly entries covered by the published span |

**Validation rules**
- At least one entry in the evaluated day must satisfy `buy_price_value < 0.05`.
- The span begins at the first qualifying entry and ends at the last qualifying entry.
- All hourly entries between those boundaries are included in the published span, even if some intermediate prices are higher.
- `slot_count` equals `len(selected_entries) * 4`.

**Selection rules**
- This result has priority over the standard midday 8-quarter-hour selector.
- If any quasi-zero entry exists, no standard candidate may replace it for that day.

## 5. MiddayBuyWindowSensorState

**Purpose**: Published Home Assistant state contract for one today/tomorrow midday buy-window sensor.

| Field | Type | Description |
|-------|------|-------------|
| `sensor_key` | `str` | Stable identifier such as `midday_buy_window` or `midday_buy_window_tomorrow` |
| `state` | `str \| unavailable` | Published sensor value in `HH:MM-HH:MM` format or `unavailable` |
| `price` | `float \| omitted` | Rounded average buy price in PLN/kWh when available |
| `is_active` | `"on" \| "off" \| omitted` | Today-only informational attribute indicating whether the current local time falls inside the published today window |
| `selected_start_local` | `datetime \| None` | Selected start time when a valid result exists |
| `selected_end_local` | `datetime \| None` | Selected end time when a valid result exists |
| `evaluation_date_local` | `date` | Local day used for selection |
| `payload_key` | `str` | Source payload key used for this sensor |
| `source_entity_id` | `str` | Buy-price source entity used to build the current state |

**Validation rules**
- `state` must match `HH:MM-HH:MM` when available.
- `price` must be rounded to 2 decimal places when present.
- `price` must be omitted when `state` is `unavailable`.
- `is_active` must be published only for the today sensor and only when a valid today window exists.
- `is_active` must be omitted for the tomorrow sensor.
- Buy-window sensor state depends only on buy-price payload data, not on sell-price changes.

## State Transitions

| From | To | Trigger |
|------|----|---------|
| `unavailable` | `available` | The relevant day payload contains enough valid buy-price data to produce either a quasi-zero span or a standard midday window |
| `available` | `available` | The selected window, rounded `price`, or today-only `is_active` changes after a payload or current-time update |
| `available` | `unavailable` | The relevant day payload becomes empty, invalid, duplicated, sparse, or otherwise insufficient to prove a valid result |
| `unavailable` | `unavailable` | Updates still fail to produce one valid day-scoped result |

## Notes

- No feature-specific persistence is required; both sensors reflect current coordinator state.
- The same day-scoped input model applies to today and tomorrow; only `payload_key`, `evaluation_date_local`, and the today-only `is_active` publication rule differ.
- The existing buy-window presentation remains the primary output; `price` and `is_active` are additive informational attributes.
