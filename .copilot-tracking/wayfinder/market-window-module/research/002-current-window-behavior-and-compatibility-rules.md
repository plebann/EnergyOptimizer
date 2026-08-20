# Current Market Window Behavior And Compatibility Rules

## Sources

- `custom_components/energy_optimizer/helpers.py`
- `custom_components/energy_optimizer/calculations/price_windows.py`
- `custom_components/energy_optimizer/entities/sensors/pricing.py`
- `custom_components/energy_optimizer/scheduler/action_scheduler.py`
- `custom_components/energy_optimizer/decision_engine/morning_charge.py`
- `custom_components/energy_optimizer/decision_engine/afternoon_charge.py`
- `custom_components/energy_optimizer/decision_engine/morning_sell.py`
- `custom_components/energy_optimizer/decision_engine/evening_sell.py`
- `custom_components/energy_optimizer/decision_engine/solar_charge_block.py`
- `custom_components/energy_optimizer/decision_engine/export_block_control.py`
- `tests/test_price_windows.py`
- `tests/test_pricing_sensors.py`
- `tests/test_helpers.py`
- `tests/test_scheduled_actions.py`
- `tests/test_solar_charge_block.py`
- `tests/test_export_block_control.py`

## Market Window Source Parsing

- Market Window calculations consume coordinator payloads shaped as `coordinator.data["price_payloads"][entity_id]["prices_today" | "prices_tomorrow"]`, where each price entry is a mapping with `time` and `price`; pricing sensors ignore missing, non-list, or empty payloads and publish no result.
- `_parse_entry_time()` accepts `datetime` values and ISO datetime strings, treats naive datetimes as local timezone, converts aware datetimes to local timezone, and returns `None` for unsupported or invalid values.
- Buy Window and Ranked Sell Window extraction require full-hour candidates: minute, second, and microsecond must all be zero.
- Buy Window and Ranked Sell Window extraction isolate the requested business date using `now_local.date()`; today and tomorrow payloads must not leak into each other.
- Duplicate full-hour entries make the affected extraction return no candidates for that evaluated slice. The sensors then publish unavailable/no result for that affected Market Window only.
- Invalid entries are skipped when enough valid candidates remain; if they remove required candidates, the result is unavailable.
- Same-day range filters compare full start/end datetimes against the range. Late hours such as 23:00-00:00 must not leak into morning/night ranges.

## Helper Resolution And Fallbacks

- `get_internal_window_price()` first resolves an integration-owned internal sensor by `entry_id` and `unique_id_suffix`; if that entity id is unavailable and a fallback entity id is configured, it reads the fallback.
- Price-like reads prefer the requested attribute (`price`, `second_window_price`, etc.) when present and not one of `None`, `unknown`, or `unavailable`; if no usable attribute exists, they fall back to the entity state as a float.
- If the requested attribute is present but unavailable, the read returns `None` rather than using the state.
- Missing entity ids log an error for not configured; missing states, unavailable values, and invalid values log warnings and return `None`.
- `_parse_hour_from_state_value()` accepts ISO datetime strings, time strings, and numeric hour values. Datetimes are converted to local time before extracting the hour.
- `_parse_time_from_state_value()` accepts `HH:MM`, `HH:MM:SS`, ISO datetime strings, and `HH:MM-HH:MM` ranges. Ranges resolve to the start time; `unknown`, `unavailable`, and unrecognized strings return `None`.
- `resolve_tariff_end_hour()` reads `CONF_HIGH_TARIFF_END_HOUR_SENSOR`, defaults to 13, and accepts only hours 7 through 24 inclusive.
- `resolve_tariff_start_hour()` reads `CONF_HIGH_TARIFF_START_HOUR_SENSOR`, defaults to 15, and accepts only hours 0 through 23 inclusive.
- `resolve_evening_max_price_hour()` prefers the internal `evening_sell_window` sensor when `entry_id` is supplied, then falls back to `CONF_EVENING_MAX_PRICE_HOUR_SENSOR`, then default 17. Out-of-range values fall back to default.
- `resolve_evening_second_max_price_hour()` prefers the `second_window_start` attribute on the internal `evening_sell_window` sensor, then falls back to `CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR`; invalid, missing, or out-of-range values return `None`.
- `resolve_morning_max_price_hour()` prefers the internal `morning_sell_window` sensor when `entry_id` is supplied, then falls back to `CONF_MORNING_MAX_PRICE_HOUR_SENSOR`, then default 7. Out-of-range values fall back to default.
- `resolve_daytime_min_price_time()` prefers the internal `consume_window` sensor when `entry_id` is supplied, then falls back to `CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR`, then a parsed default time of 12:00. Invalid default strings also fall back to 12:00.

