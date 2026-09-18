# Architecture Refactor Proposal

## Purpose

Turn Draper Marketing Pipeline from a working local-first automation tool into a reliable content orchestration platform: multi-project safe, observable, extensible, and able to run background AI/publishing workflows without hidden state or duplicate domain models.

This proposal targets the remaining architectural blockers after the July 2026 hardening pass, especially DOMN-01/02: the two incompatible `ProjectManager` implementations.

## Executive Summary

The project has a solid base now: SQLite is the source of truth for core records, workflow services exist, auth/CSRF are in place, jobs are durable, and provider publishing has a common contract. The main ceiling is architectural drift:

- Two project domains still coexist:
  - `projects/manager.py`: dashboard, CLI, MCP, secrets/settings/current project
  - `data/project_manager.py`: scheduler and automated generator object-model path
- Review records are still raw dicts.
- Dashboard routes are still a giant closure inside `dashboard/unified_dashboard.py`.
- The job queue exists but no long-running worker owns background execution.
- Observability is still minimal.
- Some legacy file/analytics surfaces remain outside first-class domain workflows.

Recommended direction: keep the existing modular-monolith shape, but introduce a clean domain/service boundary and retire the compatibility managers incrementally. Do not rewrite into microservices. The fastest path to a much stronger platform is to make the monolith internally crisp.

## Target Architecture

```text
Entry Points
  cli.py
  dashboard app factory + routers
  mcp_server
  draper-worker
  scheduler producer
      |
      v
Application Services
  ProjectService
  ReviewWorkflowService
  GenerationService
  PublishingService
  JobRunner / Worker
  IdeaLabService
  AnalyticsService
      |
      v
Domain Models
  Project
  ReviewRecord
  ContentDraft
  ScheduledPost
  PublishingAttempt
  LearningPattern
  JobRecord
      |
      v
Repositories / Store
  SQLiteStore-backed repositories
  optional future Postgres implementation
      |
      v
Adapters
  LLM providers
  Typefully / Late / Nostr
  Gamma / media
  MCP tools
```

The core rule: entry points compose services. Services own business behavior. Repositories own persistence. Adapters talk to the outside world. Entry points do not mutate raw store records directly.

## Core Decisions

### 1. Use One Canonical Project Domain

Decision: keep `projects.manager.ProjectManager` as the compatibility import path for now, but make it a thin facade over a new `ProjectService` and one canonical `Project` model.

Recommended canonical model: evolve `data.models.Project` into the canonical project shape because it already carries `ProjectSettings` and `GenerationSchedule`, which the scheduler/object-model path needs.

Implementation direction:

- Move project business behavior into `services/project_service.py`.
- Keep persistence in `SQLiteStore`.
- Replace `projects/manager.py` local `Project`, `ProjectConfig`, and `BrandVoice` dataclasses with adapters to the canonical model.
- Convert `data/project_manager.py` into a deprecation shim that imports the canonical service/facade.
- Update `scheduler/content_scheduler.py` and `generator/automated_content_generator.py` to depend on `ProjectService`/`ProjectContextService`, not `data.project_manager`.

Acceptance criteria:

- `rg "class ProjectManager" projects data` shows one real implementation and one compatibility shim at most.
- `rg "from data.project_manager import"` is empty outside compatibility tests.
- Dashboard, CLI, MCP, scheduler, and automated generator all load the same project object shape.
- Project settings, generation schedule, provider mapping, secrets, brand voice, content plan, and learning patterns all resolve through the same service.

### 2. Make Review Records a Real Domain

Decision: introduce `ReviewRecord` and stop treating review state as arbitrary dicts in route handlers.

Implementation direction:

- Add `ReviewRecord`, `ReviewStatus`, `ReviewAction`, and `FeedbackHistoryEntry`.
- Add `FeedbackManager.transition(review_id, action, actor, feedback, tags, metadata)`.
- Move all approve/reject/needs-work/schedule/publish behavior into `ReviewWorkflowService`.
- Make UI form routes and JSON API routes call the same workflow methods.
- Split "approve" from "schedule/publish" so reviewers can approve without immediately touching a provider.

Acceptance criteria:

- No dashboard route calls `_save_review_record()` directly.
- JSON and form variants for approve/reject/needs-work produce identical learning-pattern behavior.
- A content item can be `approved` without creating a Typefully/Late/Nostr draft.
- Invalid state transitions fail with a typed error code, not a string-only message.

