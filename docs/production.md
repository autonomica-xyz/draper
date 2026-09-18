# Production Deployment

This checklist covers a minimal production deployment for the local-first dashboard.

## Required Configuration

- Install Python 3.10 or newer.
- Install dependencies in a virtual environment with `uv pip install -e .`.
- Store secrets in an environment file outside the repository, for example
  `/etc/draper.env`.
- Set `DRAPER_DASHBOARD_TOKEN` to a random value, for example:

```bash
openssl rand -hex 32
```

- Configure at least one LLM provider key and one publishing provider key.
- Keep `DRAPER_ALLOW_UNAUTHENTICATED_LOCAL` unset in production.

## Systemd

The checked-in `draper-dashboard.service` is a template. Before installing it, update:

- `User=` and `Group=`,
- `WorkingDirectory=`,
- `EnvironmentFile=`,
- `ExecStart=`,
- `ReadWritePaths=`.

Then install and start:

```bash
sudo cp draper-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now draper-dashboard
sudo systemctl status draper-dashboard
```

The template binds the dashboard to `0.0.0.0:8765` because the TLS reverse
proxy runs on a different host. The proxy → dashboard hop is plaintext HTTP,
so:

- Restrict port `8765` (firewall/security group) to the reverse proxy's IP only.
- Keep `DRAPER_REQUIRE_AUTH=1` and `DASHBOARD_SECURE_COOKIE=1` as set in the unit.
- Have the proxy send `X-Forwarded-Proto: https` so HSTS and the `Secure` cookie
  flag behave correctly.
- If the network between proxy and dashboard is untrusted, use an encrypted
  tunnel (WireGuard, etc.) or terminate TLS on the dashboard host instead.

## Worker Process

The `draper-worker` service runs the background worker that continuously
drains the job queue. It is required for the following dashboard behaviors
to work without manual intervention:

- `POST /api/generate {"async": true}` — async generation jobs are picked up
  by the worker without calling `/api/jobs/run-next`.
- Scheduled posts (`/schedule/{review_id}`) — the scheduled-publish job
  fires when due via the worker (the dashboard enqueues the job at schedule
  time with `available_at=scheduled_at`).
- Auto-fix as a background `fix_content` job (see Plan 04-02 for the
  migration; until that plan lands, auto-fix still runs synchronously in
  the request handler per AGENTS.md gotcha #7).

The worker constructs the same `AppContainer` as the dashboard, which
triggers `DashboardAccessPolicy.validate_startup()`. The systemd unit
inherits `EnvironmentFile=/etc/draper.env` from the
dashboard template; that file MUST provide either `DRAPER_DASHBOARD_TOKEN`
(at least 16 characters) or `DRAPER_ALLOW_UNAUTHENTICATED_LOCAL=1` for
loopback-only deployments. Keep `DRAPER_ALLOW_UNAUTHENTICATED_LOCAL` unset
in production — the worker never accepts inbound requests, but it shares
the dashboard's startup validation to fail closed on misconfiguration.

The unit mirrors `draper-dashboard.service` hardening: same `User=draper`,
`NoNewPrivileges=true`, `ProtectSystem=full`, `ProtectHome=true`, and
`ReadWritePaths=/opt/draper/data`. It adds
`After=draper-dashboard.service` for operational ordering (both services
work standalone — the dependency is not hard).

Install and start:

```bash
sudo cp draper-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now draper-worker
sudo systemctl status draper-worker
```

## Stuck-Job Recovery

If a worker is killed mid-job (OOM, server crash, deploy), the job may stay
in `running` status forever — the worker cannot finish what it lost. Recover
these stuck jobs with:

```bash
draper jobs recover --stuck --threshold-minutes 30
```

This marks any job in `running` longer than the threshold as `failed` with
`failure_category=unknown`. Idempotent: safe to run repeatedly. To recover
via the API (owner token required):

```bash
curl -X POST -H "Authorization: Bearer $DRAPER_DASHBOARD_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"threshold_minutes": 30}' \
     http://localhost:8765/api/jobs/recover-stuck
```

Recovered jobs do NOT automatically re-enqueue — review the
`failure_category` and `error` fields, then enqueue a new job if the work
is still needed.

## Data and Backups

Runtime state is stored under `data/`, including SQLite state and compatibility JSON files.

For the full storage topology — which paths are in SQLite, which paths are
on-disk-only (e.g. `data/media/`, `data/videos/`), and which JSON files
remain as deprecated fallbacks — see
[Data and Media Storage Topology](./data-and-media-storage.md).

Back up these paths:

- `data/marketing_pipeline.sqlite3`,
- `data/marketing_pipeline.sqlite3-wal` and `data/marketing_pipeline.sqlite3-shm` when present,
- `data/media/` and `data/videos/` (large binary artifacts not stored in SQLite),
- project markdown files you want to preserve.

Do not publish or commit backups unless they have been scrubbed of project content and secrets.

## Release Checklist

- `python -m ruff check .`
- `python -m pytest`
- `python -m build`
- Verify `git status --short` contains only intentional release changes.
- Confirm `.env`, `data/*.sqlite3`, `data/projects/**/secrets.json`, and `.mcp.json` are not tracked.
- Review root-level strategy and planning markdown files before publishing a public repository.
