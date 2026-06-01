# Contract: Midday Sell Window Sensors

## Interface Type

Two Home Assistant sensor entities published by the `energy_optimizer` integration.

## Purpose

Expose the cheapest sell-price window of length 8 quarter-hours between 08:00 and 16:00 for:

- the current local day,
- the next local day,

while preserving the existing text-state behavior and adding a `price` attribute for the average selected window price.

## Input Contract

The implementation reads day-scoped hourly `sell-price sensor` payloads from shared integration state already maintained for electricity pricing.

Expected payload shapes from the source entity:

| Field | Required | Meaning |
|-------|----------|---------|
| `prices_today` | yes for current-day sensor | Collection of hourly price entries for the current local day |
| `prices_today[].time` | yes | Timestamp for the hour beginning |
| `prices_today[].price` | yes | Sell-price value used for comparison |
| `prices_tomorrow` | yes for tomorrow sensor | Collection of hourly price entries for the next local day |
| `prices_tomorrow[].time` | yes | Timestamp for the hour beginning |
| `prices_tomorrow[].price` | yes | Sell-price value used for comparison |

Each input slot is 1 hour long. During calculation, each hour is expanded into 4 consecutive quarter-hour slots that all inherit the same price value.

The payloads are consumed from coordinator-managed shared state rather than by directly reading the source entity in derived sensor code.

## Output Contract

| Property | Current-day sensor | Tomorrow sensor |
|----------|--------------------|-----------------|
| Entity domain | `sensor` | `sensor` |
| Translation key | `midday_sell_window` | `midday_sell_window_tomorrow` |
| State when available | Text in `HH:MM-HH:MM` format | Text in `HH:MM-HH:MM` format |
| `price` when available | Rounded float average in PLN/kWh | Rounded float average in PLN/kWh |
| State when insufficient data | `unavailable` | `unavailable` |
| `price` when unavailable | Omitted | Omitted |
| Tie-break rule | Earliest start time wins when total cost is equal | Earliest start time wins when total cost is equal |
| Day scope | Current local day only | Next local day only |
| Price scope | `sell-price sensor` only; buy-price changes must not affect the result | `sell-price sensor` only; buy-price changes must not affect the result |

## Update Contract

- Each sensor recalculates when its underlying day-scoped price-series payload changes and during the normal integration refresh path.
- A change affecting only one day payload must not overwrite or invalidate the other day sensor unless its own payload also changes.
- The sensors do not require user service calls or manual recalculation.
- The feature does not require feature-specific persistence across restarts.

## Error Semantics

| Condition | Result |
|-----------|--------|
| Fewer than 8 contiguous valid quarter-hour slots in 08:00-16:00 after hourly expansion for a given day payload | The corresponding sensor becomes `unavailable` |
| Non-numeric required price point inside a candidate window | The corresponding sensor becomes `unavailable` |
| Multiple windows share the same minimum total cost | The earliest valid window is published for that day |
| Buy-price source changes only | No output change attributable to buy-price data |
| Sensor state is `unavailable` | The corresponding `price` attribute is omitted |