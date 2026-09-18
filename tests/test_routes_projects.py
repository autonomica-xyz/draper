"""Plan 03-02 Task 2: dashboard/routes/projects.py regression contracts.

Asserts:
1. ``dashboard.routes.projects`` imports in isolation (criterion #2).
2. ``projects.router`` registers every /api/projects* path the monolith owns.
3. Behavioral equivalence for GET /api/projects, POST /api/projects,
   DELETE /api/projects/{id}, GET /api/projects/{id}/content-plan.
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


EXPECTED_PROJECT_PATHS = {
    "/api/projects",
    "/api/projects/{project_id}",
    "/api/projects/{project_id}/access/tokens",
    "/api/projects/{project_id}/access/tokens/{token_id}",
    "/api/projects/{project_id}/mcp-config",
    "/api/projects/{project_id}/content-plan",
    "/api/projects/{project_id}/content-plan/download",
    "/api/projects/{project_id}/content-plan/upload",
    "/api/projects/{project_id}/brand-voice",
    "/api/projects/{project_id}/social-profiles",
    "/api/projects/{project_id}/social-profiles/toggle",
    "/api/projects/{project_id}/posting-strategy",
    "/api/projects/{project_id}/provider-mapping",
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

        module = importlib.import_module("dashboard.routes.projects")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)


class TestRouteRegistration:
    def test_router_registers_every_project_path(self):
        from dashboard.routes import projects

        paths = {route.path for route in projects.router.routes}
        missing = EXPECTED_PROJECT_PATHS - paths
        assert not missing, f"Missing paths in projects.router: {sorted(missing)}"

    def test_router_has_at_least_13_routes(self):
        from dashboard.routes import projects

        assert len(projects.router.routes) >= 13

    def test_iter_routers_yields_projects(self):
        from dashboard.routes import iter_routers, projects

        routers = list(iter_routers())
        assert projects.router in routers


class TestBehavioralEquivalence:
    def test_get_api_projects_returns_success_with_projects_list(
        self, container, client
    ):
        container.project_manager.create_project(
            name="Listed", description="shows up"
        )
        token = container.csrf.current_token()
        resp = client.get("/api/projects", headers={"x-csrf-token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert "projects" in body
        assert isinstance(body["projects"], list)
        assert any(p["name"] == "Listed" for p in body["projects"])

    def test_post_api_projects_creates_and_returns_project(self, container, client):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/projects",
            json={"name": "New Project", "description": "from test"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["project"]["name"] == "New Project"
        assert body["project"]["description"] == "from test"

    def test_post_api_projects_requires_name(self, container, client):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/projects",
            json={"name": "", "description": "missing name"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "error" in body

    def test_delete_api_projects_returns_success(self, container, client):
        created = container.project_manager.create_project(name="To Delete")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.delete(
            f"/api/projects/{project_id}",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_get_content_plan_returns_content_string(self, container, client):
        created = container.project_manager.create_project(name="Plan Project")
        project_id = created.project_id
        container.project_manager.save_content_plan(project_id, "# Plan\n\nbody")
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/projects/{project_id}/content-plan",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["content"] == "# Plan\n\nbody"
        assert "last_updated" in body

    def test_get_content_plan_returns_seeded_default_when_unset(
        self, container, client
    ):
        created = container.project_manager.create_project(name="Empty Plan")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/projects/{project_id}/content-plan",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "content" in body
        assert isinstance(body["content"], str)
        assert "last_updated" in body

    def test_post_content_plan_saves_markdown(self, container, client):
        created = container.project_manager.create_project(name="Savable")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/content-plan",
            json={"content": "# Saved\n\nvia API"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "last_updated" in body
        assert (
            container.project_manager.get_content_plan(project_id)
            == "# Saved\n\nvia API"
        )

    def test_get_brand_voice_returns_markdown_with_is_default_flag(
        self, container, client
    ):
        created = container.project_manager.create_project(name="Voice Project")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/projects/{project_id}/brand-voice",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "content" in body
        assert isinstance(body["content"], str)
        assert "is_default" in body
        assert isinstance(body["is_default"], bool)

    def test_get_provider_mapping_returns_default(self, container, client):
        created = container.project_manager.create_project(name="Mapping Project")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/projects/{project_id}/provider-mapping",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "mapping" in body
