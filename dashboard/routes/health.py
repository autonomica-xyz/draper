"""Health endpoints: liveness probe + owner-only deep diagnostics.

``GET /api/health`` is unauthenticated liveness (200 = the process is
up). ``GET /api/health/deep`` is owner-only and surfaces five
diagnostic keys — ``db_ok``, ``worker_last_active``, ``queue_depth``,
``recent_failure_rate``, ``env_vars_set`` — without ever leaking secret
values (T-05-04-01). Owner-only authorization is enforced at the auth
middleware via ``infer_project_authz``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from dashboard.dependencies import get_container

router = APIRouter()


_CRITICAL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "TYPEFULLY_API_KEY",
    "DRAPER_DASHBOARD_TOKEN",
)


@router.get("/api/health")
async def api_health():
    return {"status": "ok", "service": "draper-dashboard"}


@router.get("/api/health/deep")
async def api_health_deep(container: Any = Depends(get_container)):
    db_ok, db_error = _check_db(container.store)
    worker_last_active = _worker_last_active(container.store)
    queue_depth = _queue_depth(container)
    recent_failure_rate = _recent_failure_rate(container.store)
    env_vars_set = {name: bool(os.getenv(name)) for name in _CRITICAL_ENV_VARS}
    status = "ok" if db_ok and recent_failure_rate < 0.5 else "degraded"
    body: dict[str, Any] = {
        "status": status,
        "db_ok": db_ok,
        "worker_last_active": worker_last_active,
        "queue_depth": queue_depth,
        "recent_failure_rate": recent_failure_rate,
        "env_vars_set": env_vars_set,
    }
    if not db_ok and db_error:
        body["db_error"] = db_error
    return body


def _check_db(store: Any) -> tuple[bool, str]:
    try:
        with store.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return True, ""
    except Exception as exc:
        return False, type(exc).__name__


def _worker_last_active(store: Any) -> str | None:
    try:
        with store.connect() as conn:
            row = conn.execute(
                "SELECT MAX(finished_at) AS max_finished FROM jobs "
                "WHERE finished_at IS NOT NULL"
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    value = row["max_finished"] if "max_finished" in row.keys() else row[0]
    return value if value else None


def _queue_depth(container: Any) -> int:
    try:
        stats = container.job_queue.stats()
    except Exception:
        return 0
    return int(stats.get("queued", 0))


def _recent_failure_rate(store: Any) -> float:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    try:
        with store.connect() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE finished_at IS NOT NULL "
                "AND finished_at > ?",
                (cutoff,),
            ).fetchone()
            failed_row = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE status = 'failed' "
                "AND finished_at IS NOT NULL AND finished_at > ?",
                (cutoff,),
            ).fetchone()
    except Exception:
        return 0.0
    total = total_row["n"] if total_row else 0
    failed = failed_row["n"] if failed_row else 0
    if total <= 0:
        return 0.0
    return float(failed) / float(total)
