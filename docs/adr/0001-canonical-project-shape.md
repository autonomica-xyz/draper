# ADR-0001: Canonical Project Shape for the v2 Refactor

- Status: Accepted
- Date: 2026-07-04
- Deciders: Draper engineering
- Supersedes: nothing
- Superseded by: nothing (as of Phase 0)

## Context and Problem Statement

Two `ProjectManager` implementations exist in the codebase today. `projects/manager.py`
(defined at `projects/manager.py:170` — the dashboard/CLI/MCP path, 571 lines) carries a
`Project` dataclass with `config: ProjectConfig` (Typefully social-set IDs, content
pillars, default platform, tone, brand keywords, and a structured `BrandVoice` object —
see `projects/manager.py:76-106`). `data/project_manager.py` (defined at
`data/project_manager.py` — the scheduler and automated-generator path, 306 lines) carries
`data.models.Project` with `settings: ProjectSettings` and `generation_schedule:
GenerationSchedule` (platform configs, social profiles, posting strategy, typefully
integrations, brand-voice/content-plan file paths, and generation cadence — see
`data/models.py:105-211`).

Both managers delegate to the same `SQLiteStore` instance and write the same `projects`
table. The 2026-07-04 two-pass audit (`.planning/AUDIT_2026-07-04.md`, lines 38-65,
DOMN-01/DOMN-02) verified that persistence is already unified: `_normalize_project_record`
in `data/sqlite_store.py:658` persists both the `config` and `settings` shapes side by
side, so there is no data divergence. The two classes do not reference each other;
their divergence is purely in the in-memory API surface they project over the shared
table.

What diverges is the API surface. The dashboard, CLI, MCP server, scheduler, and automated
generator each construct a `ProjectManager` against the same SQLite backing but read
different project shapes out of it. The v2 refactor (Phase 1) must collapse to one
canonical shape so that every entry point loads the same project object.

## Decision Drivers

- The scheduler and automated generator already depend on the
  `data.models.Project` shape with its `settings` + `generation_schedule` fields
  (see `scheduler/content_scheduler.py:30` and
  `generator/automated_content_generator.py:28`).
- `data.models.Project` carries the richer shape: `ProjectSettings` nests
  `PlatformConfig`, `SocialProfile`, `PostingStrategy`, and `TypefullyIntegration`
  — covering everything `ProjectConfig` expresses plus generation cadence and
  platform-specific overrides (`data/models.py:105-176`).
- The dashboard/CLI path's `ProjectConfig` fields (social-set IDs, pillars, tone,
  brand keywords, structured `BrandVoice`) can be projected from or absorbed into
  `ProjectSettings` without loss; `ProjectSettings.brand_voice_path` already
  locates the canonical markdown representation.
- Phase 1 introduces `services/project_service.py` as the canonical service (see
  `docs/architecture-refactor-proposal.md` §1 and ROADMAP plan 01-01); the chosen
  domain model must be the one the service returns.

## Considered Options

1. **`data.models.Project` canonical** — make `projects.manager.ProjectManager` a facade
   returning `data.models.Project`; deprecate `data.project_manager.ProjectManager` to a
   shim. Only the dashboard/CLI/MCP path migrates; the scheduler/generator path already
   uses this shape.
2. **`projects.manager.Project` canonical** — make the data-path manager return
   `projects.manager.Project`; add `generation_schedule` to `ProjectConfig` and adopt the
   `BrandVoice` dataclass as canonical. The scheduler/generator path would have to migrate
   to a shape it does not currently use.
3. **New unified model** — create a third `Project` class from scratch combining both
   shapes. Every entry point migrates; nothing is reused as-is.

## Decision Outcome

Chosen: **Option 1 — `data.models.Project` (with `ProjectSettings` + `GenerationSchedule`)
is the canonical project shape.**

Justification: Option 1 requires the least code movement — the scheduler and automated
generator already use this shape, so only the dashboard/CLI/MCP path needs migration (via
the new `ProjectService` introduced in Phase 1, plan 01-01). `ProjectSettings` is a
superset of `ProjectConfig`'s expressive power: platforms, social profiles, posting
strategy, typefully integrations, and brand-voice/content-plan file paths are all
expressible, while the structured `BrandVoice` fields (personality, voice_attributes,
tone_by_channel, messaging_pillars) are preserved in the markdown file referenced by
`ProjectSettings.brand_voice_path` and parsed on demand by generators that need them.

Option 2 would force the scheduler and automated generator — the path that already works —
to adopt a different shape, inverting the cost. Option 3 duplicates design work and creates
a third migration target where one already exists.

## Consequences

- **Positive:** One project shape across all entry points. `services/project_service.py`
  (Phase 1, plan 01-01) returns `data.models.Project`. The characterization tests in
  `tests/test_project_loading_characterization.py` (plan 00-01) verify all five entry
  points resolve this shape today and will catch any regression after Phase 1. The
  import-boundary test in `tests/test_import_boundaries.py` (this plan, 00-02) freezes the
  legacy module's dependency surface so no new production code can grow.
- **Negative:** The dashboard/CLI path loses direct access to `ProjectConfig.brand_voice`
  (the structured `BrandVoice` dataclass at `projects/manager.py:27-73`). Brand voice
  becomes a markdown string read via `ProjectService.get_brand_voice()`. The structured
  fields (personality, voice_attributes, tone_by_channel, messaging_pillars,
  preferred_terms, avoided_terms, style_rules) are preserved in the markdown and parsed on
  demand by generators that need them.
- **Neutral:** `projects.manager.ProjectManager` becomes a facade in Phase 1 (plan 01-02).
  `data.project_manager.ProjectManager` becomes a deprecation shim emitting a
  `DeprecationWarning`. Neither is deleted in Phase 1; both are retained for a transition
  period so external scripts and the dormant `scheduler/content_scheduler.py` keep working.

## Compliance

- `tests/test_import_boundaries.py` (this plan) enforces that no new production code
  imports `data.project_manager` outside the two-file allow-list. Expanding the allow-list
  requires updating this ADR's Status to `Revised` and recording the change.
- `tests/test_project_loading_characterization.py` (plan 00-01) verifies all five entry
  points resolve the same fixture project. After Phase 1, the same tests verify they all
  resolve a `data.models.Project`.
- Allow-list amendments require updating this ADR's Status field to `Revised` and recording
  the change in the `## Compliance` section.

## References

- `docs/architecture-refactor-proposal.md` — full refactor proposal
- `.planning/AUDIT_2026-07-04.md` — DOMN-01/DOMN-02 evidence (persistence unified, API diverges)
- `.planning/ROADMAP.md` — Phase 1 success criteria
- `data/models.py:179` — canonical `Project` dataclass
- `projects/manager.py:109` — legacy `Project` dataclass (becoming facade in Phase 1)
- `tests/test_import_boundaries.py` — boundary test enforcing this decision
- `tests/test_project_loading_characterization.py` — characterization tests pinning entry-point behavior
