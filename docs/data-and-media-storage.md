# Data and Media Storage Topology

This document is the single source of truth for what the Draper Marketing
Pipeline persists, where it persists it, and which paths are intentionally
excluded from the SQLite store. It is referenced from
[`docs/production.md`](./production.md) and is intended for operators
responsible for backup, restore, and deployment.

## Source of Truth

The SQLite database at `data/marketing_pipeline.sqlite3` holds every piece
of operational runtime state. The tables include:

- `projects` — canonical project records (with `project_kv` for per-project
  JSON namespaces such as `learning_patterns`, `unified_analytics`,
  `content_recommendations`, and provider-specific settings)
- `reviews` — review records carrying status, history, scheduling metadata
- `scheduled_posts` — scheduled and published post records (replaces the
  legacy `orchestrator_scheduled.json` writer path)
- `jobs` — durable job queue (kinds: `generate_content`, `fix_content`,
  `publish_content`, plus future kinds)
- `source_material` — Idea Lab source material envelopes
- `content_ideas` — Idea Lab generated ideas
- `access_tokens` / `project_roles` — RBAC and scoped dashboard tokens
- `analytics_snapshots` — JSON analytics snapshots imported from legacy
  files; primary read path for analytics modules (plan 05-03)
- `system_events` — append-only audit log populated by review, publish,
  job, credential, and settings flows (plan 05-01)

Writes flow through `services/` (canonical), `data/repositories/`
(delegation layer added in plan 05-02), or directly through
`data/sqlite_store.py` for grandfathered paths.

## On-Disk-Only Paths (NOT in SQLite)

The following paths are intentionally kept on the filesystem and are NOT
migrated to SQLite:

- `data/media/` — generated images, carousels, and other large binary
  artifacts. Large blobs belong on disk; SQLite is not a media store.
- `data/videos/` — generated videos (FFmpeg outputs). Same rationale as
  media files.
- `data/projects/{id}/brand_voice.md` — markdown the operator edits
  directly. Per Phase 1 plan 01-02 decision, operator-edited strategy
  markdown stays on disk so editors can use any text editor.
- `data/projects/{id}/content_plan.md` — operator-edited content plan
  markdown. Same rationale.

Backups MUST include `data/media/` and `data/videos/` separately; they are
not covered by the SQLite snapshot.

## Deprecated JSON Fallbacks (Read-Only Transitional Shims)

The following JSON files remain on disk as deprecated fallbacks during the
SQLite transition. Each reader prefers the SQLite `analytics_snapshots`
table (or `project_kv` namespace) and only reads the file when the
snapshot is missing — and when it does, the reader emits a
`DeprecationWarning` so operators can see when their snapshot import is
stale.

Analytics JSON files:

- `data/typefully_metrics.json`
- `data/typefully_trends.json`
- `data/typefully_analytics.json`
- `data/unified_analytics.json`
- `data/content_recommendations.json`
- `data/content_preferences.json`
- `data/sync_status.json`
- `data/nostr_events.json`
- `data/nostr_metrics.json`
- `data/nostr_trends.json`

Posts history / scheduler JSON (the writer path was already routed
through SQLite in Phase 1; the file remains as a transitional read
fallback):

- `data/orchestrator_scheduled.json`

Per-project learning patterns (Phase 1 already routed the writer through
`ProjectService.save_learning_patterns` → SQLiteStore; the file remains as
a transitional read fallback):

- `data/projects/{id}/learning_patterns.json`

## Removal Timeline

JSON fallbacks will be removed in the next minor release after operators
confirm SQLite imports are stable. Until then, the fallback emits
`DeprecationWarning` when fired, surfacing stale snapshots so operators
can re-run the import via the `migrate` CLI.

## See Also

- [`docs/production.md`](./production.md) — production deployment
  checklist, backup paths, and release procedure
- [`docs/rollback-runbook.md`](./rollback-runbook.md) — phased rollback
  procedure
- `.planning/phases/05-data-and-observability-finish/05-CONTEXT.md` —
  architectural context for the JSON-to-SQLite migration
