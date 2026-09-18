"""Authn/authz middleware and project-authz helpers extracted from ``unified_dashboard.py:main()``.

The functions previously nested inside ``main()`` as closures over
``dashboard_instance`` are module-level here. They read the container from
``request.app.state.container`` (set by ``build_app``). The
``AuthMiddleware`` class wraps the body of ``require_dashboard_auth``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Dict, Optional

from fastapi.requests import Request
from fastapi.responses import JSONResponse, RedirectResponse

from services.access_control import (
    AccessDeniedError,
    DashboardAccessPolicy,
    Principal,
)

if TYPE_CHECKING:
    from dashboard.app_container import AppContainer


role_by_method = {
    "GET": "viewer",
    "HEAD": "viewer",
    "OPTIONS": "viewer",
    "POST": "editor",
    "PUT": "editor",
    "PATCH": "editor",
    "DELETE": "owner",
}


def _json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
    )


def _request_principal(request: Request) -> Principal:
    """Return the authenticated principal for a request.

    Fail closed: when no middleware attached a principal (route mounted
    without ``AuthMiddleware``), the caller gets an unauthenticated principal
    with no roles — every ``require_*`` check denies it. Unauthenticated admin
    access is granted only by ``AuthMiddleware`` in explicit loopback-dev
    mode, never by this fallback.
    """
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return Principal(
            token_id="anonymous",
            label="Unauthenticated (no auth middleware)",
            is_admin=False,
            project_roles={},
        )
    return principal


def _container(request: Request) -> "AppContainer":
    return request.app.state.container


def _visible_projects(request: Request):
    container = _container(request)
    projects = container.get_projects()
    principal = _request_principal(request)
    if principal.is_admin:
        return projects
    allowed = set(principal.project_ids)
    return [project for project in projects if project.project_id in allowed]


def _default_project_id_for_request(request: Request) -> Optional[str]:
    container = _container(request)
    principal = _request_principal(request)
    if principal.is_admin:
        current = container.get_current_project()
        return current.project_id if current else None
    return principal.project_ids[0] if len(principal.project_ids) == 1 else None


def _current_project_for_request(
    request: Request,
    requested_project_id: Optional[str] = None,
):
    container = _container(request)
    project_id = requested_project_id or _default_project_id_for_request(request)
    if project_id:
        _request_principal(request).require_project_role(project_id, "viewer")
        return container.project_manager.get_project(project_id)
    if _request_principal(request).is_admin:
        return container.get_current_project()
    return None


def _resolve_record_project_id(request: Request, record: Optional[Dict]) -> Optional[str]:
    if not record:
        return None
    return _container(request).resolve_record_project_id(record)


def _resource_project_id(request: Request, resource_type: str, resource_id: str) -> Optional[str]:
    container = _container(request)
    if resource_type == "review":
        return _resolve_record_project_id(
            request, container.feedback_manager._load_review_record(resource_id)
        )
    if resource_type == "scheduled":
        record = container.store.get_scheduled_record(resource_id)
        return _resolve_record_project_id(request, record)
    if resource_type == "job":
        record = container.job_queue.get(resource_id)
        return record.get("project_id") if record else None
    if resource_type == "material":
        record = container.store.get_source_material_record(resource_id)
        return record.get("project_id") if record else None
    if resource_type == "idea":
        record = container.store.get_content_idea_record(resource_id)
        return record.get("project_id") if record else None
    return None


def _require_project_access(
    request: Request,
    project_id: Optional[str],
    required_role: str,
) -> None:
    principal = _request_principal(request)
    if project_id == "*":
        principal.require_any_project_role(required_role)
        return
    principal.require_project_role(project_id, required_role)


def _project_from_path(path: str, prefix: str) -> Optional[str]:
    marker = f"{prefix}/"
    if not path.startswith(marker):
        return None
    remainder = path[len(marker) :]
    return remainder.split("/", 1)[0] if remainder else None


async def _json_body_for_authz(request: Request) -> Dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return {}
    body_bytes = await request.body()

    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    request._receive = receive
    if not body_bytes:
        return {}
    try:
        parsed = json.loads(body_bytes.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


async def infer_project_authz(request: Request) -> tuple[Optional[str], str, bool]:
    """Return (project_id, required_role, global_admin_only)."""
    method = request.method.upper()
    path = request.url.path
    role = role_by_method.get(method, "viewer")

    if path in {"/", "/analytics", "/scheduled", "/evaluate", "/past", "/nostr"}:
        return (
            request.query_params.get("project") or _default_project_id_for_request(request),
            "viewer",
            False,
        )

    if path == "/api/projects":
        return (
            "*" if method == "GET" else None,
            "viewer" if method == "GET" else "owner",
            method != "GET",
        )

    project_id = _project_from_path(path, "/api/projects")
    if project_id:
        if "/access" in path or path.endswith("/mcp-config"):
            return project_id, "owner", False
        if "/integrations" in path or "/social-profiles" in path:
            return project_id, "owner", False
        if method == "DELETE":
            return project_id, "owner", False
        return project_id, role, False

    path_parts = [part for part in path.split("/") if part]
    if path_parts[:1] in (
        ["approve"],
        ["needs-work"],
        ["decline"],
        ["schedule"],
        ["regenerate"],
        ["reject"],
    ):
        return (
            _resource_project_id(request, "review", path_parts[1] if len(path_parts) > 1 else ""),
            "publisher",
            False,
        )

    if path_parts[:2] == ["api", "decline"]:
        return (
            _resource_project_id(request, "review", path_parts[2] if len(path_parts) > 2 else ""),
            "publisher",
            False,
        )

    if path_parts[:2] == ["api", "content"] and len(path_parts) >= 3:
        action = path_parts[3] if len(path_parts) > 3 else ""
        required = "publisher" if action in {"approve", "reject", "schedule"} else role
        return _resource_project_id(request, "review", path_parts[2]), required, False

    if path == "/api/publish":
        body = await _json_body_for_authz(request)
        return _resource_project_id(request, "review", body.get("review_id", "")), "publisher", False

    if path_parts[:2] == ["scheduled", "delete"]:
        return (
            _resource_project_id(request, "scheduled", path_parts[2] if len(path_parts) > 2 else ""),
            "publisher",
            False,
        )

    if path_parts[:3] == ["api", "calendar", "events"] and len(path_parts) >= 4:
        return _resource_project_id(request, "scheduled", path_parts[3]), "publisher", False

    if path == "/api/generate":
        body = await _json_body_for_authz(request)
        return (
            body.get("project_id") or _default_project_id_for_request(request),
            "editor",
            False,
        )

    if path in {"/api/generate/image", "/api/generate/carousel"}:
        body = await _json_body_for_authz(request)
        return (
            body.get("project_id") or _default_project_id_for_request(request),
            "editor",
            False,
        )

    if path == "/api/jobs/sync-analytics":
        body = await _json_body_for_authz(request)
        return (
            body.get("project_id") or _default_project_id_for_request(request),
            "publisher",
            False,
        )

    if path in {"/api/jobs/run-next", "/api/jobs/recover-stuck"}:
        return None, "owner", True

    if path == "/api/health/deep":
        return None, "owner", True

    if path == "/api/events":
        if request.query_params.get("project_id"):
            return request.query_params["project_id"], "viewer", False
        return None, "owner", True

    if path_parts[:2] == ["api", "jobs"] and len(path_parts) >= 3:
        return (
            _resource_project_id(request, "job", path_parts[2]),
            "publisher" if method != "GET" else "viewer",
            False,
        )

    if path == "/api/jobs":
        return (
            request.query_params.get("project_id")
            or _default_project_id_for_request(request),
            "viewer",
            False,
        )

    if path == "/api/content":
        return (
            request.query_params.get("project_id")
            or _default_project_id_for_request(request),
            "viewer",
            False,
        )

    if path == "/api/analytics":
        return (
            request.query_params.get("project_id")
            or _default_project_id_for_request(request),
            "viewer",
            False,
        )

    if path == "/api/status":
        return (
            request.query_params.get("project_id")
            or _default_project_id_for_request(request)
            or "*",
            "viewer",
            False,
        )

    if path.startswith("/api/ideas/materials"):
        if len(path_parts) >= 4 and path_parts[3].startswith("sm_"):
            required = "viewer" if method == "GET" else "editor"
            return _resource_project_id(request, "material", path_parts[3]), required, False
        body = await _json_body_for_authz(request)
        return (
            request.query_params.get("project_id")
            or body.get("project_id")
            or _default_project_id_for_request(request),
            "viewer" if method == "GET" else "editor",
            False,
        )

    if path.startswith("/api/ideas/ideas"):
        if len(path_parts) >= 4 and path_parts[3].startswith("ci_"):
            required = "viewer" if method == "GET" else "editor"
            return _resource_project_id(request, "idea", path_parts[3]), required, False
        body = await _json_body_for_authz(request)
        return (
            request.query_params.get("project_id")
            or body.get("project_id")
            or _default_project_id_for_request(request),
            "viewer" if method == "GET" else "editor",
            False,
        )

    if path == "/api/ideas/mining/trigger" or path == "/api/ideas/generate-ideas-batch":
        body = await _json_body_for_authz(request)
        return (
            body.get("project_id") or _default_project_id_for_request(request),
            "editor",
            False,
        )

    if path == "/nostr/publish-all" or path == "/nostr/publish-note":
        return _default_project_id_for_request(request), "publisher", False

    if path == "/sync-analytics":
        return _default_project_id_for_request(request), "publisher", False

    return None, role, False


class AuthMiddleware:
    """Authentication + project-authorization gate."""

    def __init__(self, access_policy: DashboardAccessPolicy, container: "AppContainer") -> None:
        self.access_policy = access_policy
        self.container = container

    async def __call__(self, request: Request, call_next):
        access_policy = self.access_policy
        container = self.container
        if not access_policy.auth_enabled or access_policy.is_exempt_path(request.url.path):
            request.state.principal = Principal(
                token_id="dev-local",
                label="Unauthenticated local dev",
                is_admin=True,
                mcp_enabled=True,
            )
            request.state.auth_transport = ""
            return await call_next(request)

        token, source = access_policy.extract_token_with_source(
            request.headers, request.cookies
        )
        principal = access_policy.authenticate(token, container.store)
        if principal:
            request.state.principal = principal
            request.state.auth_transport = source
            if principal.is_scoped:
                try:
                    project_id, required_role, admin_only = await infer_project_authz(request)
                    if admin_only:
                        raise AccessDeniedError("Admin access required")
                    _require_project_access(request, project_id, required_role)
                except AccessDeniedError:
                    return _json_error(403, "Forbidden")
            return await call_next(request)

        accept = request.headers.get("accept", "")
        if request.url.path.startswith("/api/") or "application/json" in accept:
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Unauthorized"},
            )
        return RedirectResponse(url="/login", status_code=303)
