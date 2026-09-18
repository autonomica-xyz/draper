# Runbook: Worker Restart

**Last verified:** 2026-07-06
**Applies to:** Draper Marketing Pipeline v2 Phase 5+

## When to use

Use this runbook when the background worker (`draper-worker`) needs to be
restarted without redeploying code — for example after a config change
in `/etc/draper.env`, after the worker has consumed
abnormal memory, or after a worker crash that systemd did not auto-restart.

## Production Assumptions

- Service: `draper-worker` (runs `python -m worker --poll-interval 2.0`)
- Service user: `draper`
- Data directory: `/opt/draper/data` (must be writable
  by the `draper` user)
- Job state lives in the `jobs` table inside
  `data/marketing_pipeline.sqlite3`

## Restart procedure

1. Check current status and recent logs (understand why you are
   restarting):

   ```bash
   sudo systemctl status draper-worker --no-pager
   sudo journalctl -u draper-worker -n 100 --no-pager
   ```

2. Restart the worker:

   ```bash
   sudo systemctl restart draper-worker
   sudo systemctl status draper-worker --no-pager
   ```

3. Confirm it is draining jobs:

   ```bash
   sudo journalctl -u draper-worker -n 50 --no-pager | tail -50
   ```

   Expected: log lines showing `request_id=...` and `job_id=...`
   correlation IDs, poll-interval cadence (~2s), and either "no job
   available" idle lines or "processed job" lines for any queued work.

## Will I lose jobs?

**No.** The worker is purely a driver over `JobRunner.run_once`. Job
state (queued, running, completed, failed) lives in the `jobs` table in
SQLite, not in worker memory. Restarting the worker:

- Does NOT drop queued jobs.
- Does NOT cancel completed jobs.
- Does NOT lose job history.

The only jobs affected are ones that were `running` at the moment of
restart — they will stay in `running` status because the worker cannot
finish what it lost. Those need recovery; see "Stuck-job recovery after
restart" below.

## Stuck-job recovery after restart

If the worker was killed mid-job (OOM, server crash, manual `kill -9`,
or this restart), any in-flight job is now stuck in `running` forever.
After the worker comes back up, run stuck-job recovery:

```bash
sudo -u draper /opt/draper/.venv/bin/draper \
    jobs recover --stuck --threshold-minutes 30
```

Or via the API (owner token required):

```bash
curl -X POST -H "Authorization: Bearer $DRAPER_DASHBOARD_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"threshold_minutes": 30}' \
     http://localhost:8765/api/jobs/recover-stuck
```

See `docs/runbooks/stuck-job-recovery.md` for the full procedure.

## Configuration changes that require a restart

The worker reads these at startup (no hot-reload):

- `DRAPER_DASHBOARD_TOKEN` / `DRAPER_ALLOW_UNAUTHENTICATED_LOCAL` —
  startup validation mirrors the dashboard (fail-closed on
  misconfiguration).
- LLM provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `LLM_MODEL`, `LLM_FALLBACKS`).
- Publishing provider keys (`TYPEFULLY_API_KEY`, `LATE_API_KEY`,
  `NOSTR_PRIVATE_KEY`).
- `DRAPER_LOG_LEVEL`, `DRAPER_LOG_FORMAT`.

After editing `/etc/draper.env`, restart the worker
for changes to take effect.

## Reference

- `docs/production.md` — Worker Process section
- `docs/runbooks/stuck-job-recovery.md` — recover jobs interrupted by the
  restart
- `draper-worker.service` — systemd unit template
