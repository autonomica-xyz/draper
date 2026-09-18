"""Plan 03-03 Task 2: dashboard/routes/ideas.py regression contracts.

Asserts the three properties the app-factory swap (Plan 03-04) relies on:

1. ``dashboard.routes.ideas`` imports in isolation.
2. ``ideas.router`` registers every idea-lab path the monolith owns.
3. Representative routes (materials CRUD, mining trigger) preserve the
   response shapes of the inline closures in
   ``dashboard/unified_dashboard.py:main()``.
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


EXPECTED_IDEAS_PATHS = {
    "/api/ideas/materials",
    "/api/ideas/materials/{material_id}",
    "/api/ideas/materials/{material_id}/enrich",
    "/api/ideas/materials/{material_id}/generate-ideas",
    "/api/ideas/materials/enrich-batch",
    "/api/ideas/generate-ideas-batch",
    "/api/ideas/ideas",
    "/api/ideas/ideas/{idea_id}",
    "/api/ideas/ideas/{idea_id}/evaluate",
    "/api/ideas/ideas/{idea_id}/approve-and-generate",
    "/api/ideas/mining/trigger",
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

        module = importlib.import_module("dashboard.routes.ideas")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)


class TestRouteRegistration:
    def test_router_registers_every_idea_path(self):
        from dashboard.routes import ideas

        paths = {route.path for route in ideas.router.routes}
        missing = EXPECTED_IDEAS_PATHS - paths
        assert not missing, f"Missing paths in ideas.router: {sorted(missing)}"

    def test_router_has_seventeen_routes(self):
        from dashboard.routes import ideas

        assert len(ideas.router.routes) == 17

    def test_iter_routers_yields_ideas(self):
        from dashboard.routes import ideas, iter_routers

        routers = list(iter_routers())
        assert ideas.router in routers


class TestBehavioralEquivalence:
    PROJECT_ID = "ideas-test-project"

    def test_post_api_ideas_materials_returns_success_with_material(
        self, container, client
    ):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/ideas/materials",
            json={
                "project_id": self.PROJECT_ID,
                "text_content": "Sample material content for tests.",
                "title": "Sample Material",
            },
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "material" in body

    def test_post_api_ideas_materials_requires_project_id(self, container, client):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/ideas/materials",
            json={"text_content": "missing project"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "project_id" in body["error"]

    def test_get_api_ideas_materials_returns_success_with_items(
        self, container, client
    ):
        token = container.csrf.current_token()
        client.post(
            "/api/ideas/materials",
            json={
                "project_id": self.PROJECT_ID,
                "text_content": "Seed material",
            },
            headers={"x-csrf-token": token},
        )
        resp = client.get(
            f"/api/ideas/materials?project_id={self.PROJECT_ID}",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "items" in body
        assert isinstance(body["items"], list)
        assert body["total"] == len(body["items"])

    def test_post_api_ideas_mining_trigger_returns_counts(
        self, container, client, monkeypatch
    ):
        token = container.csrf.current_token()

        captured = {}

        def fake_enrich(project_id):
            captured["enrich_project_id"] = project_id
            return {
                "total": 1,
                "enriched": 1,
                "partial": 0,
                "failed": 0,
                "skipped": 0,
            }

        def fake_generate(project_id):
            captured["generate_project_id"] = project_id
            return {
                "generated": 2,
                "skipped": 0,
                "errors": 0,
                "total_materials": 1,
            }

        monkeypatch.setattr(container.idea_lab, "enrich_all_pending", fake_enrich)
        monkeypatch.setattr(
            container.idea_lab, "generate_ideas_for_project", fake_generate
        )

        resp = client.post(
            "/api/ideas/mining/trigger",
            json={"project_id": self.PROJECT_ID},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["enrichment"] == {
            "total": 1,
            "enriched": 1,
            "partial": 0,
            "failed": 0,
            "skipped": 0,
        }
        assert body["ideas"] == {
            "generated": 2,
            "skipped": 0,
            "errors": 0,
            "total_materials": 1,
        }
        assert captured["enrich_project_id"] == self.PROJECT_ID
        assert captured["generate_project_id"] == self.PROJECT_ID

    def test_post_api_ideas_mining_trigger_requires_project_id(
        self, container, client
    ):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/ideas/mining/trigger",
            json={},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert "project_id" in body["error"]

    def test_get_api_ideas_ideas_returns_success_with_items(self, container, client):
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/ideas/ideas?project_id={self.PROJECT_ID}",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "items" in body
        assert isinstance(body["items"], list)
