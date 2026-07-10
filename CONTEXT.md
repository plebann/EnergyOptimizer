# EnergyOptimizer Context

## Glossary

### Market Window

A time window chosen from energy market or tariff information for EnergyOptimizer decisions. Market Window is the umbrella term for buy windows, sell windows, midday price windows, and high-tariff windows.

### Buy Window

A Market Window selected because buying energy during that window is favorable.

### Sell Window

A Market Window selected because exporting energy during that window is favorable.

### Midday Avoidance Window

A Market Window selected because exporting energy during that window is unfavorable, so EnergyOptimizer may avoid or limit export-oriented behavior.

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

### Night Buy Window

A Buy Window within 00:00-06:00, seeded from the cheapest two consecutive hours in that range, then grown outward one
boundary hour at a time on either side while each boundary hour's price stays within 10% of the window's current
average price (recomputed after every accepted hour). Expansion stops permanently on a side once its next boundary
hour exceeds the 10% threshold or falls outside 00:00-06:00; a Night Buy Window may end up spanning the full 6-hour
range. Morning Charge starts at the Night Buy Window's start hour and charges for its full (variable) duration.
