# Quickstart: Inverter Off-Grid Mode on Zero Sell Price

**Feature**: `005-inverter-offgrid-zero-price`
**Date**: 2026-06-20

## What This Feature Does

When sell prices are effectively zero (< 0.05 PLN/kWh; rounds to 0.0 at 1 decimal place), instead of limiting export power via the surplus switch, the integration now switches the inverter to **off-grid (island) mode** by turning ON a dedicated Inverter OffGrid switch entity. When prices recover, the switch is turned OFF, reconnecting the inverter to the grid.

The feature is **opt-in**: it only activates when the Inverter OffGrid switch is configured. Existing setups using only the export-surplus switch continue to work unchanged.

---

## Setup Steps

### 1. Configure the Inverter OffGrid switch entity

Create or identify a HA switch entity that controls your inverter's grid-connection mode:

- `switch.state == "off"` → inverter is grid-connected (normal)
- `switch.state == "on"` → inverter is in off-grid/island mode

For **Solarman** inverters this is typically a Modbus register toggle exposed via `ha-solarman`. For other inverters, use any compatible switch entity.

### 2. Set it in the integration Options

In Home Assistant → Settings → Devices & Services → Energy Optimizer → **Configure**:

1. Navigate to the **Control Entities** step.
2. Set **Inverter OffGrid Switch** to your switch entity.
3. Save.

No HA restart required.

### 3. Verify behavior

With the switch configured:

- When sell price < 0.05 (rounds to 0.0) → the switch turns ON (off-grid mode).
- When sell price ≥ 0.05 (rounds above 0.0) → the switch turns OFF (grid reconnect).
- At night (sun below horizon) → no action, regardless of price.

---

## Testing

Run export-block-control tests in WSL:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc \
  'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; \
   ./.venv-wsl/bin/python -m pytest tests/test_export_block_control.py -v'
```

---

## Rollback / Opt-out

Remove the **Inverter OffGrid Switch** entity from Options → Control Entities (clear the field). The integration reverts to the export-surplus switch behavior immediately.
