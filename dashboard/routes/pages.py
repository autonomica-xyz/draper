"""HTML page routes extracted from ``unified_dashboard.py:main()``.

Each route body is a verbatim copy of the corresponding inline closure with
the standard mechanical substitutions applied across the plan:

* ``@app.<method>`` decorators become ``@router.<method>``.
* ``dashboard_instance.<collaborator>`` becomes ``Depends(get_<collaborator>)``
  (or ``container.<collaborator>`` via ``Depends(get_container)`` for
  one-off accesses).
* The Jinja2Templates instance is constructed once at module import using
  the same path resolution as the source (``Path(__file__).parent.parent
  / "templates"``), which from ``dashboard/routes/pages.py`` resolves to
  ``dashboard/templates/``.

Threat T-03-03-02 (login spoofing): the cookie name, ``HttpOnly`` +
``SameSite=Lax`` attributes, and ``DashboardAccessPolicy.authenticate``
validation are preserved verbatim.
Threat T-03-03-04 (info disclosure via project list): the
``_visible_projects`` filter is preserved verbatim so scoped tokens
see only their own projects.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates

from dashboard.dependencies import get_container
from dashboard.middleware.auth import (
    _current_project_for_request,
    _require_project_access,
    _resolve_record_project_id,
    _visible_projects,
)

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

router = APIRouter()


def _env_flag(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _secure_cookie_enabled(container: Any, request: Request) -> bool:
    explicit = _env_flag("DASHBOARD_SECURE_COOKIE")
    if explicit is not None:
        return explicit
    return request.url.scheme == "https"


def _record_auth_event(
    container: Any,
    request: Request,
    *,
    succeeded: bool,
    throttled: bool = False,
    principal: Any = None,
) -> None:
    """Write a ``system_events`` audit row for a login attempt.

    Records only the client IP and outcome labels — never submitted token
    material. Failures here must never break the login flow itself.
    """
    from dashboard.middleware.rate_limit import client_ip

    payload: dict[str, Any] = {"ip": client_ip(request), "method": "login-form"}
    if throttled:
        payload["throttled"] = True
    if principal is not None:
        payload["principal"] = getattr(principal, "label", "")
        payload["token_id"] = getattr(principal, "token_id", "")
    try:
        container.store.record_event(
            category="auth",
            action="login_succeeded" if succeeded else "login_failed",
            payload=payload,
        )
    except Exception as exc:  # audit is best-effort; never block login
        print(f"system_events.auth write failed: {exc}")


@router.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(
        """
                <!doctype html>
                <html>
                <head><title>Draper Dashboard Login</title></head>
                <body style="font-family: system-ui, sans-serif; max-width: 420px; margin: 10vh auto;">
                    <h1>Dashboard Login</h1>
                    <form method="post" action="/login">
                        <input name="token" type="password" autocomplete="current-password"
                               style="width: 100%; padding: 10px; margin-bottom: 12px;"
                               autofocus>
                        <button type="submit" style="padding: 10px 14px;">Sign in</button>
                    </form>
                </body>
                </html>
                """
    )


@router.post("/login")
async def login(
    request: Request,
    container: Any = Depends(get_container),
    token: str = Form(...),
):
    # Threat T-q-02 (credential brute force): failed-login throttle keyed by
    # socket peer IP (never X-Forwarded-For), plus auth audit events. Only
    # failed attempts count against the budget; success clears the bucket.
    login_limiter = getattr(container, "login_limiter", None)
    if login_limiter is not None and login_limiter.is_locked(request):
        _record_auth_event(container, request, succeeded=False, throttled=True)
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "error": "Too many failed login attempts. Try again later.",
            },
        )
    token = token.strip().strip('"').strip("'")
    principal = container.access_policy.authenticate(token, container.store)
    if not principal:
        if login_limiter is not None:
            login_limiter.record_failure(request)
        _record_auth_event(container, request, succeeded=False)
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Unauthorized"},
        )
    if login_limiter is not None:
        login_limiter.reset(request)
    _record_auth_event(container, request, succeeded=True, principal=principal)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        "draper_dashboard_token",
        token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie_enabled(container, request),
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("draper_dashboard_token")
    return response


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    container: Any = Depends(get_container),
):
    active_tab = request.query_params.get("tab", "pipeline")
    project_id = request.query_params.get("project")
    from datetime import datetime

    projects = _visible_projects(request)
    current_project = _current_project_for_request(request, project_id)

    if active_tab == "analytics":
        analytics = container.dashboard.get_analytics_data()
        content = None
        scheduled = None
    elif active_tab == "scheduled":
        analytics = None
        content = None
        scheduled = container.dashboard.get_scheduled_posts(
            project_id=current_project.project_id if current_project else None
        )
    else:
        analytics = None
        content = (
            container.dashboard.get_content_to_evaluate(
                project_id=current_project.project_id if current_project else None
            )
            if active_tab in ("pipeline", None)
            else None
        )
        scheduled = None

    return templates.TemplateResponse(
        request,
        "unified.html",
        {
            "request": request,
            "active_tab": active_tab,
            "analytics": analytics,
            "content": content,
            "scheduled": scheduled,
            "datetime": datetime,
            "projects": projects,
                        "current_project": current_project,
            "schedule_error": request.query_params.get("schedule_error") or "",
        },
    )


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    container: Any = Depends(get_container),
):
    from datetime import datetime

    analytics = container.dashboard.get_analytics_data()

    return templates.TemplateResponse(
        request,
        "unified.html",
        {
            "request": request,
            "active_tab": "analytics",
            "analytics": analytics,
            "content": None,
            "scheduled": None,
            "datetime": datetime,
            "projects": _visible_projects(request),
            "current_project": _current_project_for_request(request),
        },
    )


@router.get("/past", response_class=HTMLResponse)
async def past_posts_page(request: Request):
    return RedirectResponse(url="/?tab=pipeline", status_code=303)


@router.get("/scheduled", response_class=HTMLResponse)
async def scheduled_posts_page(
    request: Request,
    container: Any = Depends(get_container),
):
    from datetime import datetime

    current_project = _current_project_for_request(request)
    scheduled = container.dashboard.get_scheduled_posts(
        project_id=current_project.project_id if current_project else None
    )

    return templates.TemplateResponse(
        request,
        "unified.html",
        {
            "request": request,
            "active_tab": "scheduled",
            "analytics": None,
            "content": None,
            "scheduled": scheduled,
            "datetime": datetime,
            "projects": _visible_projects(request),
            "current_project": current_project,
        },
    )


@router.get("/evaluate", response_class=HTMLResponse)
async def evaluate_redirect(request: Request):
    return RedirectResponse(url="/?tab=pipeline", status_code=303)


@router.get("/generate")
async def generate_content_get():
    return JSONResponse(
        status_code=405,
        content={"success": False, "error": "Use POST /generate to generate content"},
    )


@router.post("/generate", response_class=HTMLResponse)
async def generate_content(
    request: Request,
    container: Any = Depends(get_container),
):
    current_project = _current_project_for_request(request)
    if not current_project:
        return RedirectResponse(
            url="/?tab=pipeline&error=project_required", status_code=303
        )
    _require_project_access(request, current_project.project_id, "editor")
    generator = container.get_generator_for_project(current_project.project_id)
    result = generator.generate_batch(count=5)
    batch = result.get("posts", []) if isinstance(result, dict) else result

    for post in batch:
        post["project_id"] = current_project.project_id
        post["project_name"] = current_project.name
        container.feedback_manager.post_content_for_review(post, "DASHBOARD")

    return RedirectResponse(url="/?tab=pipeline", status_code=303)


@router.get("/nostr", response_class=HTMLResponse)
async def nostr_page(request: Request):
    return RedirectResponse(url="/?tab=pipeline", status_code=303)


@router.post("/nostr/publish-all", response_class=HTMLResponse)
async def publish_all_to_nostr(
    request: Request,
    container: Any = Depends(get_container),
):
    from integrations.publishing_provider import PublishRequest

    current_project = _current_project_for_request(request)
    if not current_project:
        return RedirectResponse(
            url="/?tab=pipeline&error=project_required", status_code=303
        )
    _require_project_access(request, current_project.project_id, "publisher")
    content_queue = [
        review
        for review in container.feedback_manager.get_pending_reviews(limit=100)
        if _resolve_record_project_id(request, review) == current_project.project_id
    ][:10]

    published_count = 0
    for review in content_queue:
        post_data = review["post_data"]

        publish_request = PublishRequest(
            content=post_data.get("content", ""), platform="nostr"
        )
        result = container.publishing_manager.publish(
            publish_request, provider_name="nostr"
        )

        if result.success:
            container.feedback_manager.process_feedback(
                review["review_id"], "approve", "Published to Nostr"
            )
            published_count += 1

    return RedirectResponse(url="/?tab=pipeline", status_code=303)


@router.post("/nostr/publish-note", response_class=HTMLResponse)
async def publish_note_to_nostr(
    request: Request,
    container: Any = Depends(get_container),
    note: str = Form(...),
):
    from integrations.publishing_provider import PublishRequest

    current_project = _current_project_for_request(request)
    if not current_project:
        return {"success": False, "message": "project_id is required"}
    _require_project_access(request, current_project.project_id, "publisher")

    publish_request = PublishRequest(content=note, platform="nostr")
    result = container.publishing_manager.publish(
        publish_request, provider_name="nostr"
    )

    return {"success": result.success, "message": result.error or "Published"}
