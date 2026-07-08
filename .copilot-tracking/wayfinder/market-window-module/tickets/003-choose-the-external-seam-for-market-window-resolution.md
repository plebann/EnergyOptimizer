---
title: Choose the external seam for Market Window resolution
labels:
  - wayfinder:grilling
status: closed
assignee: GitHub Copilot
parent: ../map.md
blocked_by:
  - 001-name-the-market-window-domain-language.md
  - 002-inventory-current-window-behavior-and-compatibility-rules.md
  - 006-decide-market-window-result-shape.md
blocks:
  - 004-decide-adapters-and-fallback-policy.md
  - 005-define-migration-and-test-strategy.md
---

## Question

Where should the external seam for Market Window resolution live, and which callers should cross it: pricing sensors, Scheduler, Decision Engine modules, or only a subset at first?

## Resolution

Place the external seam in a new `custom_components/energy_optimizer/market_windows/` package. Pricing sensors, Scheduler, and Decision Engine modules should cross that seam for Market Window behavior, while current-price controls outside Market Window behavior remain outside the seam.

See [Market Window Module Design Decisions](../research/003-006-market-window-module-design-decisions.md#external-seam-decision).
