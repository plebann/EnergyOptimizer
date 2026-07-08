---
title: Decide adapters and fallback policy
labels:
  - wayfinder:grilling
status: closed
assignee: GitHub Copilot
parent: ../map.md
blocked_by:
  - 001-name-the-market-window-domain-language.md
  - 002-inventory-current-window-behavior-and-compatibility-rules.md
  - 003-choose-the-external-seam-for-market-window-resolution.md
blocks:
  - 005-define-migration-and-test-strategy.md
---

## Question

Which adapters should exist behind the Market Window seam, and what is the policy for internal integration-owned sensors, configured fallback entities, default times, invalid values, missing state, and unavailable windows?

## Resolution

Use internal adapters for coordinator price payloads, integration-owned internal sensors, configured fallback entities, defaults, and sensor publication formatting. Preserve the current fallback order: price-window sensors use coordinator payloads only, while Scheduler and Decision Engine reads prefer internal sensors, then configured fallbacks, then existing defaults where applicable.

See [Market Window Module Design Decisions](../research/003-006-market-window-module-design-decisions.md#adapter-and-fallback-policy).
