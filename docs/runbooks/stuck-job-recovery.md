# Runbook: Stuck-Job Recovery

**Last verified:** 2026-07-06
**Applies to:** Draper Marketing Pipeline v2 Phase 5+

## When to use

Use this runbook when a worker was killed mid-job (OOM, server crash,
deploy, manual `kill -9`) and one or more jobs are stuck in `running`
status forever — the worker cannot finish what it lost.

Symptoms:

- `/api/health/deep` reports `worker_last_active: <ISO timestamp>` (a
  non-null value means the worker has heartbeat'd recently) but specific
  jobs have been `running` for an abnormally long time.
- A scheduled publish or async generate that never completed and never
  failed.
- The `jobs` table shows rows with `status='running'` and
  `started_at < now - 30 minutes`.

## Production Assumptions

- Production checkout: `/opt/draper`
- Job state lives in the `jobs` table inside
  `data/marketing_pipeline.sqlite3`
- CLI: `draper` (entry point `draper = "cli:main"` in `pyproject.toml`)
- Service user: `draper`

## Recovery via CLI (preferred)

```bash
sudo -u draper /opt/draper/.venv/bin/draper \
    jobs recover --stuck --threshold-minutes 30
```

This marks any job in `running` longer than the threshold as `failed`
with `failure_category=unknown`. Output:

```
Recovered N stuck job(s) (threshold: 30 min).
  - job_id=... kind=generate_content started_at=... 
  - job_id=... kind=fix_content started_at=...
```

## Recovery via API

```bash
curl -X POST -H "Authorization: Bearer $DRAPER_DASHBOARD_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"threshold_minutes": 30}' \
     http://localhost:8765/api/jobs/recover-stuck
```

Requires the owner token (the dashboard admin token). The response is a
JSON envelope with the recovered job records.

## Idempotency

The recovery UPDATE is conditional:

```sql
UPDATE jobs
   SET status='failed',
       failure_category='unknown',
       error = COALESCE(error, 'stuck: timed out'),
       finished_at = <now>, updated_at = <now>
 WHERE status='running'
   AND started_at < <cutoff>;
```

(`error` is only overwritten when it was previously NULL, so an
already-captured exception is preserved.)

Re-running the command is safe and returns `[]` once no stuck jobs
remain. Concurrent claims cannot race: a job that the worker genuinely
picked up between two recovery runs will have a fresh `started_at` and
will not match the cutoff.

## Recovered jobs do NOT auto-re-enqueue

Recovery only marks the stuck row as `failed`. It does NOT re-enqueue
the work. After recovery:

1. Review each recovered job's `failure_category` and `error` fields:

   ```bash
   sudo -u draper sqlite3 /opt/draper/data/marketing_pipeline.sqlite3 \
        "SELECT job_id, kind, failure_category, error FROM jobs WHERE failure_category='unknown' AND error LIKE 'stuck%';"
   ```

2. Decide per job whether to retry. If yes, enqueue a new job with the
   same payload (the original payload is preserved in the `payload_json`
   column).

3. For `fix_content` jobs that were stuck: re-trigger via the dashboard
   "Fix & Resubmit" button, which enqueues a fresh `fix_content` job.

4. For `generate_content` jobs: re-trigger via `POST /api/generate` with
   `{"async": true}` or via the project's generation schedule
   (`services/scheduler_producer.py` will enqueue on the next tick).

## Choosing a threshold

- **30 minutes** is the default. Suitable for `generate_content` (LLM
  call typically completes in <60s) and `fix_content` (auto-fix LLM call
  typically completes in <30s).
- For longer-running job kinds (none currently — but if media or video
  generation jobs are added later), raise the threshold to match the
  expected worst-case duration.
- Lower thresholds risk marking genuinely-running jobs as failed; higher
  thresholds delay recovery. 30 minutes is a safe default.

## Reference

- `docs/production.md` — Stuck-Job Recovery section
- `services/job_queue.py:JobQueueService.recover_stuck` — implementation
- `tests/test_*recover*` — recovery behavior contract
