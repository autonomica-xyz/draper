# Rollback Runbook

> **Operational source of truth:** `docs/runbooks/rollback.md` (kept
> up-to-date as the canonical step-by-step). This document remains as a
> higher-level overview.

Use this when a dashboard deploy fails health checks, startup, authentication, or publish/schedule smoke tests.

## Production Assumptions

- Production checkout: `/opt/draper`
- Service: `draper-dashboard`
- Service user: `draper`
- Runtime state to preserve: `.env`, `data/`, generated media, and `data/projects/*/secrets.json`

Do not print secret values while investigating.

## Fast Rollback

1. Confirm production is a git checkout:

   ```bash
   cd /opt/draper
   sudo -u draper git rev-parse --show-toplevel
   ```

   If this fails, stop. Preserve runtime state and convert or replace the directory with a proper checkout before continuing.

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
   ```

4. Verify service health:

   ```bash
   sudo systemctl status draper-dashboard --no-pager
   sudo journalctl -u draper-dashboard -n 100 --no-pager
   ```

5. Smoke test through the dashboard or API:

   - `/login` accepts the configured dashboard token.
   - Pipeline tab loads for the expected project.
   - Pending reviews are visible.
   - Scheduling/publishing routes either succeed or return structured `success: false` errors.

## Data Recovery Checks

SQLite is the source of truth. Before destructive filesystem work, copy the database and sidecar files:

```bash
sudo -u draper cp -a data/marketing_pipeline.sqlite3 data/marketing_pipeline.sqlite3.rollback-backup
sudo -u draper cp -a data/marketing_pipeline.sqlite3-wal data/marketing_pipeline.sqlite3-wal.rollback-backup 2>/dev/null || true
sudo -u draper cp -a data/marketing_pipeline.sqlite3-shm data/marketing_pipeline.sqlite3-shm.rollback-backup 2>/dev/null || true
```

Legacy JSON files are compatibility inputs only. Do not restore them over newer SQLite state unless the rollback decision explicitly calls for a data restore.
