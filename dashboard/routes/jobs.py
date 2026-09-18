"""Job-management routes extracted from ``unified_dashboard.py:main()``.

Each route body is a verbatim copy of the corresponding inline closure with
the standard mechanical substitutions applied across the plan:

* ``@app.<method>`` decorators become ``@router.<method>``.
* ``dashboard_instance.<collaborator>`` becomes ``Depends(get_<collaborator>)``
  (or ``container.<collaborator>`` via ``Depends(get_container)`` for
  one-off accesses).

Threat T-03-03-01: ``/api/jobs/run-next`` is the most privileged route in
the dashboard. Owner-only authz is enforced by ``infer_project_authz``
returning ``admin_only=True`` at the middleware level (see
``dashboard/middleware/auth.py``), so no per-route role check is needed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from dashboard.dependencies import (
    get_job_queue,
    get_job_runner,
)
from dashboard.middleware.auth import (
    _default_project_id_for_request,
    _require_project_access,
)

router = APIRouter()


@router.get("/api/jobs")
async def api_list_jobs(
    request: Request,
    job_queue: Any = Depends(get_job_queue),
):
    try:
        limit = int(request.query_params.get("limit", "100"))
    except ValueError:
        return {"success": False, "error": "limit must be an integer"}
    limit = max(1, min(limit, 500))
    jobs = job_queue.list(
        project_id=request.query_params.get("project_id")
        or _default_project_id_for_request(request),
        status=request.query_params.get("status") or None,
        limit=limit,
    )
    for job in jobs:
        job["next_retry_at"] = (
            job.get("available_at")
            if job.get("status") == "queued" and job.get("failure_category")
            else None
        )
    return {"success": True, "total": len(jobs), "items": jobs}


@router.post("/api/jobs/sync-analytics")
async def api_enqueue_analytics_sync(
    request: Request,
    job_queue: Any = Depends(get_job_queue),
):
    try:
        body = await request.json()
    except Exception:
        body = {}
    project_id = body.get("project_id")
    if not project_id:
        project_id = _default_project_id_for_request(request)
    if project_id:
        _require_project_access(request, project_id, "publisher")
    job = job_queue.enqueue(
        "sync_analytics",
        project_id=project_id,
        payload={"project_id": project_id} if project_id else {},
    )
    return {"success": True, "job_id": job["job_id"], "job": job}


@router.post("/api/jobs/run-next")
async def api_run_next_job(
    request: Request,
    job_runner: Any = Depends(get_job_runner),
):
    try:
        body = await request.json()
    except Exception:
        body = {}
    kind = body.get("kind")
    result = job_runner.run_once(kinds=[kind] if kind else None)
    if not result:
        return {"success": True, "ran": False, "message": "No queued jobs"}
    return {"success": result.get("success", False), "ran": True, **result}


@router.get("/api/jobs/{job_id}")
async def api_get_job(
    job_id: str,
    job_queue: Any = Depends(get_job_queue),
):
    job = job_queue.get(job_id)
    if not job:
        return {"success": False, "error": "Job not found"}
    job["next_retry_at"] = (
        job.get("available_at")
        if job.get("status") == "queued" and job.get("failure_category")
        else None
    )
    return {"success": True, "job": job}


@router.post("/api/jobs/{job_id}/cancel")
async def api_cancel_job(
    job_id: str,
    job_queue: Any = Depends(get_job_queue),
):
    job = job_queue.cancel(job_id)
    if not job:
        return {"success": False, "error": "Job not found"}
    return {"success": True, "job": job}


@router.post("/api/jobs/recover-stuck")
async def api_recover_stuck_jobs(
    request: Request,
    job_queue: Any = Depends(get_job_queue),
):
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        threshold_minutes = int(body.get("threshold_minutes", 30))
    except (TypeError, ValueError):
        return {"success": False, "error": "threshold_minutes must be an integer"}
    if threshold_minutes < 1 or threshold_minutes > 1440:
        return {"success": False, "error": "threshold_minutes must be between 1 and 1440"}
    recovered = job_queue.recover_stuck(threshold_minutes=threshold_minutes)
    return {
        "success": True,
        "recovered": recovered,
        "threshold_minutes": threshold_minutes,
    }