### 3. Replace Dashboard Closure Routes with an App Factory and Routers

Decision: extract route groups without redesigning the UI first.

Implementation direction:

- Add `dashboard/app.py` with `build_app(container: AppContainer) -> FastAPI`.
- Add `dashboard/container.py` to construct services once.
- Move routes into:
  - `dashboard/routes/reviews.py`
  - `dashboard/routes/projects.py`
  - `dashboard/routes/integrations.py`
  - `dashboard/routes/jobs.py`
  - `dashboard/routes/ideas.py`
  - `dashboard/routes/analytics.py`
  - `dashboard/routes/pages.py`
- Move middleware state into explicit objects: `CSRFService`, `RateLimiter`, `SecurityHeaders`.
- Keep `dashboard/templates/unified.html` initially; split templates only after routes are stable.

Acceptance criteria:

- `dashboard/unified_dashboard.py` becomes a CLI/server bootstrap under roughly 300 lines.
- Route tests can import one router without constructing the full dashboard process.
- Pydantic request contracts live next to the route group that uses them.

### 4. Make the Job System the Default Execution Engine

Decision: generation, auto-fix, scheduled publish, analytics sync, idea mining, and media generation should all run as jobs unless explicitly requested synchronously.

Implementation direction:

- Add a `draper-worker` console command.
- Add a `draper-worker.service` systemd unit.
- Scheduler becomes a producer of `generate_content` jobs, not a direct generator.
- Needs-work enqueues `fix_content`; the UI shows `fix_pending`/`fix_failed` instead of hanging on an LLM call.
- Use typed job payloads and result envelopes.
- Upgrade `claim_next_job` to `UPDATE ... RETURNING` on SQLite versions that support it, with current fallback retained.

Acceptance criteria:

- `POST /api/generate {"async": true}` is processed by a worker without calling `/api/jobs/run-next`.
- Scheduled posts publish when due through the worker.
- Auto-fix never blocks the FastAPI event loop on synchronous LLM calls.
- Job attempts, durations, failure categories, and next retry time are visible from the dashboard/API.

### 5. Formalize Repositories Around SQLiteStore

Decision: keep SQLite, but stop making every manager call `SQLiteStore` as a giant god object.

Implementation direction:

- Introduce repository classes backed by `SQLiteStore`:
  - `ProjectRepository`
  - `ReviewRepository`
  - `JobRepository`
  - `AnalyticsRepository`
  - `MediaRepository`
  - `LearningRepository`
- Keep `SQLiteStore` as the low-level schema/transaction layer.
- Move analytics JSON snapshots, posts history, media metadata, and learning patterns into first-class tables or typed project-kv records.
- Define repository interfaces narrow enough for a future Postgres backend.

Acceptance criteria:

- New application services do not import `SQLiteStore` directly.
- JSON compatibility imports are one-way migration inputs, not active write targets.
- The full runtime state needed for backup/restore is documented and queryable.

### 6. Upgrade Observability from Print Statements to Operations Data

Decision: standard-library logging is the baseline; structured event records are the platform feature.

Implementation direction:

- Use `services/observability.py` for logging config everywhere.
- Add a `system_events` table for important domain events:
  - review transitioned
  - publish attempted
  - publish failed
  - job claimed/completed/failed
  - provider credentials changed
  - project settings changed
- Add request IDs and job IDs to logs.
- Add `/api/health`, `/api/health/deep`, and `/api/events`.
- Document rollback and incident procedures in `docs/`.

Acceptance criteria:

- Operators can answer: "what failed, for which project, under which provider, and what should I do next?"
- No provider error is only visible as a console print.
- Production runbooks cover deploy, rollback, worker restart, DB backup, and stuck-job recovery.

## Refactor Phases

### Phase 0: Safety Net and Freeze Lines

Goal: make refactoring safe before moving domain boundaries.

Work:

- Add characterization tests around project loading for dashboard, CLI, MCP, scheduler, and automated generator.
- Add a project fixture with provider mapping, brand voice, content plan, learning patterns, secrets, and generation schedule.
- Add import-boundary checks that forbid new imports of `data.project_manager`.
- Document the chosen canonical project shape in an ADR.

Exit criteria:

- Tests fail if a new caller imports `data.project_manager`.
- Tests prove both old managers currently resolve the same fixture before migration starts.

### Phase 1: Project Domain Consolidation

