"""Plan 03-03 Task 1: dashboard/routes/analytics.py regression contracts.

Asserts the three properties the app-factory swap (Plan 03-04) relies on:

1. ``dashboard.routes.analytics`` imports in isolation.
2. ``analytics.router`` registers /api/analytics, /api/providers, /api/status.
3. The status / analytics / providers routes preserve the response shapes
   of the inline closures in ``dashboard/unified_dashboard.py:main()``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import APIRouter
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


@pytest.fixture
def app(container):
    from dashboard.app_factory import build_app

    return build_app(container)


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


EXPECTED_ANALYTICS_PATHS = {
    "/api/analytics",
    "/api/providers",
    "/api/status",
}


class TestImportIsolation:
    def test_import_succeeds_without_dashboard_construction(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        start = time.monotonic()
        import importlib

        module = importlib.import_module("dashboard.routes.analytics")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)


class TestRouteRegistration:
    def test_router_registers_every_analytics_path(self):
        from dashboard.routes import analytics

        paths = {route.path for route in analytics.router.routes}
        missing = EXPECTED_ANALYTICS_PATHS - paths
        assert not missing, f"Missing paths in analytics.router: {sorted(missing)}"

    def test_router_has_three_routes(self):
        from dashboard.routes import analytics

        assert len(analytics.router.routes) == 3

    def test_iter_routers_yields_analytics(self):
        from dashboard.routes import analytics, iter_routers

        routers = list(iter_routers())
        assert analytics.router in routers


class TestBehavioralEquivalence:
    def test_get_api_status_returns_success_with_pipeline_keys(
        self, container, client
    ):
        token = container.csrf.current_token()
        resp = client.get("/api/status", headers={"x-csrf-token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "pipeline" in body
        pipeline = body["pipeline"]
        for key in ("total", "pending", "approved", "scheduled", "rejected"):
            assert key in pipeline
        assert "providers" in body
        assert "jobs" in body

    def test_get_api_analytics_returns_success_with_analytics_block(
        self, container, client
    ):
        token = container.csrf.current_token()
        resp = client.get("/api/analytics", headers={"x-csrf-token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "analytics" in body
        assert "period" in body

    def test_get_api_providers_returns_success_with_providers_list(
        self, container, client
    ):
        token = container.csrf.current_token()
        resp = client.get("/api/providers", headers={"x-csrf-token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["providers"], list)
