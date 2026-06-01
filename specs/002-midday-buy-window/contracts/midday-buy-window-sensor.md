# Contract: Midday Buy Window Sensors

## Interface Type

Two Home Assistant sensor entities published by the `energy_optimizer` integration.

## Purpose

Expose the selected midday buy window between `08:00` and `16:00` for:

- the current local day,
- the next local day,

using buy-price data only, while preserving the existing `HH:MM-HH:MM` text-state behavior and adding informational attributes for the selected average price and, for today only, active-window status.

## Input Contract

The implementation reads day-scoped hourly buy-price payloads from coordinator-managed shared state already maintained by the integration.

Expected payload shapes from the configured buy-price source entity:

| Field | Required | Meaning |
|-------|----------|---------|
| `prices_today` | yes for current-day sensor | Collection of hourly buy-price entries for the current local day |
| `prices_today[].time` | yes | Timestamp for the represented full-hour start |
| `prices_today[].price` | yes | Buy-price value used for midday selection |
| `prices_tomorrow` | yes for tomorrow sensor | Collection of hourly buy-price entries for the next local day |
| `prices_tomorrow[].time` | yes | Timestamp for the represented full-hour start |
| `prices_tomorrow[].price` | yes | Buy-price value used for midday selection |

Each input slot is one hour long. During calculation, each hour is interpreted as four consecutive quarter-hour slots with the same price value.

The payloads are consumed from coordinator-managed shared state rather than by directly reading source entity attributes inside derived sensor code.

## Output Contract

| Property | Current-day sensor | Tomorrow sensor |
|----------|--------------------|-----------------|
| Entity domain | `sensor` | `sensor` |
| Translation key | `midday_buy_window` | `midday_buy_window_tomorrow` |
| State when available | Text in `HH:MM-HH:MM` format | Text in `HH:MM-HH:MM` format |
| `price` when available | Rounded float average in PLN/kWh | Rounded float average in PLN/kWh |
| `is_active` when available | `on` when current local time is inside the published window, otherwise `off` | Omitted |
| State when insufficient data | `unavailable` | `unavailable` |
| `price` when unavailable | Omitted | Omitted |
| `is_active` when unavailable | Omitted | Omitted |
| Day scope | Current local day only | Next local day only |
| Price scope | Buy-price payload only; sell-price changes must not affect the result | Buy-price payload only; sell-price changes must not affect the result |

## Selection Contract

1. The evaluated range is limited to the local midday interval `08:00-16:00`.
2. If the evaluated day contains at least one buy-price entry below `0.05 PLN/kWh`, the published window MUST cover the full span from the first to the last such occurrence in that day.
3. If no such quasi-zero entry exists, the published window MUST be the cheapest contiguous 8-quarter-hour / 2-hour midday window.
4. When multiple standard windows share the same minimum cost, the earliest valid window wins.
5. The published `price` attribute MUST equal the arithmetic mean of the selected window and MUST be rounded to 2 decimal places.

## Update Contract

- Each sensor recalculates during the existing integration refresh/listener path when its underlying buy-price payload snapshot changes.
- A change affecting only one day payload must not overwrite or invalidate the other day sensor unless its own payload also changes.
- The current-day sensor may also refresh its `is_active` presentation when the current local time moves into or out of the already-selected window.
- The sensors do not require user service calls or feature-specific persistence.
- The two midday buy-window sensors are added beside the rest of the pricing sensor set without replacing existing entities.

## Error Semantics

| Condition | Result |
|-----------|--------|
| No valid day-scoped buy-price payload for the sensor's evaluated day | The corresponding sensor becomes `unavailable` |
| Required `time` or `price` missing inside the evaluated slice | The affected day result is invalid, and the corresponding sensor becomes `unavailable` if no valid result remains |
| `price` is non-numeric or duplicate hour entries make the day ambiguous | The affected day result is invalid, and the corresponding sensor becomes `unavailable` |
| Fewer than 2 contiguous hourly entries remain for a standard midday window on a day without quasi-zero prices | The corresponding sensor becomes `unavailable` |
| At least one quasi-zero entry exists in the day | The full first-to-last quasi-zero span is published instead of the standard 2-hour selector |
| Multiple standard windows share the same minimum average price | The earliest valid window is published |
| Sensor state is `unavailable` | The corresponding dependent attributes are omitted |
| Sell-price source changes only | No output change attributable to sell-price data |

## Notes

- For these two sensors, state remains a text range `HH:MM-HH:MM` because the integration already publishes midday windows that way.
- `is_active` is intentionally scoped to the current-day sensor only.
- Existing non-midday pricing sensors retain their current contracts and are not redefined by this document.