Goal: close DOMN-01/02.

Work:

- Add `services/project_service.py`.
- Make `ProjectService` own:
  - current project
  - project CRUD
  - settings
  - provider mapping
  - brand voice/content plan
  - learning patterns
  - project data paths
  - project-match verification
- Rework `projects/manager.py` into a compatibility facade.
- Convert `data/project_manager.py` into a shim with a deprecation warning.
- Update scheduler, automated generator, and auto-fix/generation helpers to consume `ProjectService`.

Exit criteria:

- Only one project service has real behavior.
- Scheduler tests prove scheduled generation uses canonical project settings.
- `data.project_manager` can be deleted in a follow-up release without changing behavior.

### Phase 2: Review Workflow Consolidation

Goal: make all review transitions consistent and testable.

Work:

- Add `ReviewRecord` and transition methods.
- Move reject/decline/needs-work learning extraction into `ReviewWorkflowService`.
- Add `approve`, `schedule`, and `publish` as separate actions.
- Add typed error/result enums for review transitions.
- Update dashboard/MCP/CLI to call the service.

Exit criteria:

- No direct dashboard mutation of review dicts.
- API and UI variants produce identical records and learning patterns.
- Approve-without-publish exists.

### Phase 3: App Factory and Route Modules

Goal: cut dashboard blast radius.

Work:

- Add `AppContainer`.
- Extract middleware.
- Extract route groups.
- Keep existing URLs stable.
- Move route request models to route modules.

Exit criteria:

- `dashboard/unified_dashboard.py` is bootstrap-only.
- Route tests cover review/project/integration APIs without a running server.
- Existing browser template still works.

### Phase 4: Worker-First Orchestration

Goal: stop doing slow/fragile work in request handlers.

Work:

- Add worker command and service file.
- Add job types: `fix_content`, `generate_visual`, `generate_carousel`, `mine_ideas`, `sync_provider_analytics`.
- Make scheduler enqueue jobs.
- Add retry policy by failure category.
- Add stuck-job recovery command.

Exit criteria:

- Dashboard requests return quickly for LLM/provider work.
- Worker can be restarted independently.
- Stuck jobs are visible and recoverable.

### Phase 5: Data and Observability Finish

Goal: make the platform operable.

Work:

- Add `system_events`.
- Add analytics/media/published-post repositories.
- Migrate remaining JSON state.
- Standardize timezone-aware UTC datetimes.
- Add health/deep-health endpoints.
- Expand docs: rollback, stuck jobs, provider outage, DB backup/restore.

Exit criteria:

- Full runtime state is in SQLite plus explicitly documented media files.
- Every high-value mutation emits an event.
- Operators can diagnose failures from API/logs without reading code.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Project migration breaks dashboard expectations around `project.config` | Add adapter properties during Phase 1; remove only after callers are migrated |
| Scheduler object-model path regresses | Add characterization tests before changing imports |
| Dashboard route extraction creates auth/CSRF gaps | Extract middleware first and reuse the same dependencies in all routers |
| Worker introduces duplicate execution | Use idempotency keys for review/job operations and conditional state transitions |
| SQLite lock contention grows | Keep transactions short now; design repositories so Postgres can replace SQLite later |
| Refactor stalls mid-way with more shims | Time-box compatibility shims and add import-boundary tests |

## What This Unlocks

After these phases, the product can grow into a serious content operations platform:

- Multiple projects and brands without accidental cross-posting.
- Safe approval queues with true scheduled publishing.
- Background AI workflows that do not block the UI.
- Agent/MCP workflows that use the same services as humans.
- Provider-agnostic publishing and analytics.
- Auditability for every content decision and publish attempt.
- A credible path to Postgres, hosted deployment, teams, and richer campaign orchestration.

## First Implementation Slice

Start with Phase 0 and Phase 1 only.

Suggested PR scope:

1. Add `ProjectService`.
2. Add project fixture tests proving dashboard/CLI/MCP/scheduler use the same project data.
3. Convert `AutomatedContentGenerator` to accept a `ProjectService` or `ProjectContextService`.
4. Convert `ContentScheduler` to use canonical project service.
5. Turn `data.project_manager.ProjectManager` into a compatibility shim.
6. Add import-boundary test blocking new `data.project_manager` imports.

This is the smallest slice that actually closes DOMN-01/02 and removes the biggest architecture divergence without touching the dashboard route monolith yet.
