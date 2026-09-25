# Morning Charge computes its target from the Charge Base and sizes current for total window energy

When the battery SOC reported at decision time is below the Safety SOC Floor, the Morning Charge gap was priced as if the battery were already at the floor, but the temporary Program 2 target was derived from the raw reported SOC — so the inverter could be left charging to a target below the floor — and the charge current was sized only for the gap above the floor, ignoring the energy needed to reach the floor within the Night Buy Window. We decided to compute the target from the Charge Base, defined as the maximum of the reported SOC and the current Safety SOC Floor (`min_soc_pv` when PV sufficiency is reached, otherwise `min_soc`), and to size the charge current for the total energy delivered in the window (gap plus fill-to-floor energy). The raw reported SOC stays in use everywhere else (reserve/gap math, arbitrage, outcome reporting), and runs with reported SOC at or above the floor are byte-for-byte unchanged.

## Considered Options

- Clamping the input SOC before evaluation (in the shared charge run path): rejected — it re-bases gap, arbitrage, and outcome reporting on a virtual value instead of only correcting the target derivation.
- Flooring inside the pure target computation: rejected — existing tests pin its unbounded arithmetic, and a floor there would not correct the current sizing.
- Fixed `min_soc` as the target floor: rejected in favor of the dynamic Safety SOC Floor, matching the domain semantics of `min_soc_pv`; issue #51's acceptance criterion 1 was reworded from "≥ min_soc" to "≥ current Safety SOC Floor".

## Consequences

- The no-action path's known `min_soc − 4` Program 2 decrement is untouched (tracked separately) — below-floor mornings with a negligible reserve need can still write below `min_soc` through that path.
- With the dynamic floor, a below-floor morning where sufficiency is reached is guaranteed only `≥ min_soc_pv`, by design.
- The shared charge action calculation gains an optional target-floor parameter defaulting to `min_soc`; strategy subclasses supply the scenario-specific floor through a small hook (base defaults to `min_soc`, Morning Charge overrides it with the sufficiency-aware value).
