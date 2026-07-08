---
title: Name the Market Window domain language
labels:
  - wayfinder:grilling
status: closed
assignee: GitHub Copilot
parent: ../map.md
blocked_by: []
blocks:
  - 003-choose-the-external-seam-for-market-window-resolution.md
  - 004-decide-adapters-and-fallback-policy.md
---

## Question

What canonical domain language should this design use for Market Windows, including buy windows, sell windows, midday price windows, high-tariff windows, window rankings, fallback sources, and unavailable/unreliable input?

## Resolution

Use `Market Window` as the umbrella term for the design. Canonical categories are `Buy Window`, `Sell Window`, `Midday Avoidance Window`, and `High-Tariff Window`. Ranking language is `Ranked Market Window`, with `Primary Market Window` and `Secondary Market Window` for selected positions. Provenance uses `Market Window Source`; confidence states are `Resolved Market Window`, `Unavailable Market Window`, and `Unreliable Market Window`.

These terms are recorded in `CONTEXT.md` and should be used by later tickets when discussing module responsibilities, seam placement, adapters, fallback policy, and tests.
