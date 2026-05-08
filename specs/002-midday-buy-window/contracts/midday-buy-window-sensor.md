# Contract: Midday Buy Window Sensor

## Interface Type

Home Assistant sensor entity published by the `energy_optimizer` integration.

## Purpose

Expose the cheapest purchase-price window of length 8 quarter-hours between 08:00 and 16:00 for the current local day.

## Input Contract

The implementation reads the configured current-day price-series source already used by the integration for electricity pricing.

Expected payload shape from the source entity:

| Field | Required | Meaning |
|-------|----------|---------|
| `prices` | yes | Collection of quarter-hour price entries |
| `prices[].dtime` | yes | Timestamp for the slot |
| `prices[].period` | yes | Human-readable period such as `12:00 - 12:15` |
| `prices[].rce_pln` | yes | Purchase-price value used for comparison |
| `prices[].business_date` | yes | Business date for current-day filtering |

## Output Contract

| Property | Contract |
|----------|----------|
| Entity domain | `sensor` |
| Translation key | `midday_buy_window` |
| State when available | Text in `HH:MM-HH:MM` format |
| State when insufficient data | `unavailable` |
| Tie-break rule | Earliest start time wins when total cost is equal |
| Day scope | Current local day only |
| Price scope | Purchase price only; sell-price changes must not affect the result |

## Update Contract

- The sensor recalculates when the underlying price-series source changes and during the normal integration refresh path.
- The sensor does not require user service calls or manual recalculation.
- The feature does not require feature-specific persistence across restarts.

## Error Semantics

| Condition | Result |
|-----------|--------|
| Fewer than 8 contiguous valid quarter-hour slots in 08:00-16:00 | `unavailable` |
| Non-numeric required price point inside a candidate window | `unavailable` |
| Multiple windows share the same minimum total cost | Earliest valid window is published |
| Sell-price source changes only | No output change attributable to sell-price data |
