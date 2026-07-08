---
title: Inventory current window behavior and compatibility rules
labels:
  - wayfinder:research
status: closed
assignee: GitHub Copilot
parent: ../map.md
blocked_by: []
blocks:
  - 003-choose-the-external-seam-for-market-window-resolution.md
  - 004-decide-adapters-and-fallback-policy.md
  - 005-define-migration-and-test-strategy.md
---

## Question

What exact behavior must the deepened Market Window module preserve across current helpers, pricing sensors, Scheduler timing, Decision Engine reads, fallback entity reads, warning behavior, and tests?

## Resolution

The current behavior inventory is captured in [Current Market Window Behavior And Compatibility Rules](../research/002-current-window-behavior-and-compatibility-rules.md).

The deepened Market Window module must preserve helper parsing and fallback behavior, Buy Window tie-breakers and availability rules, Ranked Sell Window ranking and secondary-window attributes, Midday Avoidance Window zero-price expansion and active-state publication, Scheduler timing/snapshot compatibility, Decision Engine fallback behavior, and warning/unavailable semantics documented there.

The inventory made the result-shape question precise enough to graduate into [Decide Market Window result shape](006-decide-market-window-result-shape.md).
