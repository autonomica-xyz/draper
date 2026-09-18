"""Plan 03-03 Task 1: dashboard/routes/jobs.py regression contracts.

Asserts the three properties the app-factory swap (Plan 03-04) relies on:

1. ``dashboard.routes.jobs`` imports in isolation (no UnifiedDashboard built).
2. ``jobs.router`` registers every job-related path the monolith owns.
3. Representative routes (list, get, sync-analytics, run-next, cancel)
   preserve the response shapes of the inline closures in
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


EXPECTED_JOBS_PATHS = {
    "/api/jobs",
    "/api/jobs/sync-analytics",
    "/api/jobs/run-next",
    "/api/jobs/recover-stuck",
    "/api/jobs/{job_id}",
    "/api/jobs/{job_id}/cancel",
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

        module = importlib.import_module("dashboard.routes.jobs")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)


class TestRouteRegistration:
    def test_router_registers_every_job_path(self):
        from dashboard.routes import jobs

        paths = {route.path for route in jobs.router.routes}
        missing = EXPECTED_JOBS_PATHS - paths
        assert not missing, f"Missing paths in jobs.router: {sorted(missing)}"

    def test_router_has_five_routes(self):
        from dashboard.routes import jobs

        assert len(jobs.router.routes) == 6

    def test_iter_routers_yields_jobs(self):
        from dashboard.routes import iter_routers, jobs

        routers = list(iter_routers())
        assert jobs.router in routers


class TestBehavioralEquivalence:
    def test_get_api_jobs_returns_success_with_items_list(self, container, client):
        token = container.csrf.current_token()
        resp = client.get("/api/jobs", headers={"x-csrf-token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "items" in body
        assert isinstance(body["items"], list)
        assert body["total"] == len(body["items"])

    def test_get_api_jobs_with_invalid_limit_returns_error(self, container, client):
        token = container.csrf.current_token()
        resp = client.get("/api/jobs?limit=abc", headers={"x-csrf-token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "limit must be an integer"

    def test_post_api_jobs_sync_analytics_returns_success_with_job_id(
        self, container, client
    ):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/jobs/sync-analytics",
            json={},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "job_id" in body
        assert "job" in body

    def test_post_api_jobs_run_next_returns_success_message_when_no_jobs(
        self, container, client
    ):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/jobs/run-next",
            json={},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["ran"] is False
        assert body["message"] == "No queued jobs"

    def test_get_api_job_by_id_returns_job_record(self, container, client):
        token = container.csrf.current_token()
        enqueue_resp = client.post(
            "/api/jobs/sync-analytics",
            json={},
            headers={"x-csrf-token": token},
        )
        job_id = enqueue_resp.json()["job_id"]
        resp = client.get(f"/api/jobs/{job_id}", headers={"x-csrf-token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["job"]["job_id"] == job_id

    def test_get_api_job_unknown_id_returns_not_found(self, container, client):
        token = container.csrf.current_token()
        resp = client.get(
            "/api/jobs/nonexistent-job",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "Job not found"

    def test_post_api_job_cancel_returns_cancelled_job(self, container, client):
        token = container.csrf.current_token()
        enqueue_resp = client.post(
            "/api/jobs/sync-analytics",
            json={},
            headers={"x-csrf-token": token},
        )
        job_id = enqueue_resp.json()["job_id"]
        resp = client.post(
            f"/api/jobs/{job_id}/cancel", headers={"x-csrf-token": token}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["job"]["job_id"] == job_id


class TestJobVisibilityFields:
    def test_get_api_jobs_response_items_carry_visibility_fields(self, container, client):
        token = container.csrf.current_token()
        client.post(
            "/api/jobs/sync-analytics",
            json={},
            headers={"x-csrf-token": token},
        )
        resp = client.get("/api/jobs", headers={"x-csrf-token": token})
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["items"], list)
        assert len(body["items"]) >= 1
        for item in body["items"]:
            for key in (
                "attempts",
                "started_at",
                "finished_at",
                "failure_category",
                "next_retry_at",
            ):
                assert key in item, f"missing key {key} in job item"

    def test_get_api_job_by_id_response_carries_visibility_fields(
        self, container, client
    ):
        token = container.csrf.current_token()
        enqueue_resp = client.post(
            "/api/jobs/sync-analytics",
            json={},
            headers={"x-csrf-token": token},
        )
        job_id = enqueue_resp.json()["job_id"]
        resp = client.get(f"/api/jobs/{job_id}", headers={"x-csrf-token": token})
        body = resp.json()
        assert body["success"] is True
        for key in (
            "attempts",
            "started_at",
            "finished_at",
            "failure_category",
            "next_retry_at",
        ):
            assert key in body["job"], f"missing key {key} in job envelope"


class TestRecoverStuck:
    def test_post_recover_stuck_with_no_stuck_jobs_returns_empty_recovered(
        self, container, client
    ):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/jobs/recover-stuck",
            json={"threshold_minutes": 30},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["recovered"] == []
        assert body["threshold_minutes"] == 30