## Buy Window Rules

- Buy Windows are two contiguous full-hour windows built by `build_best_buy_window_result()`.
- Today/tomorrow selection comes from the `now_local` date used by the caller.
- Night Buy Window uses the 00:00-06:00 range. Day Buy Window uses the 10:00-16:00 range.
- The selected Buy Window minimizes average price across two contiguous hours.
- Night tie-breakers are: lower average price, then end time closest to the range end, then latest end time.
- Day tie-breakers are: lower average price, then start time closest to 13:00, then earlier start time.
- A result can have a negative or zero average and still be available.
- Unsupported range keys raise `ValueError`.
- Buy Window sensors publish the start time as `HH:MM`, set `available` false when no result exists, and publish attributes `price` rounded to 3 decimals and `is_negative` based on the unrounded average.
- Buy Window sensors are isolated to the configured buy price entity and ignore sell-price-only changes.

## Ranked Sell Window Rules

- Ranked Sell Windows are one-hour full-hour candidates built by `build_ranked_sell_window_result()`.
- Morning Sell Window uses the 04:00-10:00 range. Evening Sell Window uses the 16:00-22:00 range.
- A result requires at least two valid full-hour candidates.
- Ranking sorts by highest sell price, then earliest start time for ties.
- `second_window_gap_pct` is `(primary_price - secondary_price) / primary_price * 100` and remains internally unrounded; it is omitted when the primary price is zero.
- Duplicate full-hour entries in an evaluated slice make that affected Ranked Sell Window unavailable, but do not necessarily affect another range that does not include the duplicate.
- Ranked Sell Window sensors publish the primary start time as `HH:MM`, set `available` false when no result exists, and publish attributes `price`, `second_window_start`, `second_window_price`, and optionally `second_window_gap_pct`.
- Ranked Sell Window sensor prices are rounded to 3 decimals; `second_window_gap_pct` is rounded to 1 decimal only at publication.
- Ranked Sell Window sensors are isolated to the configured sell price entity and ignore buy-price-only changes.

## Midday Avoidance Window Rules

- Midday Avoidance Windows use hourly sell-price entries expanded into quarter-hour points by `expand_hourly_sell_prices()`; each hour produces four quarter-hour slots.
- Midday filtering keeps quarter-hour slots fully inside 08:00-16:00.
- Prices below `0.05` PLN/kWh are treated as zero during expansion.
- If more than two midday hours are zero-priced, `select_consume_window()` returns a variable-length window from the earliest zero hour start through the latest zero hour end, including non-zero gaps between them.
- Otherwise, `select_consume_window()` returns the cheapest contiguous 8-quarter-hour window; ties keep the earliest start because replacement only happens on strictly lower total cost.
- Missing midday points, fewer than eight contiguous quarter-hour points, or gaps inside a candidate window produce no result.
- `format_consume_window()` publishes `HH:MM-HH:MM`.
- Midday Avoidance Window sensors publish that range as state, and publish `price` rounded to 2 decimals.
- The today Midday Avoidance Window sensor also publishes `is_active` as string `on` or `off`; tomorrow does not publish `is_active`.
- Midday Avoidance Window sensors are isolated to the configured sell price entity and ignore buy-price-only changes.

## Scheduler Compatibility

