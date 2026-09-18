# Runbook: Production Deploy

**Last verified:** 2026-07-06
**Applies to:** Draper Marketing Pipeline v2 Phase 5+

## When to use

Use this runbook when deploying a new release of the dashboard + worker to
the production host at `/opt/draper`. This is the
standard update flow.

## Production Assumptions

- Production checkout: `/opt/draper` (a git checkout of
  `git@github.com:your-org/draper.git`)
- Services: `draper-dashboard` (FastAPI/uvicorn) and `draper-worker`
  (background job runner)
- Service user: `draper`
- Runtime state to preserve across deploys: `.env`, `data/*.sqlite3`
  (and `-wal` / `-shm` sidecars), generated media under `data/media/` and
  `data/videos/`, and `data/projects/*/secrets.json`
- Environment file: `/etc/draper.env` (contains
  `DRAPER_DASHBOARD_TOKEN`, LLM keys, publishing provider keys)

Do not print secret values while deploying.

## Pre-deploy checks

1. On your workstation: `ruff check . && pytest` — both must pass.
2. Confirm `.env`, `data/*.sqlite3`, `data/projects/**/secrets.json`, and
   `.mcp.json` are NOT tracked (`git status --short` shows only intended
   release changes).
3. Confirm the `draper` service user has read access to the repository
   origin (GitHub deploy key or equivalent non-interactive credential):

   ```bash
   sudo -u draper git -C /opt/draper fetch origin --dry-run
   ```

## Standard deploy

1. Confirm production is a git checkout (do NOT proceed if this fails —
   see docs/production.md for the conversion procedure):

   ```bash
   cd /opt/draper
   sudo -u draper git rev-parse --show-toplevel
   ```

2. Pull the target branch or commit:

   ```bash
   sudo -u draper git fetch --all --prune
   sudo -u draper git status --short
   sudo -u draper git checkout <branch-or-commit>
   sudo -u draper git pull --ff-only
   ```

3. Sanity-compile the dashboard entry point (catches syntax errors before
   service restart):

   ```bash
   sudo -u draper .venv/bin/python -m compileall dashboard/unified_dashboard.py
   ```

4. Restart the dashboard and verify it came up:

   ```bash
   sudo systemctl restart draper-dashboard
   sudo systemctl status draper-dashboard --no-pager
   sudo journalctl -u draper-dashboard -n 100 --no-pager
   ```

5. Restart the worker (the worker and dashboard share the same code; both
   must run the new release):

   ```bash
   sudo systemctl restart draper-worker
   sudo systemctl status draper-worker --no-pager
   ```

## Post-deploy smoke test

1. Liveness:

   ```bash
   curl -fsS http://localhost:8765/api/health
   ```

   Expected: `200 OK` with a small JSON body.

2. Deep health (auth required):

   ```bash
   curl -fsS -H "Authorization: Bearer $DRAPER_DASHBOARD_TOKEN" \
        http://localhost:8765/api/health/deep
   ```

   Expected: `200 OK` with `db_ok: true`, `worker_last_active` set to a
   non-null ISO timestamp (the worker has heartbeat'd recently), and
   `env_vars_set` reporting your configured provider keys as `true`.

   Programmatic check:

   ```bash
   curl -fsS -H "Authorization: Bearer $DRAPER_DASHBOARD_TOKEN" \
        http://localhost:8765/api/health/deep \
        | jq -e '.db_ok and (.worker_last_active != null) and (.status == "ok" or .status == "degraded")'
   ```

3. UI smoke (manual, in a browser): `/login` accepts the configured token;
   the Pipeline tab loads; pending reviews are visible.

## If something goes wrong

- See `docs/runbooks/rollback.md` for fast rollback.
- See `docs/runbooks/worker-restart.md` if only the worker needs restart.
- See `docs/runbooks/stuck-job-recovery.md` if jobs were interrupted by
  the deploy.

## Reference

- `AGENTS.md` — Production Deployment section (canonical process)
- `docs/production.md` — system architecture, systemd templates, release
  checklist
- `draper-dashboard.service`, `draper-worker.service` — systemd unit
  templates
