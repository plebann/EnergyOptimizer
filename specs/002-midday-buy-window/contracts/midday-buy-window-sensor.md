# Contract: Midday Sell Window Sensor

## Interface Type

Home Assistant sensor entity published by the `energy_optimizer` integration.

## Purpose

Expose the cheapest sell-price window of length 8 quarter-hours between 08:00 and 16:00 for the current local day.

## Input Contract

The implementation reads the configured current-day hourly `sell-price sensor` payload from shared integration state already maintained for electricity pricing.

Expected payload shape from the source entity:

| Field | Required | Meaning |
|-------|----------|---------|
| `prices_today` | yes | Collection of hourly price entries |
| `prices_today[].time` | yes | Timestamp for the hour beginning |
| `prices_today[].price` | yes | Sell-price value used for comparison |

Each input slot is 1 hour long. During calculation, each hour is expanded into 4 consecutive quarter-hour slots that all inherit the same price value.

The payload is consumed from shared state maintained by the integration coordinator rather than by directly reading the source entity from the result sensor implementation.

## Output Contract

| Property | Contract |
|----------|----------|
| Entity domain | `sensor` |
| Translation key | `midday_sell_window` |
| State when available | Text in `HH:MM-HH:MM` format |
| State when insufficient data | `unavailable` |
| Tie-break rule | Earliest start time wins when total cost is equal |
| Day scope | Current local day only |
| Price scope | `sell-price sensor` only; buy-price changes must not affect the result |

## Update Contract

- The sensor recalculates when the underlying price-series source changes and during the normal integration refresh path.
- The sensor does not require user service calls or manual recalculation.
- The feature does not require feature-specific persistence across restarts.

## Error Semantics

| Condition | Result |
|-----------|--------|
| Fewer than 8 contiguous valid quarter-hour slots in 08:00-16:00 after hourly expansion | `unavailable` |
| Non-numeric required price point inside a candidate window | `unavailable` |
| Multiple windows share the same minimum total cost | Earliest valid window is published |
| Buy-price source changes only | No output change attributable to buy-price data |
