# HACS Implementation Practices — Research Note

Date: 2026-07-10  
Question: Czy w tym repozytorium jest gdzieś dokument md opisujący obowiązujące praktyki implementacji oraz dobre praktyki implementacji rozszerzeń HACS do Home Assistant?

## Summary Answer

**Tak.** Repozytorium zawiera kilka dokumentów Markdown, które razem stanowią spójny zestaw zasad implementacji integracji HACS dla projektu EnergyOptimizer. Nie istnieje jeden pojedynczy, samowystarczalny dokument "best practices HACS", ale zbiór plików w `.github/`, `.copilot-tracking/research/` i `.specify/memory/` pokrywają wszystkie istotne obszary.

---

## Documents A — Project-specific implementation practices

### 1. `.github/instructions/ha-integration-conventions.md`

**Scope:** Coding conventions for the `energy_optimizer` HA integration.  
**Covers:** File organization (required + optional files in `custom_components/energy_optimizer/`), naming conventions (files, classes, functions, constants, entity IDs), type hints, error handling patterns (`ConfigEntryNotReady`, `UpdateFailed`), logging, device registry integration, translation keys, entity descriptions, config entry data storage, platform setup pattern, polling vs push update methods, services registration, version compatibility.  
**HACS relevance:** Addresses manifest structure, config flow, and platform patterns required by HACS. No explicit `hacs.json` schema discussion.  
**Language:** English.

### 2. `.github/copilot-instructions.md`

**Scope:** Always-on AI assistant instructions for the repo; the single source of truth for mandatory patterns.  
**Covers:** Integration structure rules, mandatory entity naming (`_attr_has_entity_name = True`), config flow requirements, async patterns, code standards (import order, entity/coordinator snippets), testing requirements, `manifest.json` required fields, HACS validation checklist, common anti-patterns, repo-specific decision-engine patterns, useful commands. References `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md` as a deeper guide.  
**HACS relevance:** Explicit HACS section covering manifest fields, repository structure, README, unique_id, device registry, and release process. Points to external HACS docs URL.  
**Language:** English.

### 3. `.specify/memory/constitution.md`

**Scope:** Normative project constitution in Polish defining long-term architectural rules.  
**Covers:** Vision & scope, project purpose, tech stack (Python, async HA model, `energy_optimizer` domain, config_flow, HACS-ready), architectural principles (coordinator per entry, module separation, platform files as registration layer only, decision-logic domain layer), naming conventions (domain, unique_id stability, translation_key preference, device_class/state_class), versioning & config entry migrations (VERSION/MINOR_VERSION semantics, `async_migrate_entry` requirement), data degradation & unavailability rules, constraints & non-goals, quality/testing/observability requirements.  
**HACS relevance:** States the integration MUST remain HACS-distributable (`gotowym do dystrybucji przez HACS`) but does not detail HACS-specific mechanics; delegates those to the other documents.  
**Language:** Polish.

---

## Documents B — Specifically about good practices for developing HACS/Home Assistant integrations

### 4. `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md`

**Scope:** The most detailed HACS-specific research document in the repo.  
**Covers:** External documentation summaries (HA manifest spec, HACS publish guide, config entries index, entity core docs, development testing), required directory structure for HACS repos, `manifest.json` field specifications with HACS mandatory keys, `hacs.json` schema and all optional keys, repository validation rules (README, description, topics, issues enabled, not archived), implementation patterns (`__init__.py`, `config_flow.py`, `sensor.py`, entity naming, `DataUpdateCoordinator`), testing best practices, code quality requirements (Bronze tier, ruff/pylint/pre-commit), GitHub releases and versioning, recommended project structure, development workflow steps, publishing steps (brands registration, PR to hacs/default).  
**HACS relevance:** Fully dedicated to HACS integration development. Covers triggers, requirements, manifest, code style, testing, release process, and repository metadata. This is the closest thing to a standalone "HACS best practices" document in the repo.  
**Language:** English.  
**Note:** The audit doc (item 5) notes that some examples in this file reference an older project domain (`heat_pump_predictor`) and are partially stale, but the structural and normative content remains current.

### 5. `.copilot-tracking/research/20260212-copilot-instructions-audit-research.md`

**Scope:** Audit of currency and alignment of the instructions and research docs.  
**Covers:** File analysis of `copilot-instructions.md`, the HACS research doc, and conventions doc; external documentation re-verification; identification of stale `heat_pump_predictor` references; recommendation to keep `copilot-instructions.md` as concise always-on rulebook with deep examples in the research doc; proposed updates.  
**HACS relevance:** Meta-document about how the HACS guidance is organized; useful for understanding which file is authoritative for what.  
**Language:** English.

### 6. `.github/skills/ha-integration-maintainer/SKILL.md`

**Scope:** AI skill triggered for any HA/HACS changes to `custom_components/energy_optimizer/`.  
**Covers:** Per-change checklist (config flow, coordinator, entities, translations, recorder/statistics, services, manifest/HACS), core patterns and snippets, common pitfalls, release and validation steps.  
**HACS relevance:** Includes explicit manifest/HACS checklist items (SemVer version, `hacs.json` present, README aligned, bump on release) and release steps. Project-specific rather than generic HACS guidance.  
**Language:** English.

### 7. `.copilot-tracking/skills/home-assistant-integration-dev/SKILL.md`

