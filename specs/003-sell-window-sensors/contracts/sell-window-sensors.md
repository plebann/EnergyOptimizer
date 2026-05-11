# Contract: Ranked Sell Window Sensors

## Interface Type

Four additional Home Assistant sensor entities published by the `energy_optimizer` integration.

## Purpose

Expose the best and second-best one-hour sell windows for:

- today morning,
- today evening,
- tomorrow morning,
- tomorrow evening,

using sell-price data only, while publishing the selected best-window start time as sensor state and the runner-up comparison as attributes, without replacing any existing sensor entities.

## Input Contract

The implementation reads hourly sell-price payloads from coordinator-managed shared state already maintained by the integration.

Expected payload shapes from the configured sell-price source entity:

| Field | Required | Meaning |
|-------|----------|---------|
| `prices_today` | yes for today sensors | Collection of hourly price entries for the current local day |
| `prices_today[].time` | yes | Timestamp for the represented full hour start |
| `prices_today[].price` | yes | Sell price used for ranking |
| `prices_tomorrow` | yes for tomorrow sensors | Collection of hourly price entries for the next local day |
| `prices_tomorrow[].time` | yes | Timestamp for the represented full hour start |
| `prices_tomorrow[].price` | yes | Sell price used for ranking |

Each input entry represents exactly one one-hour candidate window. Candidate starts are limited to full hours only.

The payloads are consumed from coordinator-managed shared state rather than by directly reading source entity attributes inside the derived sensor code.

## Output Contract

| Property | Today morning | Today evening | Tomorrow morning | Tomorrow evening |
|----------|---------------|---------------|------------------|------------------|
| Entity domain | `sensor` | `sensor` | `sensor` | `sensor` |
| Translation key | `morning_sell_window` | `evening_sell_window` | `morning_sell_window_tomorrow` | `evening_sell_window_tomorrow` |
| Evaluated range | `04:00-10:00` | `16:00-22:00` | `04:00-10:00` | `16:00-22:00` |
| State when available | `HH:MM` best start | `HH:MM` best start | `HH:MM` best start | `HH:MM` best start |
| `price` when available | Rounded float best price, 3 decimals | Rounded float best price, 3 decimals | Rounded float best price, 3 decimals | Rounded float best price, 3 decimals |
| `second_window_start` when available | `HH:MM` | `HH:MM` | `HH:MM` | `HH:MM` |
| `second_window_price` when available | Rounded float, 3 decimals | Rounded float, 3 decimals | Rounded float, 3 decimals | Rounded float, 3 decimals |
| `second_window_gap_pct` when available | Rounded float, 1 decimal unless best price is zero | Rounded float, 1 decimal unless best price is zero | Rounded float, 1 decimal unless best price is zero | Rounded float, 1 decimal unless best price is zero |
| State when insufficient data | `unavailable` | `unavailable` | `unavailable` | `unavailable` |
| Price scope | Sell-price payload only; buy-price changes must not affect result | Sell-price payload only; buy-price changes must not affect result | Sell-price payload only; buy-price changes must not affect result | Sell-price payload only; buy-price changes must not affect result |

## Update Contract

- Each sensor recalculates during the existing integration refresh/listener path when its underlying payload snapshot changes.
- A change affecting only one day or one range must not overwrite or invalidate the other three sensors unless their own slice changes.
- The sensors do not require user service calls or feature-specific persistence.
- The four ranked sensors are added beside the existing sensor set; the old midday sell-window pair remains unchanged.

## Error Semantics

| Condition | Result |
|-----------|--------|
| Fewer than two valid hourly candidates in the sensor's day/range slice | The corresponding sensor becomes `unavailable` |
| Non-numeric required price entry inside the evaluated slice | The corresponding sensor becomes `unavailable` |
| Multiple candidates share the same top sell price | Earlier start time wins best rank; the next later candidate with the same price may become second-best |
| Best candidate price equals `0` | Sensor remains available, but `second_window_gap_pct` is omitted |
| Buy-price source changes only | No output change attributable to buy-price data |

## Notes

- For these four new sensors, state is a single start time `HH:MM`.
- Existing midday sensors retain their own pre-existing state contract and are not redefined by this document.
- The contract intentionally favors deterministic ranked outputs over partial publication when only one candidate exists.