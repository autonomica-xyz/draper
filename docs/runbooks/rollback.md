# Runbook: Rollback

**Last verified:** 2026-07-06
**Applies to:** Draper Marketing Pipeline v2 Phase 5+

## When to use

Use this runbook when a dashboard or worker deploy fails health checks,
startup, authentication, or publish/schedule smoke tests, and you need to
revert to the previous known-good release.

## Production Assumptions

- Production checkout: `/opt/draper`
- Services: `draper-dashboard`, `draper-worker`
- Service user: `draper`
- Runtime state to preserve: `.env`, `data/`, generated media, and
  `data/projects/*/secrets.json`

Do not print secret values while investigating.

## Fast rollback

1. Confirm production is a git checkout:

   ```bash
   cd /opt/draper
   sudo -u draper git rev-parse --show-toplevel
   ```

   If this fails, stop. Preserve runtime state and convert or replace the
   directory with a proper checkout before continuing (see
   `docs/production.md`).

2. Identify the previous known-good commit:

   ```bash
   sudo -u draper git log --oneline --decorate -10
   sudo -u draper git reflog -10
   ```

3. Roll back code with git, not file copies:

   ```bash
   sudo -u draper git status --short
   sudo -u draper git checkout <known-good-commit>
   sudo -u draper .venv/bin/python -m compileall dashboard/unified_dashboard.py
   sudo systemctl restart draper-dashboard
   sudo systemctl restart draper-worker
   ```

4. Verify service health:

   ```bash
   sudo systemctl status draper-dashboard --no-pager
   sudo systemctl status draper-worker --no-pager
   sudo journalctl -u draper-dashboard -n 100 --no-pager
   ```

5. Smoke test through the dashboard or API:

   - `/login` accepts the configured dashboard token.
   - Pipeline tab loads for the expected project.
   - Pending reviews are visible.
   - Scheduling/publishing routes either succeed or return structured
     `success: false` errors.

## Data recovery checks

SQLite is the source of truth. Before destructive filesystem work, copy
the database and sidecar files (see `docs/runbooks/db-backup-restore.md`
for the full procedure):

```bash
sudo -u draper cp -a data/marketing_pipeline.sqlite3 data/marketing_pipeline.sqlite3.rollback-backup
sudo -u draper cp -a data/marketing_pipeline.sqlite3-wal data/marketing_pipeline.sqlite3-wal.rollback-backup 2>/dev/null || true
sudo -u draper cp -a data/marketing_pipeline.sqlite3-shm data/marketing_pipeline.sqlite3-shm.rollback-backup 2>/dev/null || true
```

Legacy JSON files are compatibility inputs only. Do not restore them over
newer SQLite state unless the rollback decision explicitly calls for a
data restore.

## Schema-migration rollback caveat

The schema migrations used by `SQLiteStore` (e.g. the Phase 4
`failure_category` ALTER and the system_events / analytics tables added
in Phase 5) are PRAGMA-guarded and **forward-only**. There is no
automatic down-migration. If a release introduced a schema change that
the rolled-back code cannot tolerate:

1. Roll back the code first.
2. Restore the DB from the pre-deploy backup
   (`docs/runbooks/db-backup-restore.md`).
3. Restart services.

For Phase 5 the new tables (`system_events`, `analytics_snapshots`) are
additive — older code simply does not read them. Learning patterns
continue to live in the `project_kv` table (key `"learning_patterns"`);
Phase 5 did not introduce a dedicated learning-patterns table. A code
rollback without a DB restore is therefore safe in the common case.

## Reference

- `docs/rollback-runbook.md` — higher-level overview (this runbook
  consolidates and supersedes it operationally)
- `docs/runbooks/db-backup-restore.md` — SQLite backup/restore procedure
- `AGENTS.md` — Production Deployment section
