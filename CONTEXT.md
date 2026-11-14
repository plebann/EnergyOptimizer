# EnergyOptimizer Context

## Glossary

### Market Window

A time window chosen from energy market or tariff information for EnergyOptimizer decisions. Market Window is the umbrella term for buy windows, sell windows, midday price windows, and high-tariff windows.

### Buy Window

A Market Window selected because buying energy during that window is favorable.

### Sell Window

A Market Window selected because exporting energy during that window is favorable.

### Morning Sell Window

A Sell Window selected from the morning price peak. EnergyOptimizer uses it as the morning export opportunity and as a reference point for later PV charging decisions.

### Consume Window

A Market Window selected because consuming energy during that window is favorable, so EnergyOptimizer may enable or prioritize consumption-oriented behavior.
_Avoid_: Midday Sell Window

### High-Tariff Window

A Market Window describing the high-tariff period that EnergyOptimizer plans around.

### Ranked Market Window

A Market Window selected from an ordered set of candidate windows.

### Primary Market Window

The first selected Ranked Market Window.

### Secondary Market Window

The next selected Ranked Market Window after the Primary Market Window.

### Market Window Source

A source of information used to resolve a Market Window.

### Resolved Market Window

A Market Window that EnergyOptimizer can use for a decision.

### Unavailable Market Window

A Market Window that cannot be resolved because the needed information is missing or unavailable.

### Unreliable Market Window

A Market Window that should not be used because the available information is invalid, duplicated, or contradictory.

### Default Market Window

A Resolved Market Window built from EnergyOptimizer's configured default hours because no Market Window Source could
supply one. It is always marked as a fallback so a decision can tell it apart from a window resolved from data.
_Avoid_: Fallback hour, default hour

### Sell Window Ranking

The pair of a Primary Market Window and its optional Secondary Market Window that a sell decision chooses between.
In code this pair is the `RankedMarketWindow` type; a Default Market Window ranking has no Secondary Market Window.
_Avoid_: Ranked pair, window tuple

### Market Window Resolver

The single place EnergyOptimizer asks which Resolved Market Window of each kind applies at a given moment. Decisions,
the scheduler and the window sensors all read the same answer; nothing reads a Market Window back from a sensor.
_Avoid_: Window helper, internal sensor lookup

### Arbitrage Margin

The difference between a Sell Window's price and the price of its paired Arbitrage Buy Reference. EnergyOptimizer only
treats extra grid charging or a high-price sell as profitable arbitrage when this margin exceeds the configured
minimum threshold (`min_arbitrage_price`). The margin acts strictly as an on/off gate — it does not scale the
arbitrage energy volume, which remains capacity-derived.

### Arbitrage Buy Reference

The Market Window whose price is used as the buy side of an Arbitrage Margin calculation. Morning Charge and Evening
Sell use the Night Buy Window; Morning Sell uses the Morning Sell Buy Reference; Afternoon Charge uses the Day Buy
Window. If the Arbitrage Buy Reference price is unavailable, the Arbitrage
Margin cannot be computed and the gate fails closed (no arbitrage / no high-price sell).

### Morning Sell Buy Reference

The Market Window spanning the hour after the Morning Sell Window up to the end of the High-Tariff Window, priced at
the average buy price over that span. It is the Arbitrage Buy Reference for Morning Sell, because energy sold in the
morning peak is bought back during that span, not in the Night Buy Window.
_Avoid_: Night Buy Window (for Morning Sell), restore-hour buy price

### Solar Charge Block

A control action that temporarily prevents PV energy from charging the battery when exporting that PV energy is more valuable than storing it. Solar Charge Block is not a Forced Battery Discharge.

### Forced Battery Discharge

A deliberate control action that lowers battery state of charge by selling or otherwise using energy already stored in the battery.
_Avoid_: Emptying the battery

### Safety SOC Floor

The configured minimum battery state of charge that an EnergyOptimizer decision must preserve. `min_soc` is the default floor; `min_soc_pv` applies only when the decision confirms sufficient PV energy for the relevant horizon. For sell decisions the floor is also a feasibility boundary: a calculated target that would sell below it is refused as no action rather than converted into a valid sell.
_Avoid_: Program SOC safety level

### Charge Base

