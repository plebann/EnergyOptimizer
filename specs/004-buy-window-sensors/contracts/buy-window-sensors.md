# Contract: Buy Window Sensors

## Interface Type

Four additional Home Assistant sensor entities published by the `energy_optimizer` integration.

## Purpose

Expose the best two-hour buy windows for:

- today night,
- today day,
- tomorrow night,
- tomorrow day,

using buy-price data only, while publishing the selected best-window start time as sensor state and the derived average price plus negative-price flag as attributes, without replacing any existing sensor entities.

## Input Contract

The implementation reads hourly buy-price payloads from coordinator-managed shared state already maintained by the integration.

Expected payload shapes from the configured buy-price source entity:

| Field | Required | Meaning |
|-------|----------|---------|
| `prices_today` | yes for today sensors | Collection of hourly price entries for the current local day |
| `prices_today[].time` | yes | Timestamp for the represented full-hour start |
| `prices_today[].price` | yes | Buy price used for candidate averaging |
| `prices_tomorrow` | yes for tomorrow sensors | Collection of hourly price entries for the next local day |
| `prices_tomorrow[].time` | yes | Timestamp for the represented full-hour start |
| `prices_tomorrow[].price` | yes | Buy price used for candidate averaging |

Each input entry represents one one-hour price segment. Candidate starts are limited to full hours only, and each published two-hour candidate requires two contiguous valid hourly records.

The payloads are consumed from coordinator-managed shared state rather than by directly reading source entity attributes inside the derived sensor code.

## Output Contract

| Property | Today night | Today day | Tomorrow night | Tomorrow day |
|----------|-------------|-----------|----------------|--------------|
| Entity domain | `sensor` | `sensor` | `sensor` | `sensor` |
| Translation key | `night_buy_window` | `day_buy_window` | `night_buy_window_tomorrow` | `day_buy_window_tomorrow` |
| Evaluated range | `00:00-06:00` | `10:00-18:00` | `00:00-06:00` | `10:00-18:00` |
| State when available | `HH:MM` best start | `HH:MM` best start | `HH:MM` best start | `HH:MM` best start |
| `price` when available | Rounded float average price, 3 decimals | Rounded float average price, 3 decimals | Rounded float average price, 3 decimals | Rounded float average price, 3 decimals |
| `is_negative` when available | Boolean derived from average price < 0 | Boolean derived from average price < 0 | Boolean derived from average price < 0 | Boolean derived from average price < 0 |
| State when insufficient data | `unavailable` | `unavailable` | `unavailable` | `unavailable` |
| Price scope | Buy-price payload only; sell-price changes must not affect result | Buy-price payload only; sell-price changes must not affect result | Buy-price payload only; sell-price changes must not affect result | Buy-price payload only; sell-price changes must not affect result |

## Update Contract

- Each sensor recalculates during the existing integration refresh/listener path when its underlying buy-price payload snapshot changes.
- A change affecting only one day or one range must not overwrite or invalidate the other three sensors unless their own slice changes.
- The sensors do not require user service calls or feature-specific persistence.
- The four buy-window sensors are added beside the existing pricing sensor set; sell-window and midday sell-window sensors remain unchanged.

## Error Semantics

| Condition | Result |
|-----------|--------|
| No complete valid two-hour candidate in the sensor's day/range slice | The corresponding sensor becomes `unavailable` |
| `prices_tomorrow` is an empty list | Both tomorrow sensors become `unavailable` |
| Required `time` or `price` missing inside the evaluated slice | The affected candidate is invalid, and the corresponding sensor becomes `unavailable` if no valid candidate remains |
| `price` is non-numeric inside the evaluated slice | The affected candidate is invalid, and the corresponding sensor becomes `unavailable` if no valid candidate remains |
| Multiple night candidates share the same minimum average price | The candidate ending closest to `06:00` wins |
| Multiple day candidates share the same minimum average price | The candidate starting closest to `13:00` wins; if still tied, the earlier start wins |
| Selected average price equals `0` | Sensor remains available and `is_negative` is `false` |
| Sell-price source changes only | No output change attributable to sell-price data |

## Notes

- For these four new sensors, state is a single start time `HH:MM` because end time is implied by the fixed two-hour duration.
- Existing pricing sensors retain their current contracts and are not redefined by this document.
- The contract intentionally favors deterministic outputs over partial publication when data is incomplete or unreliable.