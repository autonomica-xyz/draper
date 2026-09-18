# Dashboard

The current dashboard is `dashboard/unified_dashboard.py`, a FastAPI app that serves the
single-page review, scheduling, strategy, settings, and analytics UI.

## Run Locally

```bash
python -m dashboard.unified_dashboard --run-server --port 8765
```

The dashboard requires authentication unless local unauthenticated development is explicitly
enabled:

```bash
export DRAPER_DASHBOARD_TOKEN="$(openssl rand -hex 32)"
python -m dashboard.unified_dashboard --run-server --port 8765
```

For loopback-only development:

```bash
export DRAPER_ALLOW_UNAUTHENTICATED_LOCAL=1
python -m dashboard.unified_dashboard --run-server --port 8765
```

Do not use `DRAPER_ALLOW_UNAUTHENTICATED_LOCAL=1` in production or behind a reverse proxy.

## Production

Use the systemd template in `draper-dashboard.service` and the deployment checklist in
[`../docs/production.md`](../docs/production.md). Runtime state is stored under `data/` and should
be backed up separately from the source tree.
