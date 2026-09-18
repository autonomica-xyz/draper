"""Plan 03-03 Task 3: dashboard/routes/generation.py regression contracts.

Asserts the three properties the app-factory swap (Plan 03-04) relies on:

1. ``dashboard.routes.generation`` imports in isolation.
2. ``generation.router`` registers /api/generate, /api/generate/image,
   /api/generate/carousel.
3. POST /api/generate preserves both the async (job-queue short-circuit)
   and synchronous (generator.generate_batch) response shapes of the
   inline closure in ``dashboard/unified_dashboard.py:main()``.

Threat T-03-03-03: ``{async: true}`` MUST short-circuit and return
``{success, async, job_id, job}`` without ever calling
``generator.generate_batch``. Verified by monkeypatch.
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

    container = AppContainer(data_dir=str(project_data_dir))
    container.project_manager.create_project(
        name="Generation Test Project",
        slug="gen-test",
        description="Test project for generation routes",
    )
    return container


@pytest.fixture
def app(container):
    from dashboard.app_factory import build_app

    return build_app(container)


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def project_id(container):
    projects = container.project_manager.list_projects()
    return projects[0].project_id


EXPECTED_GENERATION_PATHS = {
    "/api/generate",
    "/api/generate/image",
    "/api/generate/carousel",
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

        module = importlib.import_module("dashboard.routes.generation")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)


class TestRouteRegistration:
    def test_router_registers_every_generation_path(self):
        from dashboard.routes import generation

        paths = {route.path for route in generation.router.routes}
        missing = EXPECTED_GENERATION_PATHS - paths
        assert not missing, f"Missing paths in generation.router: {sorted(missing)}"

    def test_router_has_three_routes(self):
        from dashboard.routes import generation

        assert len(generation.router.routes) == 3

    def test_iter_routers_yields_generation(self):
        from dashboard.routes import generation, iter_routers

        routers = list(iter_routers())
        assert generation.router in routers


class TestBehavioralEquivalence:
    def test_post_api_generate_async_returns_job_id_without_calling_generator(
        self, container, client, project_id, monkeypatch
    ):
        token = container.csrf.current_token()

        class _FailGenerator:
            def generate_batch(self, *args, **kwargs):
                raise AssertionError(
                    "generate_batch must NOT be called when async=True"
                )

        container.generator = _FailGenerator()

        resp = client.post(
            "/api/generate",
            json={
                "count": 1,
                "platform": "twitter",
                "project_id": project_id,
                "async": True,
            },
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["async"] is True
        assert "job_id" in body
        assert "job" in body

    def test_post_api_generate_sync_calls_generator_and_returns_review_ids(
        self, container, client, project_id, monkeypatch
    ):
        token = container.csrf.current_token()

        class _FakeGenerator:
            def generate_batch(self, *, count=1, platforms=None, repurpose=False):
                return {
                    "posts": [
                        {
                            "platform": "twitter",
                            "content": f"Generated post {i}",
                            "content_type": "tweet",
                        }
                        for i in range(count)
                    ]
                }

        container.generator = _FakeGenerator()

        resp = client.post(
            "/api/generate",
            json={
                "count": 2,
                "platform": "twitter",
                "project_id": project_id,
            },
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["count"] == 2
        assert len(body["review_ids"]) == 2
        assert len(body["items"]) == 2

    def test_post_api_generate_binds_generator_to_requested_project(
        self, container, client, project_id
    ):
        token = container.csrf.current_token()

        class _ProjectAwareGenerator:
            def __init__(self):
                self.project = None
                self.seen_projects = []

            def generate_batch(self, *, count=1, platforms=None, repurpose=False):
                self.seen_projects.append(self.project.project_id)
                return {
                    "posts": [
                        {
                            "platform": platforms[0] if platforms else "twitter",
                            "content": "Project-scoped generated post",
                            "content_type": "tweet",
                        }
                    ]
                }

        generator = _ProjectAwareGenerator()
        container.generator = generator

        resp = client.post(
            "/api/generate",
            json={
                "count": 1,
                "platform": "twitter",
                "project_id": project_id,
            },
            headers={"x-csrf-token": token},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert generator.seen_projects == [project_id]
        assert generator.project is None

    def test_post_api_generate_requires_valid_project_id(
        self, container, client, monkeypatch
    ):
        token = container.csrf.current_token()

        class _FailGenerator:
            def generate_batch(self, *args, **kwargs):
                raise AssertionError(
                    "generate_batch must NOT be called on validation fail"
                )

        container.generator = _FailGenerator()

        resp = client.post(
            "/api/generate",
            json={
                "count": 1,
                "platform": "twitter",
                "project_id": "nonexistent-project-id",
            },
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "project_id" in body["error"]

    def test_post_api_generate_image_requires_prompt(self, container, client):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/generate/image",
            json={},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "prompt is required"

    def test_post_api_generate_carousel_requires_content(self, container, client):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/generate/carousel",
            json={},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "content is required"