**Scope:** External reference skill imported from `aurora-smart-home` repo. Covers general HA custom integration development.  
**Covers:** "Iron Law" rules (timestamps, attributes, async, storage via `runtime_data`), process flow, common pitfalls table, integration type clarification questions, delivery contract, quick reference table with links to sub-references (`architecture.md`, `config-flow.md`, `entities.md`, `coordinator.md`, `testing.md`, `publishing.md`, etc.), templates for various integration types, HACS preparation section (hacs.json, manifest.json, README, validate.yaml workflow, LICENSE, GitHub topics), pre-completion checklist covering all areas including HACS preparation.  
**HACS relevance:** Has a dedicated "HACS Preparation" section and references to a `publishing.md` sub-file for Integration Quality Scale tiers. Generic (not project-specific) but comprehensive for HACS extension development.  
**Language:** English.

### 8. `.copilot-tracking/hacs-integration-architecture.md`

**Scope:** Detailed architecture analysis of the `rce_pse` HACS integration used as a reference implementation.  
**Covers:** Executive summary, file-by-file analysis of manifest, `__init__.py`, coordinator, shared base classes, sensor/binary-sensor subdirectories, price calculator, config flow; inheritance hierarchy; entity organization pattern; DataUpdateCoordinator usage; layered class design.  
**HACS relevance:** Serves as a concrete worked example of a well-designed HACS custom component. Not prescriptive guidance but an architectural reference.  
**Language:** English.

---

## Documents C — Related but not primarily about HACS practices

| Path | Description |
|------|-------------|
| `README.md` | User-facing README with HACS install instructions and "HACS Compliance" badge. Mentions best practices briefly. |
| `CHANGELOG.md` | Release history; one entry mentions "Home Assistant and HACS best practices" re architecture refactor. |
| `spec.md` (root) | Feature spec for EnergyOptimizer; includes HACS distribution requirement and manifest rules in acceptance criteria. |
| `specs/001-core-integration/spec.md` | Speckit spec; FR-014 requires HACS-compatible repository structure. |
| `Project_Architecture_Blueprint.md` | High-level architecture blueprint; mentions HACS metadata (`hacs.json`, `manifest.json`) and packaging. |
| `docs/EnergyOptimizer_Architecture.md` | Polish-language architecture document for the HACS integration; describes layers and module structure. |
| `CONTEXT.md` | Domain glossary (market windows, arbitrage, charge actions). No HACS content. |
| `info.md` | Short HACS info file (rendered by HACS in UI). Installation and service listing. |
| `docs/MIGRATION.md` | Migration guide from YAML to entity-based config; mentions HACS install steps. |
| `CLAUDE.md` | Behavioral guidelines for LLM coding agents; references `docs/agents/` files. No HA-specific content. |
| `.github/skills/ha-entity-architecture/SKILL.md` + refs | Entity architecture skill (layers, base patterns, options reload, IDs/uniqueness). HA-specific but not HACS-pub-specific. |
| `.github/skills/ha-config-flow-options/SKILL.md` + refs | Config flow & options pattern skill. HA-specific. |
| `.github/skills/ha-translations-and-ids/SKILL.md` + refs | Translations and ID migration skill. HA-specific. |
| `.github/skills/persistable-sensors/SKILL.md` | Persistable sensors skill. HA-specific. |
| `.github/skills/code-runner/SKILL.md` + refs | Generic code execution skill. Not HA-specific. |
| `.github/skills/architecture-blueprint-generator/SKILL.md` | Blueprint generator skill. Not HA-specific. |
| `.github/skills/pr-review-response/SKILL.md` | PR review response skill. Not HA-specific. |
| `.agents/skills/home-assistant-best-practices/SKILL.md` + refs | HA best practices for automations/helpers/dashboards (not integration development per se). |
| `.copilot-tracking/README.md` | Explains the `.copilot-tracking` directory structure. |
| `docs/agents/domain.md`, `issue-tracker.md`, `triage-labels.md` | Agent workflow docs (domain, issues, labels). No HACS content. |

---

## Which documents specifically cover HACS extension development best practices?

The following directly address how to build, structure, validate, test, and release a HACS extension:

1. **`.copilot-tracking/research/20241221-hacs-compatible-integration-research.md`** — the most comprehensive; covers everything from manifest fields to brands registration and publishing.
2. **`.github/copilot-instructions.md`** — concise mandatory rules + HACS validation checklist; the "always-on" reference.
3. **`.github/instructions/ha-integration-conventions.md`** — coding-level conventions (naming, patterns, error handling) that a HACS integration must follow.
4. **`.github/skills/ha-integration-maintainer/SKILL.md`** — per-change checklist including manifest/HACS and release steps.
5. **`.copilot-tracking/skills/home-assistant-integration-dev/SKILL.md`** — general HA integration dev skill with dedicated HACS preparation section and quality scale tiers.
6. **`.specify/memory/constitution.md`** — normative project rules that constrain what the HACS integration may/must do.

For deeper pattern examples, the sub-reference files under `.github/skills/ha-entity-architecture/`, `ha-config-flow-options/`, `ha-translations-and-ids/` supplement items 2–3.

---

## Note on stale content

The audit doc (`.copilot-tracking/research/20260212-copilot-instructions-audit-research.md`) notes that `20241221-hacs-compatible-integration-research.md` and `ha-integration-conventions.md` contain some examples scoped to an older domain (`heat_pump_predictor`). The structural and normative content is current; only illustrative code snippets and path examples may be outdated. The `copilot-instructions.md` has been updated to use `energy_optimizer` throughout.
