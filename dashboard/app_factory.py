"""Application factory composing ``AppContainer`` into a FastAPI app."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from fastapi import FastAPI
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles

from dashboard.routes import iter_routers

if TYPE_CHECKING:
    from dashboard.app_container import AppContainer


def build_app(container: "AppContainer", *, host: Optional[str] = None) -> FastAPI:
    """Construct the FastAPI application from a wired ``AppContainer``.

    ``host`` is optional: when provided it overrides
    ``container.access_policy.host``; when omitted the container's existing
    host (set at ``AppContainer`` construction) is preserved. This avoids
    silently resetting a non-default host for programmatic callers that
    construct ``AppContainer(host=...)`` and call ``build_app(container)``
    without re-passing ``host``.
    """
    from dashboard.middleware.auth import AuthMiddleware
    from dashboard.middleware.csrf import CSRFService
    from dashboard.middleware.rate_limit import LoginRateLimiter, RateLimiter
    from dashboard.middleware.request_id import RequestIdMiddleware
    from dashboard.middleware.security_headers import SecurityHeaders

    if host is not None:
        container.access_policy.host = host
    container.access_policy.validate_startup()

    if container.csrf is None:
        container.csrf = CSRFService()
    if container.rate_limiter is None:
        container.rate_limiter = RateLimiter()
    if container.login_limiter is None:
        container.login_limiter = LoginRateLimiter()
    if container.security_headers is None:
        container.security_headers = SecurityHeaders()
    if container.auth_middleware is None:
        container.auth_middleware = AuthMiddleware(
            access_policy=container.access_policy, container=container
        )
    if container.request_id_middleware is None:
        container.request_id_middleware = RequestIdMiddleware()

    app = FastAPI(title="Draper Unified Dashboard")
    app.state.container = container

    media_path = Path("data/media")
    media_path.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

    app.add_middleware(BaseHTTPMiddleware, dispatch=container.security_headers)
    app.add_middleware(BaseHTTPMiddleware, dispatch=container.csrf)
    app.add_middleware(BaseHTTPMiddleware, dispatch=container.rate_limiter)
    app.add_middleware(BaseHTTPMiddleware, dispatch=container.auth_middleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=container.request_id_middleware)

    @app.get("/api/csrf-token")
    async def get_csrf_token():
        return {"success": True, "csrf_token": container.csrf.current_token()}

    @app.get("/health")
    async def health():
        return {"success": True, "status": "ok"}

    @app.get("/favicon.ico")
    async def favicon():
        return Response(status_code=204)

    for router in iter_routers():
        app.include_router(router)

    return app
