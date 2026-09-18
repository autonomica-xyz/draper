"""Plan 03-02 Task 3: dashboard/routes/integrations.py regression contracts.

Asserts:
1. ``dashboard.routes.integrations`` imports in isolation (criterion #2).
2. ``integrations.router`` registers every /api/projects/{id}/integrations*
   path the monolith owns.
3. Behavioral equivalence for GET /api/projects/{id}/integrations.
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


EXPECTED_INTEGRATIONS_PATHS = {
    "/api/projects/{project_id}/integrations",
    "/api/projects/{project_id}/integrations/typefully",
    "/api/projects/{project_id}/integrations/typefully/test",
    "/api/projects/{project_id}/integrations/late",
    "/api/projects/{project_id}/integrations/late/test",
    "/api/projects/{project_id}/integrations/nostr",
    "/api/projects/{project_id}/integrations/nostr/test",
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

        module = importlib.import_module("dashboard.routes.integrations")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)


class TestRouteRegistration:
    def test_router_registers_every_integration_path(self):
        from dashboard.routes import integrations

        paths = {route.path for route in integrations.router.routes}
        missing = EXPECTED_INTEGRATIONS_PATHS - paths
        assert not missing, f"Missing paths in integrations.router: {sorted(missing)}"

    def test_router_has_nine_routes(self):
        from dashboard.routes import integrations

        assert len(integrations.router.routes) == 9

    def test_iter_routers_yields_integrations(self):
        from dashboard.routes import integrations, iter_routers

        routers = list(iter_routers())
        assert integrations.router in routers


class TestBehavioralEquivalence:
    def test_get_integrations_returns_typefully_block(self, container, client):
        created = container.project_manager.create_project(name="Int Project")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/projects/{project_id}/integrations",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "typefully" in body
        typefully = body["typefully"]
        assert "env_configured" in typefully
        assert "drafts_enabled" in typefully
        assert "auto_schedule" in typefully

    def test_get_late_integration_returns_configured_flag(
        self, container, client
    ):
        created = container.project_manager.create_project(name="Late Project")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/projects/{project_id}/integrations/late",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "configured" in body
        assert isinstance(body["configured"], bool)

    def test_save_typefully_integration_returns_success(self, container, client):
        created = container.project_manager.create_project(name="Save TF")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/integrations/typefully",
            json={"drafts_enabled": True, "auto_schedule": False},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_get_nostr_integration_returns_configured_flag(
        self, container, client
    ):
        created = container.project_manager.create_project(name="Nostr Project")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/projects/{project_id}/integrations/nostr",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "configured" in body
        assert isinstance(body["configured"], bool)
        assert "api_key" in body

    def test_save_nostr_integration_returns_success(self, container, client):
        created = container.project_manager.create_project(name="Save Nostr")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/integrations/nostr",
            json={"api_key": "nsec1testkey"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_test_nostr_without_key_returns_error(self, container, client):
        created = container.project_manager.create_project(name="No Nostr Key")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/integrations/nostr/test",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "error" in body

    def test_test_typefully_without_key_returns_error(self, container, client):
        created = container.project_manager.create_project(name="No Key")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/integrations/typefully/test",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "error" in body
