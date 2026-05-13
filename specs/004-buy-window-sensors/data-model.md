# Data Model: Cztery Sensory Optymalnych Okien Zakupu Energii

## 1. HourlyBuyPriceEntry

**Purpose**: One hourly buy-price record consumed from `prices_today` or `prices_tomorrow`.

| Field | Type | Description |
|-------|------|-------------|
| `time` | `str | datetime` | Input timestamp representing the start of a full local hour |
| `price` | `float` | Buy price for that one-hour period |
| `start_local` | `datetime` | Parsed local start timestamp used internally for candidate building |
| `end_local` | `datetime` | Parsed local end timestamp exactly one hour after `start_local` |
| `business_date` | `date` | Local day derived from `start_local` |

**Validation rules**
- `price` must be numeric.
- `start_local` must parse from the input timestamp.
- `start_local.minute`, `start_local.second`, and `start_local.microsecond` must equal `0`.
- `end_local` must equal `start_local + 1 hour`.
- The record must belong to the evaluated business day for its payload key.

**Relationships**
- Many `HourlyBuyPriceEntry` objects form one `DayScopedBuyPricePayload`.
- Each entry can participate in zero, one, or two overlapping `TwoHourBuyWindowCandidate` objects depending on neighboring hourly entries.

## 2. DayScopedBuyPricePayload

**Purpose**: One day-specific payload of buy-price entries sourced from coordinator-managed shared state.

| Field | Type | Description |
|-------|------|-------------|
| `payload_key` | `str` | Either `prices_today` or `prices_tomorrow` |
| `evaluation_date_local` | `date` | Local date the payload is expected to represent |
| `source_entity_id` | `str` | Configured buy-price entity ID |
| `entries` | `list[HourlyBuyPriceEntry]` | Hourly records for that day |

**Validation rules**
- `payload_key` must be either `prices_today` or `prices_tomorrow`.
- All valid entries must share the payload's `evaluation_date_local`.
- An empty `prices_tomorrow` list is treated as missing data for tomorrow sensors.
- The payload is treated as buy-price data only and must not mix with sell-price state.

**Relationships**
- One payload feeds zero or more `TwoHourBuyWindowCandidate` objects for each evaluated range.
- Each published sensor evaluates exactly one payload and one time range.

## 3. TwoHourBuyWindowCandidate

**Purpose**: One valid contiguous two-hour candidate window inside a named range for one day-scoped payload.

| Field | Type | Description |
|-------|------|-------------|
| `range_key` | `str` | `night` or `day` |
| `start_local` | `datetime` | Local start time of the two-hour window |
| `end_local` | `datetime` | Local end time of the two-hour window |
| `average_buy_price` | `float` | Average buy price across the two hourly records |
| `hourly_entries` | `tuple[HourlyBuyPriceEntry, HourlyBuyPriceEntry]` | Source records forming the window |
| `payload_key` | `str` | Source payload key that produced the candidate |
| `source_entity_id` | `str` | Configured buy-price entity ID |

**Validation rules**
- `start_local.minute` must equal `0`.
- `end_local` must equal `start_local + 2 hours`.
- The second hourly entry must begin exactly one hour after the first.
- Night candidates must satisfy `00:00 <= start_local < 06:00` and `end_local <= 06:00`.
- Day candidates must satisfy `10:00 <= start_local < 16:00` and `end_local <= 16:00`.
- `average_buy_price` must equal the arithmetic mean of the two hourly prices.

**Relationships**
- Many candidates can be derived from one `DayScopedBuyPricePayload`.
- Exactly zero or more candidates may exist for each `(payload_key, range_key)` pair.

## 4. SelectedBuyWindow

**Purpose**: Deterministic selection result for one buy-window sensor variant.

| Field | Type | Description |
|-------|------|-------------|
| `sensor_key` | `str` | Stable identifier for the sensor variant |
| `evaluation_date_local` | `date` | Day being evaluated |
| `range_key` | `str` | `night` or `day` |
| `selected_candidate` | `TwoHourBuyWindowCandidate | None` | Lowest-ranked valid candidate after tie-breaking |
| `is_negative` | `bool | omitted` | True when the selected candidate's average buy price is below zero |

**Validation rules**
- Night candidates are ordered by `average_buy_price` ascending, then by absolute closeness of `end_local` to `06:00`, then by later `end_local`.
- Day candidates are ordered by `average_buy_price` ascending, then by absolute closeness of `start_local` to `13:00`, then by earlier `start_local`.
- A valid published selection requires one complete valid `selected_candidate`.
- `is_negative` is true only when `selected_candidate.average_buy_price < 0`.

**Relationships**
- One `SelectedBuyWindow` drives exactly one published sensor state.
- One sensor update recalculates one selection from one payload/range pair.

## 5. BuyWindowSensorState

**Purpose**: Published Home Assistant state contract for one buy-window sensor.

| Field | Type | Description |
|-------|------|-------------|
| `sensor_key` | `str` | Stable identifier such as `night_buy_window` or `day_buy_window_tomorrow` |
| `state` | `str | unavailable` | `HH:MM` start time of the selected candidate or `unavailable` |
| `price` | `float | omitted` | Rounded selected average buy price in PLN/kWh |
| `is_negative` | `bool | omitted` | Whether the selected average buy price is below zero |
| `payload_key` | `str` | Source payload key used for this sensor |
| `source_entity_id` | `str` | Configured buy-price source entity |

**Validation rules**
- `state` must match `HH:MM` when available.
- `price` must be rounded to 3 decimal places when present.
- `is_negative` is omitted when `state` is `unavailable`.
- `price` is omitted when `state` is `unavailable`.
- Buy-window sensor state depends only on buy-price payload data, not on sell-price changes.

## State Transitions

| From | To | Trigger |
|------|----|---------|
| `unavailable` | `available` | At least one complete valid two-hour candidate appears for the sensor's day and range |
| `available` | `available` | The selected candidate or rounded attributes change after a payload update for that same day/range |
| `available` | `unavailable` | No valid contiguous two-hour candidate remains, the relevant payload becomes empty, or required entry data becomes invalid |
| `unavailable` | `unavailable` | Updates still fail to produce one valid candidate for that sensor variant |

## Notes

- No feature-specific persistence is required; all four sensors reflect current coordinator state.
- The same selection model applies to today/tomorrow and night/day variants; only `payload_key`, `evaluation_date_local`, and `range_key` differ.
- The existing sell-window, midday sell-window, and other current sensors remain outside the scope of this state model and must keep their current behavior unchanged.