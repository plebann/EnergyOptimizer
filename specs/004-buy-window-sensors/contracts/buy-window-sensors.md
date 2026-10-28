# Contract: Buy Window Sensors

## Interface Type

Four additional Home Assistant sensor entities published by the `energy_optimizer` integration.

## Purpose

Expose the cheapest buy windows, seeded from the best two-hour period and expanded
with adjacent qualifying hours, for:

- today night,
- today day,
- tomorrow night,
- tomorrow day,

using buy-price data only, while publishing the selected best-window start time as sensor state and the derived average price plus negative-price flag as attributes, without replacing any existing sensor entities.

Night windows are persisted plans rather than stateless calendar-day projections.

## Input Contract

The implementation reads hourly buy-price payloads from coordinator-managed shared state already maintained by the integration.

Expected payload shapes from the configured buy-price source entity:

| Field | Required | Meaning |
|-------|----------|---------|
| `prices` | required for night-plan creation | Combined collection of timestamped hourly buy-price entries |
| `prices[].time` | yes | Timezone-aware timestamp for the represented full-hour start |
| `prices[].price` | yes | Buy price used for candidate averaging |

Each input entry represents one one-hour price segment. Candidate starts are limited to full hours only, and each published two-hour candidate requires two contiguous valid hourly records.

The payloads are consumed from coordinator-managed shared state rather than by directly reading source entity attributes inside the derived sensor code.

## Output Contract

| Property | Today night | Today day | Tomorrow night | Tomorrow day |
|----------|-------------|-----------|----------------|--------------|
| Entity domain | `sensor` | `sensor` | `sensor` | `sensor` |
| Translation key | `night_buy_window` | `day_buy_window` | `night_buy_window_tomorrow` | `day_buy_window_tomorrow` |
| Evaluated range | current/last planned night | `09:00-17:00` | next planned night | `09:00-17:00` |
| State when available | `HH:MM-HH:MM` selected window | `HH:MM-HH:MM` selected window | `HH:MM-HH:MM` selected window | `HH:MM-HH:MM` selected window |
| `price` when available | Rounded float average price, 3 decimals | Rounded float average price, 3 decimals | Rounded float average price, 3 decimals | Rounded float average price, 3 decimals |
| `is_negative` when available | Boolean derived from average price < 0 | Boolean derived from average price < 0 | Boolean derived from average price < 0 | Boolean derived from average price < 0 |
| `start_time` / `end_time` when available | ISO 8601 timestamp with offset | ISO 8601 timestamp with offset | ISO 8601 timestamp with offset | ISO 8601 timestamp with offset |
| State when insufficient data | `unavailable` | `unavailable` | `unavailable` | `unavailable` |
| Price scope | Buy-price payload only; sell-price changes must not affect result | Buy-price payload only; sell-price changes must not affect result | Buy-price payload only; sell-price changes must not affect result | Buy-price payload only; sell-price changes must not affect result |

## Update Contract

- Each sensor recalculates during the existing integration refresh/listener path when its underlying buy-price payload snapshot changes.
- A change affecting only one day or one range must not overwrite or invalidate the other three sensors unless their own slice changes.
- The sensors do not require user service calls or feature-specific persistence.
- The four buy-window sensors are added beside the existing pricing sensor set; sell-window and consume-window sensors remain unchanged.

## Error Semantics

| Condition | Result |
|-----------|--------|
| No hourly buy-price data in the sensor's day/range slice | The corresponding sensor becomes `unavailable` |
| `prices_tomorrow` is an empty list | Both tomorrow sensors become `unavailable` |
| Required `time` or `price` missing inside the evaluated slice | The affected candidate is invalid, and the corresponding sensor becomes `unavailable` if no valid candidate remains |
| `price` is non-numeric inside the evaluated slice | The affected candidate is invalid, and the corresponding sensor becomes `unavailable` if no valid candidate remains |
| Multiple night candidates share the same minimum average price | The candidate ending closest to `06:00` wins |
| Multiple day candidates share the same minimum average price | The candidate starting closest to `13:00` wins; if still tied, the earlier start wins |
| After selecting the cheapest two-hour night candidate | Expand continuously on either side while each adjacent hourly price is at most 110% of the initial candidate average and the window remains inside `22:00-06:00` |
| Selected average price equals `0` | Sensor remains available and `is_negative` is `false` |
| Sell-price source changes only | No output change attributable to sell-price data |

## Night-plan lifecycle

- The plan range is continuous local time from `22:00` on the prior day through
  `06:00` on the plan end day. All eight hourly records must be valid and
  present before a plan can be created.
- The first complete source update at or after 14:00 creates the next-night
  plan. Later source updates do not replace that validated plan.
- `night_buy_window_tomorrow` means the active night before 06:01 and the next
  planned night after 06:01. `night_buy_window` represents the active or most
  recently completed night.
- Rotation occurs at 06:01 local time. Between rotation and the first valid
  post-14:00 plan, the future sensor is unavailable.
- Plans contain absolute timezone-aware timestamps and survive Home Assistant
  restarts. A malformed refresh cannot overwrite a previously validated plan.

## Notes

- For these four sensors, the state is the complete selected range and `start_time` plus `end_time` retain the complete local timestamps.
- Existing pricing sensors retain their current contracts and are not redefined by this document.
- The contract intentionally favors deterministic outputs over partial publication when data is incomplete or unreliable.
