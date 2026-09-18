"""Plan 03-01 Task 3: build_app factory + routes auto-discovery."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def container(project_data_dir: Any, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
    from dashboard.app_container import AppContainer

    return AppContainer(data_dir=str(project_data_dir))


class TestBuildApp:
    def test_returns_fastapi_with_expected_title(self, container):
        from dashboard.app_factory import build_app

        app = build_app(container)
        assert isinstance(app, FastAPI)
        assert app.title == "Draper Unified Dashboard"

    def test_app_state_container_is_input(self, container):
        from dashboard.app_factory import build_app

        app = build_app(container)
        assert app.state.container is container

    def test_health_endpoint(self, container):
        from dashboard.app_factory import build_app

        client = TestClient(build_app(container))
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "status": "ok"}

    def test_csrf_token_endpoint(self, container):
        from dashboard.app_factory import build_app

        client = TestClient(build_app(container))
        resp = client.get("/api/csrf-token")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        token = body["csrf_token"]
        assert isinstance(token, str)
        assert len(token) == 64

    def test_favicon_endpoint(self, container):
        from dashboard.app_factory import build_app

        client = TestClient(build_app(container))
        resp = client.get("/favicon.ico")
        assert resp.status_code == 204

    def test_security_headers_active(self, container):
        from dashboard.app_factory import build_app

        client = TestClient(build_app(container))
        resp = client.get("/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_app_factory_constructs_middleware_on_container(self, container):
        from dashboard.app_factory import build_app
        from dashboard.middleware import AuthMiddleware, CSRFService, RateLimiter, SecurityHeaders

        build_app(container)
        assert isinstance(container.security_headers, SecurityHeaders)
        assert isinstance(container.csrf, CSRFService)
        assert isinstance(container.rate_limiter, RateLimiter)
        assert isinstance(container.auth_middleware, AuthMiddleware)

    def test_build_app_preserves_container_host_when_host_omitted(
        self, project_data_dir, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
        from dashboard.app_container import AppContainer
        from dashboard.app_factory import build_app

        container = AppContainer(data_dir=str(project_data_dir), host="localhost")
        build_app(container)
        assert container.access_policy.host == "localhost"

    def test_build_app_explicit_host_overrides_container_host(
        self, project_data_dir, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
        from dashboard.app_container import AppContainer
        from dashboard.app_factory import build_app

        container = AppContainer(data_dir=str(project_data_dir), host="localhost")
        build_app(container, host="127.0.0.1")
        assert container.access_policy.host == "127.0.0.1"


class TestMiddlewareOrder:
    """When auth is enabled, an unauthenticated API request hits auth FIRST
    (outermost) and returns 401, not 403 from CSRF. When auth is disabled
    (DRAPER_ALLOW_UNAUTHENTICATED_LOCAL=1), CSRF still applies on POST.
    """

    def test_auth_enabled_unauthenticated_api_returns_401(
        self, project_data_dir, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", raising=False)
        monkeypatch.setenv("DRAPER_DASHBOARD_TOKEN", "fixture-dashboard-token-1234")
        from dashboard.app_container import AppContainer
        from dashboard.app_factory import build_app

        container = AppContainer(data_dir=str(project_data_dir))
        client = TestClient(build_app(container))
        resp = client.post("/api/generate", json={"count": 1})
        assert resp.status_code == 401
        assert resp.json() == {"success": False, "error": "Unauthorized"}

    def test_local_dev_csrf_still_active_on_post(self, container):
        from dashboard.app_factory import build_app

        client = TestClient(build_app(container))
        resp = client.post("/api/generate", json={"count": 1})
        assert resp.status_code == 403
        assert resp.json() == {"success": False, "error": "CSRF token missing or invalid"}

    def test_local_dev_post_with_csrf_token_passes_csrf(self, container):
        from dashboard.app_factory import build_app

        app = build_app(container)
        client = TestClient(app)
        token = container.csrf.current_token()
        resp = client.post("/api/generate", json={"count": 1}, headers={"x-csrf-token": token})
        assert resp.status_code != 403


class TestIterRoutersDiscovery:
    def test_iter_routers_returns_iterable(self):
        from dashboard.routes import iter_routers

        result = list(iter_routers())
        assert isinstance(result, list)

    def test_iter_routers_yields_apirouter_instances(self):
        from dashboard.routes import iter_routers

        routers = list(iter_routers())
        for entry in routers:
            assert isinstance(entry, APIRouter)

    def test_routes_package_importable(self):
        from dashboard import routes

        assert hasattr(routes, "iter_routers")
