# Sell decisions treat the Safety SOC Floor as a feasibility boundary, not a clamp target

Sell decisions calculated a raw target SOC, clamped it up to the Safety SOC Floor, and executed the export action even when the requested energy could not fit between the current SOC and the floor — the inverter would be left covering local consumption and could import from the grid. Issue #57 records an observed Morning sell at 19% SOC that clamped a 15.7% target to the 18% floor and still switched to Export First. We decided that a floored target below the floor is infeasible and produces `no_action` with reason "insufficient battery energy above minimum SOC": no inverter work mode, Program SOC, or regulator write, and no sell-restore payload is created or overwritten. Sell targets that floor at or above the floor are byte-for-byte unchanged.

## Considered Options

- Clamping to the floor and executing (pre-existing behavior): rejected — the floor was silently converting an infeasible sell request into a valid one, hiding the shortfall in the logs and risking unwanted grid import.
- Comparing the unrounded raw target (`raw < floor`): rejected — the guard would then compare a quantity the execution never writes, so a decision and its written Program SOC value could diverge.
- Rounding the raw target up before the comparison: rejected — it re-opens a 0.5-point band just below the floor to clamped execution, partially undoing the fix.

## Consequences

- The guard compares the floored raw target (`math.floor(raw_target_soc)`) against the floor — the exact quantity that feeds the written `target_soc = max(floor(raw), floor)` — so decision and write cannot disagree. For integer floors this is identical to issue #57's literal pseudocode; for fractional floors it is slightly more conservative (a raw in `[floor, next integer)` is refused where the literal spec would sell down to the floor). We accept that in exchange for the consistency guarantee.
- The decision replay gains a `floored_raw_target_soc` diagnostic in the `sell_target_soc` step and in the no-action outcome details, so boundary decisions are explainable without reading code.
- The guard lives in the shared `BaseSellStrategy._execute_sell()` tail after the `sell_target_soc` step and before the existing `target_soc >= current_soc` guard, so Morning Sell and Evening Sell (all paths) are covered by one check.
