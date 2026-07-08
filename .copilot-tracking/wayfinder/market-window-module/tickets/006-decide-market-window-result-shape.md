---
title: Decide Market Window result shape
labels:
  - wayfinder:grilling
status: closed
assignee: GitHub Copilot
parent: ../map.md
blocked_by:
  - 002-inventory-current-window-behavior-and-compatibility-rules.md
blocks:
  - 003-choose-the-external-seam-for-market-window-resolution.md
---

## Question

Should the deepened Market Window module expose one shared result shape for Buy Windows, Ranked Sell Windows, and Midday Avoidance Windows, or preserve distinct result shapes behind a smaller caller-facing interface?

## Resolution

Preserve distinct category-specific result shapes inside the Market Window module and expose a smaller caller-facing interface at the seam.

See [Market Window Module Design Decisions](../research/003-006-market-window-module-design-decisions.md#result-shape-decision).