- `ActionScheduler.start()` registers fixed time actions for morning charge at 04:00:01, evening behavior at 22:00:01, and daily schedule refresh at 00:00:01.
- Afternoon charge is scheduled two hours before the resolved high-tariff start hour.
- Morning sell is scheduled at the resolved Morning Sell Window hour.
- Evening primary sell is scheduled at the resolved primary Evening Sell Window hour; a secondary listener is added only when a secondary hour resolves.
- Sell restore listeners run one hour after the resolved morning sell hour and one hour after the later/effective evening sell hour. With a secondary evening hour, the evening restore source and time use the secondary hour only when it is at or after the primary hour.
- Daytime min price restore is scheduled at the resolved Midday Avoidance Window time.
- Scheduler registers state-change listeners for the high-tariff start sensor and for integration-owned `evening_sell_window`, `morning_sell_window`, and `consume_window` sensors when those internal entity ids exist.
- Only one state-change listener is registered for the shared evening sell sensor.
- Hourly price-driven controls run at minute 1 during daylight only; sunrise enables the listener and sunset disables it.
- Hourly price-driven controls call `solar_charge_block`, wait five seconds, then call `export_block_control`.
- Scheduled action snapshots repeat the same helper resolution rules and publish fixed, dynamic, derived restore, and event-driven entries with stable keys, labels, source strings, local times, ordering, and summary counts.

## Decision Engine Compatibility

- Morning Charge gathers forecasts from 06:00 to the resolved high-tariff end hour and uses the resolved Morning Sell Window hour when computing optional morning arbitrage.
- Morning Charge reads the Morning Sell Window price via `get_internal_window_price()` with fallback `CONF_MORNING_MAX_PRICE_SENSOR`; missing price records `arbitrage_reason = missing_morning_sell_price`.
- Afternoon Charge gathers forecasts from the resolved high-tariff start hour to 22:00 and uses the resolved Evening Sell Window hour when computing optional arbitrage.
- Afternoon Charge reads the Evening Sell Window price via `get_internal_window_price()` with fallback `CONF_EVENING_MAX_PRICE_SENSOR`; missing price records `arbitrage_reason = missing_sell_price`.
- Morning Sell reads the Morning Sell Window price and hour through helpers. If the price is unavailable, it sets price to 0, marks `_price_unavailable`, and continues with surplus-over-space behavior.
- Morning Sell also reads the Evening Sell Window price for morning-vs-evening surplus selection; if that price is unavailable, the selection falls back to overflow/surplus behavior.
- Evening Sell resolves primary and secondary Evening Sell Window context through helpers. It reads primary `price` or secondary `second_window_price` via `get_internal_window_price()` and falls back to configured max/second max sensors.
- Evening Sell reads Tomorrow Morning Sell Window price via `morning_sell_window_tomorrow` with configured fallback; unavailable tomorrow price skips the tomorrow comparison rather than aborting.
- Solar Charge Block uses current buy price first, then sell price, then legacy price sensor. It reads the Midday Avoidance Window price and time through helpers; missing current price, missing min price, or current time at/after the min price time all skip action.
- Export Block Control does not use Market Window sensors. It reads current sell or legacy price directly, runs only during daylight, and uses `round(price, 1)` to decide off-grid/export behavior.

## Warning And Unavailable Behavior

- Helper reads distinguish missing configuration, missing state, unavailable state/attribute, and invalid values through logs, but caller behavior generally treats all of them as `None`.
- Pricing sensors clear native value and attributes when no result exists. Buy and Ranked Sell sensors also expose `available = False` when no result exists; Midday Avoidance sensors do not override availability and instead publish `None` state with empty attributes.
- Duplicate entries are treated as Unreliable Market Window input for Buy and Ranked Sell calculations; invalid individual entries are skipped unless they make the result impossible.
- Zero and negative prices are valid where calculation rules allow them; they must not automatically make a Market Window unavailable.

## Compatibility Tests To Preserve

- `tests/test_price_windows.py` is the behavior contract for calculation functions: day isolation, range filtering, duplicate handling, contiguity requirements, tie-breakers, zero-price expansion, negative/zero buy averages, and internal-vs-published precision.
- `tests/test_pricing_sensors.py` is the behavior contract for sensor state, attributes, availability, translation keys, unique ids, today/tomorrow isolation, and payload update behavior.
- `tests/test_helpers.py` is the behavior contract for parsing `HH:MM`, `HH:MM:SS`, ISO datetimes, `HH:MM-HH:MM` ranges, internal sensor preference, configured fallback entities, defaults, and `None` returns.
- `tests/test_scheduled_actions.py` is the behavior contract for Scheduler listener registration, daylight hourly controls, fixed/dynamic/derived/event-driven snapshot entries, and evening A/B flag passing.
- `tests/test_solar_charge_block.py` and `tests/test_export_block_control.py` cover current-price decision-engine compatibility that must not be accidentally folded into Market Window behavior without an explicit later decision.