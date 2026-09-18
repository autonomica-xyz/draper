"""Analytics / status / providers routes extracted from
``unified_dashboard.py:main()``.

Each route body is a verbatim copy of the corresponding inline closure with
the standard mechanical substitutions: ``@app.<method>`` becomes
``@router.<method>``, and ``dashboard_instance.<collaborator>`` becomes a
Depends-injected parameter (or ``container.<collaborator>`` via
``Depends(get_container)`` for one-off accesses).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from dashboard.dependencies import (
    get_container,
    get_feedback_manager,
    get_job_queue,
    get_publishing_manager,
    get_store,
)
from dashboard.middleware.auth import (
    _default_project_id_for_request,
    _request_principal,
    _require_project_access,
)

router = APIRouter()


@router.get("/api/status")
async def api_pipeline_status(
    request: Request,
    store: Any = Depends(get_store),
    feedback_manager: Any = Depends(get_feedback_manager),
    publishing_manager: Any = Depends(get_publishing_manager),
    job_queue: Any = Depends(get_job_queue),
):
    project_id = request.query_params.get("project_id") or _default_project_id_for_request(
        request
    )
    principal = _request_principal(request)

    if project_id:
        _require_project_access(request, project_id, "viewer")
        reviews = store.list_review_records(project_id=project_id)
        status_project_ids = [project_id]
    elif principal.is_scoped:
        principal.require_any_project_role("viewer")
        status_project_ids = principal.project_ids
        reviews = []
        for allowed_project_id in status_project_ids:
            reviews.extend(
                store.list_review_records(project_id=allowed_project_id)
            )
    else:
        status_project_ids = None
        reviews = None

    if reviews is not None:
        stats = {
            "total": len(reviews),
            "pending": sum(1 for r in reviews if r.get("status") == "pending_review"),
            "approved": sum(1 for r in reviews if r.get("status") == "approved"),
            "scheduled": sum(1 for r in reviews if r.get("status") == "scheduled"),
            "rejected": sum(
                1 for r in reviews if r.get("status") in {"rejected", "declined"}
            ),
        }
    else:
        stats = feedback_manager.get_stats()

    provider_health = {}
    for name, provider in publishing_manager.providers.items():
        provider_health[name] = {
            "configured": provider.is_configured(),
            "name": provider.get_name(),
        }

    return {
        "success": True,
        "project_id": project_id,
        "project_ids": status_project_ids,
        "pipeline": {
            "total": stats.get("total", 0),
            "pending": stats.get("pending", 0),
            "approved": stats.get("approved", 0),
            "scheduled": stats.get("scheduled", 0),
            "rejected": stats.get("rejected", 0),
        },
        "providers": provider_health,
        "jobs": job_queue.stats(),
    }


@router.get("/api/analytics")
async def api_analytics(
    request: Request,
    container: Any = Depends(get_container),
):
    platform = request.query_params.get("platform")
    project_id = request.query_params.get("project_id") or _default_project_id_for_request(
        request
    )
    if project_id:
        _require_project_access(request, project_id, "viewer")
    analytics_data = container.dashboard.get_analytics_data()

    if platform:
        platform_key = platform.lower()
        if platform_key in analytics_data:
            analytics_data = {platform_key: analytics_data[platform_key]}

    return {
        "success": True,
        "project_id": project_id,
        "period": request.query_params.get("period", "all"),
        "analytics": analytics_data,
    }


@router.get("/api/providers")
async def api_list_providers(
    publishing_manager: Any = Depends(get_publishing_manager),
):
    providers = []
    platform_map = {
        "typefully": ["twitter", "linkedin"],
        "late": [
            "twitter",
            "linkedin",
            "instagram",
            "tiktok",
            "youtube",
            "facebook",
            "threads",
            "bluesky",
            "pinterest",
        ],
        "nostr": ["nostr"],
    }
    for name, provider in publishing_manager.providers.items():
        providers.append(
            {
                "name": name,
                "configured": provider.is_configured(),
                "is_primary": name == publishing_manager._primary_provider,
                "supported_platforms": platform_map.get(name, []),
            }
        )

    return {"success": True, "providers": providers}
