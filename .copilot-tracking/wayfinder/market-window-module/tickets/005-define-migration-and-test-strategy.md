---
title: Define migration and test strategy
labels:
  - wayfinder:grilling
status: closed
assignee: GitHub Copilot
parent: ../map.md
blocked_by:
  - 002-inventory-current-window-behavior-and-compatibility-rules.md
  - 003-choose-the-external-seam-for-market-window-resolution.md
  - 004-decide-adapters-and-fallback-policy.md
blocks: []
---

## Question

What migration order and test strategy should carry the existing shallow helpers into a deep Market Window module while preserving Home Assistant behavior and avoiding a risky all-at-once refactor?

## Resolution

Migrate in thin slices: add the new module and seam tests first, move pure calculation behavior behind compatibility exports, migrate pricing sensors, move helper fallback resolution behind wrappers, then migrate Scheduler and Decision Engine callers while preserving public entry points and Home Assistant entity behavior.

See [Market Window Module Design Decisions](../research/003-006-market-window-module-design-decisions.md#migration-strategy) and [Test Strategy](../research/003-006-market-window-module-design-decisions.md#test-strategy).
