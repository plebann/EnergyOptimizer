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

### Arbitrage Margin

The difference between a Sell Window's price and the price of its paired Arbitrage Buy Reference. EnergyOptimizer only
treats extra grid charging or a high-price sell as profitable arbitrage when this margin exceeds the configured
minimum threshold (`min_arbitrage_price`). The margin acts strictly as an on/off gate — it does not scale the
arbitrage energy volume, which remains capacity-derived.

### Arbitrage Buy Reference

The Buy Window whose price is used as the buy side of an Arbitrage Margin calculation. Morning Charge, Morning Sell,
and Evening Sell scenarios use the Night Buy Window as their Arbitrage Buy Reference. Afternoon Charge uses the Day
Buy Window (best 2h window, 10:00-16:00; unchanged). If the Arbitrage Buy Reference price is unavailable, the
Arbitrage Margin cannot be computed and the gate fails closed (no arbitrage / no high-price sell).

### Solar Charge Block

A control action that temporarily prevents PV energy from charging the battery when exporting that PV energy is more valuable than storing it. Solar Charge Block is not a Forced Battery Discharge.

### Forced Battery Discharge

A deliberate control action that lowers battery state of charge by selling or otherwise using energy already stored in the battery.
_Avoid_: Emptying the battery

### Safety SOC Floor

The configured minimum battery state of charge that an EnergyOptimizer decision must preserve. `min_soc` is the default floor; `min_soc_pv` applies only when the decision confirms sufficient PV energy for the relevant horizon.
_Avoid_: Program SOC safety level

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
