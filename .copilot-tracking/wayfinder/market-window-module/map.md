---
title: Deepen the Market Window Module
labels:
  - wayfinder:map
status: open
assignee:
children:
  - tickets/001-name-the-market-window-domain-language.md
  - tickets/002-inventory-current-window-behavior-and-compatibility-rules.md
  - tickets/003-choose-the-external-seam-for-market-window-resolution.md
  - tickets/004-decide-adapters-and-fallback-policy.md
  - tickets/005-define-migration-and-test-strategy.md
  - tickets/006-decide-market-window-result-shape.md
---

## Destination

A refactor-ready design decision for deepening the Market Window module: the domain language, module responsibilities, seam placement, adapter/fallback policy, and migration/test strategy are clear enough to hand off for implementation.

This map covers all price/tariff window knowledge: buy windows, sell windows, midday price windows, high-tariff start/end windows, internal sensor reads, fallback entity reads, Scheduler timing, and Decision Engine reads. It does not implement the refactor.

## Notes

- Planning only: tickets resolve decisions and investigations, not implementation, unless a ticket explicitly says otherwise.
- Consult `/codebase-design` for module/interface/depth/seam/adapter/leverage/locality vocabulary.
- Use `/grilling` for HITL decisions and `/domain-modeling` when the glossary changes.
- Follow Home Assistant integration constraints from `.github/copilot-instructions.md`; preserve public `async_run_*` entry points unless a later map explicitly changes that scope.
- Local markdown tracker convention for this effort: each file has frontmatter with `title`, `labels`, `status`, `assignee`, `parent`, `blocked_by`, and `blocks`. Open, unassigned tickets whose `blocked_by` tickets are closed are the frontier.

## Decisions so far

- [Name the Market Window domain language](tickets/001-name-the-market-window-domain-language.md) — confirmed Market Window vocabulary for categories, rankings, sources, and validity states.
- [Inventory current window behavior and compatibility rules](tickets/002-inventory-current-window-behavior-and-compatibility-rules.md) — captured the behavior the deepened Market Window module must preserve across helpers, calculations, sensors, Scheduler, Decision Engine reads, warnings, and tests.

## Not yet specified

- Whether Scheduler schedule snapshots should remain part of the Market Window module or become a separate Schedule Intent module depends on the seam decision.
- Whether any compatibility adapter is temporary or permanent depends on fallback policy and migration risk.

## Out of scope

- Forecast profile deepening is a separate architecture effort.
- Decision outcome recording is a separate architecture effort.
- Command entry path cleanup is a separate architecture effort.
- Implementing the Market Window refactor is out of scope for this planning map.
