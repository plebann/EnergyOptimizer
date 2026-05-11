# Data Model: Cztery Sensory Optymalnych Okien Sprzedazy Energii

## 1. HourlySellPriceEntry

**Purpose**: One hourly sell-price record consumed from `prices_today` or `prices_tomorrow`.

| Field | Type | Description |
|-------|------|-------------|
| `time` | `str | datetime` | Input timestamp representing the start of a full local hour |
| `price` | `float` | Sell price for that one-hour period |
| `start_local` | `datetime` | Parsed local start timestamp used internally for ranking |
| `end_local` | `datetime` | Parsed local end timestamp exactly one hour after `start_local` |
| `business_date` | `date` | Local day derived from `start_local` |

**Validation rules**
- `price` must be numeric.
- `start_local` must parse from the input timestamp.
- `end_local` must equal `start_local + 1 hour`.
- The record must belong to the evaluated business day for its payload key.

**Relationships**
- Many `HourlySellPriceEntry` objects form one `DayScopedSellPricePayload`.
- Exactly zero or one `SellWindowCandidate` can be derived from one hourly entry because the feature evaluates only full-hour windows.

## 2. DayScopedSellPricePayload

**Purpose**: One day-specific payload of sell-price entries sourced from coordinator-managed shared state.

| Field | Type | Description |
|-------|------|-------------|
| `payload_key` | `str` | Either `prices_today` or `prices_tomorrow` |
| `evaluation_date_local` | `date` | Local date that the payload is expected to represent |
| `source_entity_id` | `str` | Configured sell-price entity ID |
| `entries` | `list[HourlySellPriceEntry]` | Hourly records for that day |

**Validation rules**
- `payload_key` must be either `prices_today` or `prices_tomorrow`.
- All valid entries must share the payload's `evaluation_date_local`.
- The payload is treated as sell-price data only and must not mix with buy-price state.

**Relationships**
- One payload feeds zero or more `SellWindowCandidate` objects for each evaluated range.
- Each published sensor evaluates exactly one payload and one time range.

## 3. SellWindowCandidate

**Purpose**: One valid one-hour candidate window inside a named range for one day-scoped payload.

| Field | Type | Description |
|-------|------|-------------|
| `range_key` | `str` | `morning` or `evening` |
| `start_local` | `datetime` | Local start time of the one-hour window |
| `end_local` | `datetime` | Local end time of the one-hour window |
| `sell_price` | `float` | Sell price used for ranking this candidate |
| `payload_key` | `str` | Source payload key that produced the candidate |
| `source_entity_id` | `str` | Configured sell-price entity ID |

**Validation rules**
- `start_local.minute` must equal `0`.
- `end_local` must equal `start_local + 1 hour`.
- Morning candidates must satisfy `04:00 <= start_local < 10:00` and `end_local <= 10:00`.
- Evening candidates must satisfy `16:00 <= start_local < 22:00` and `end_local <= 22:00`.
- `sell_price` must come directly from the hourly input record for that hour.

**Relationships**
- Many candidates can be derived from one `DayScopedSellPricePayload`.
- Exactly zero, one, or many candidates may exist for each `(payload_key, range_key)` pair.

## 4. RankedSellWindowSelection

**Purpose**: Deterministic ranking result for one sensor variant.

| Field | Type | Description |
|-------|------|-------------|
| `sensor_key` | `str` | Stable identifier for the sensor variant |
| `evaluation_date_local` | `date` | Day being evaluated |
| `range_key` | `str` | `morning` or `evening` |
| `best_candidate` | `SellWindowCandidate | None` | Highest-ranked candidate |
| `second_best_candidate` | `SellWindowCandidate | None` | Second-ranked candidate |
| `second_window_gap_pct` | `float | omitted` | Percentage by which the second-best candidate is worse than the best candidate |

**Validation rules**
- Candidates are ranked by `sell_price` descending and `start_local` ascending.
- A valid published selection requires both `best_candidate` and `second_best_candidate`.
- `second_window_gap_pct` is computed as `((best - second_best) / best) * 100`.
- `second_window_gap_pct` is omitted when `best_candidate.sell_price` equals `0`.
- `second_window_gap_pct` is rounded to 1 decimal when present.

**Relationships**
- One `RankedSellWindowSelection` drives exactly one published sensor state.
- One sensor update recalculates one selection from one payload/range pair.

## 5. SellWindowSensorState

**Purpose**: Published Home Assistant state contract for one ranked sell-window sensor.

| Field | Type | Description |
|-------|------|-------------|
| `sensor_key` | `str` | Stable identifier such as `morning_sell_window` or `evening_sell_window_tomorrow` |
| `state` | `str | unavailable` | `HH:MM` start time of the best candidate or `unavailable` |
| `price` | `float | omitted` | Rounded best-candidate sell price in PLN/kWh |
| `second_window_start` | `str | omitted` | `HH:MM` start time of the second-best candidate |
| `second_window_price` | `float | omitted` | Rounded second-best candidate sell price in PLN/kWh |
| `second_window_gap_pct` | `float | omitted` | Rounded percentage difference relative to the best candidate |
| `payload_key` | `str` | Source payload key used for this sensor |
| `source_entity_id` | `str` | Configured sell-price source entity |

**Validation rules**
- `state` must match `HH:MM` when available.
- `price` and `second_window_price` must be rounded to 3 decimal places when present.
- `second_window_start` must match `HH:MM` when present.
- `price`, `second_window_start`, and `second_window_price` are omitted when `state` is `unavailable`.
- `second_window_gap_pct` is omitted when `state` is `unavailable` or when `best_candidate.sell_price == 0`.
- Buy-price changes must not affect any field in this state model.

## State Transitions

| From | To | Trigger |
|------|----|---------|
| `unavailable` | `available` | At least two valid ranked candidates appear for the sensor's day and range |
| `available` | `available` | The best candidate, second-best candidate, or rounded attributes change after a payload update for that same day/range |
| `available` | `unavailable` | Fewer than two valid hourly candidates remain, data becomes non-numeric, or the relevant range no longer yields two full-hour windows |
| `unavailable` | `unavailable` | Updates still fail to produce two valid candidates for that sensor variant |

## Notes

- No feature-specific persistence is required; all four sensors reflect current coordinator state.
- The same ranking model applies to today/tomorrow and morning/evening variants; only `payload_key`, `evaluation_date_local`, and `range_key` differ.
- The existing midday sensor pair and other current sensors remain outside the scope of this new state model and must keep their existing behavior unchanged.