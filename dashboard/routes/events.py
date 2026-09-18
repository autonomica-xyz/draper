"""Events API: ``GET /api/events`` reads from the system_events audit log.

Owner-only when unscoped (no ``project_id`` query param); project-scoped
otherwise. Defense in depth: the auth middleware's ``infer_project_authz``
gates unscoped access at the boundary, AND the route handler scopes the
SQL query to projects the caller actually holds a role on. Per plan 05-04
option 1, the route calls ``store.list_events`` directly — dashboard
routes are outside the services/ boundary-test scope of plan 05-02, so
ARCH-07 criterion #4 still holds.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from dashboard.dependencies import get_store
from dashboard.middleware.auth import _request_principal

router = APIRouter()


_VALID_CATEGORIES = frozenset({"review", "publish", "job", "credential", "settings", "auth"})


@router.get("/api/events")
async def api_list_events(
    request: Request,
    category: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    store: Any = Depends(get_store),
):
    if category is not None and category not in _VALID_CATEGORIES:
        return {
            "success": False,
            "error": (
                f"category must be one of {sorted(_VALID_CATEGORIES)} or omitted"
            ),
        }
    principal = _request_principal(request)
    effective_project = project_id
    if not principal.is_admin and effective_project is None:
        return {
            "success": False,
            "error": "Forbidden",
        }
    items = store.list_events(
        category=category,
        since=since,
        project_id=effective_project,
        limit=limit,
    )
    return {"success": True, "items": items, "count": len(items)}