The effective state of charge from which EnergyOptimizer calculates the temporary Morning Charge target. When the battery SOC reported at decision time is below the current Safety SOC Floor, the Charge Base is the Safety SOC Floor; otherwise it equals the reported SOC.
_Avoid_: Virtual SOC, Clamped SOC

### Charge Target Safety Margin

The fixed percentage point (currently 1 point) added to a calculated charge target SOC after rounding it up, before the result is capped at the configured `max_soc`. It applies to the Morning Charge temporary Program 2 target and the Afternoon Charge Program 4 target; sell/discharge targets are unaffected.
_Avoid_: margin (forecast demand multiplier), Arbitrage Margin

### Program 2 Normal SOC Target

The Program 2 SOC value used after a temporary Morning Charge target ends: `min_soc`.
_Avoid_: Restored Program 2 SOC

### Morning Charge Completion

The instant at the end of the resolved Night Buy Window when the temporary Morning Charge target no longer applies.
_Avoid_: Target SOC reached

### Program 2 Morning Synchronization

The scheduler updates Program 2's start time only alongside an actual Morning Charge SOC change; it leaves the start time unchanged when the SOC remains unchanged.
_Avoid_: Unconditional Program 2 start update

### Program 2 Start Control

A writable `time` or `input_datetime` entity that holds Program 2's start time.
_Avoid_: Read-only program time sensor

### Program SOC Update

A decision outcome that records an actual write to a program's SOC control, rather than a no-action result.
_Avoid_: SOC change reported as no action

### Morning Charge Schedule Log

A concise record of a Morning Charge schedule change containing Program 2 SOC and the resolved Night Buy Window start and end.
_Avoid_: Forecast and energy diagnostic log

### Afternoon Charge Completion

The instant at the end of the resolved Day Buy Window when Program 4 is set to the lower of the current battery SOC and `min_soc_pv`.
_Avoid_: Program 4 solar reset

### Night Buy Window

A Buy Window within 00:00-06:00, seeded from the cheapest two consecutive hours in that range, then grown outward one
boundary hour at a time on either side while each boundary hour's price stays within 10% of the window's current
average price (recomputed after every accepted hour). Expansion stops permanently on a side once its next boundary
hour exceeds the 10% threshold or falls outside 00:00-06:00; a Night Buy Window may end up spanning the full 6-hour
range. Morning Charge starts at the Night Buy Window's start hour and charges for its full (variable) duration.

### Day Buy Window

A Buy Window inside the low-tariff range that runs from the High-Tariff Window's end hour to its start hour (the
`high_tariff_end_hour_sensor` and `high_tariff_start_hour_sensor` values at planning time; 13:00-15:00 when a sensor is
unavailable). It is seeded from the cheapest two consecutive full hours in that range, then grown by adjacent hours
priced within 2% of the window average without leaving the range; price ties pick the earlier start. A range shorter
than two hours yields no Day Buy Window, and without one Afternoon Charge is skipped rather than run at fallback hours.
Afternoon Charge starts at the Day Buy Window's start and Afternoon Charge Completion happens at its end.

### Secure Energy

A decision that sets the relevant inverter program SOC above the current battery SOC to preserve a calculated energy
reserve through its decision horizon, without scheduling grid charging. It requires an independent reserve signal at
an effective gap at or below the common 0.001 kWh epsilon. Morning Charge: the needed reserve exceeds the epsilon and
the target SOC is above the current SOC (the Charge Target Safety Margin may lift that target). Afternoon Charge: the
unrounded forecast peak SOC in the Day Buy Window, before rounding and the margin, exceeds the current SOC by more than
the epsilon in kWh, and the final written target, after the margin and the `max_soc` cap, is above the current SOC. A
target produced only by technical SOC rounding or a safety margin, with neither signal, is not
Secure Energy. At the end of the window it restores only the program SOC; it never changes the grid-charge current.

### Charge Decision Type

The business classification of a Morning Charge or Afternoon Charge decision: `charge` for an effective energy gap
above the common 0.001 kWh epsilon, `secure_energy` for a no-grid-charge decision that raises the program SOC above the
current SOC on an independent reserve signal (see Secure Energy), or `no_action` otherwise. Avoid technical write-oriented
labels such as `charge_scheduled`, `program_soc_updated`, and `program_settings_updated` for these decisions.
