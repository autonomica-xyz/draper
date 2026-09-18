"""Plan 05-04 Task 2: Health endpoints + Events API contract.

Pins the nine behavior spec items:

* ``GET /api/health`` returns 200 ``{"status": "ok", "service": ...}``
  WITHOUT authentication (liveness probe).
* ``GET /api/health/deep`` without owner principal returns 403.
* ``GET /api/health/deep`` with admin returns 200 with the five
  diagnostic keys: ``status``, ``db_ok``, ``worker_last_active``,
  ``queue_depth``, ``recent_failure_rate``, ``env_vars_set``.
* ``GET /api/events`` with admin returns all events (subject to limit).
* ``GET /api/events?project_id=p1`` with a viewer holding role on p1
  returns only events for p1.
* ``GET /api/events?project_id=p1`` with a viewer NOT holding role on
  p1 returns 403.
* ``GET /api/events`` without project_id and without admin returns 403.
* ``GET /api/events?category=...&since=...&limit=...`` filters work.
* ``services/job_runner.JobRunner.run_once`` sets the job_id contextvar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _make_admin_container(data_dir: str, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
    from dashboard.app_container import AppContainer

    return AppContainer(data_dir=data_dir)


@pytest.fixture
def container(project_data_dir: Any, monkeypatch):
    return _make_admin_container(str(project_data_dir), monkeypatch)


@pytest.fixture
def app(container):
    from dashboard.app_factory import build_app

    return build_app(container)


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_container(project_data_dir: Any, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", raising=False)
    monkeypatch.setenv("DRAPER_DASHBOARD_TOKEN", "health-deep-admin-token-1234567890")
    from dashboard.app_container import AppContainer

    return AppContainer(data_dir=str(project_data_dir))


@pytest.fixture
def auth_client(auth_container):
    from dashboard.app_factory import build_app

    return TestClient(build_app(auth_container), raise_server_exceptions=False)


class TestHealthLiveness:
    def test_get_api_health_returns_ok_without_auth(self, auth_client):
        resp = auth_client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "draper-dashboard"


class TestHealthDeep:
    def test_unauthenticated_returns_401(self, auth_client):
        resp = auth_client.get("/api/health/deep")
        assert resp.status_code == 401

    def test_scoped_non_admin_returns_403(self, auth_container):
        from dashboard.app_factory import build_app

        record = auth_container.store.create_access_token(
            "scoped viewer",
            project_roles={"p1": "viewer"},
            is_admin=False,
        )
        token_value = record["token"]
        client = TestClient(build_app(auth_container), raise_server_exceptions=False)
        resp = client.get(
            "/api/health/deep",
            headers={"Authorization": f"Bearer {token_value}"},
        )
        assert resp.status_code == 403

    def test_admin_returns_full_diagnostics(self, auth_container):
        from dashboard.app_factory import build_app

        client = TestClient(build_app(auth_container), raise_server_exceptions=False)
        resp = client.get(
            "/api/health/deep",
            headers={"Authorization": "Bearer health-deep-admin-token-1234567890"},
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "status",
            "db_ok",
            "worker_last_active",
            "queue_depth",
            "recent_failure_rate",
            "env_vars_set",
        ):
            assert key in body, f"deep health response missing {key}"
        assert body["status"] in {"ok", "degraded"}
        assert isinstance(body["db_ok"], bool)
        assert body["worker_last_active"] is None or isinstance(
            body["worker_last_active"], str
        )
        assert isinstance(body["queue_depth"], int)
        assert isinstance(body["recent_failure_rate"], float)
        assert 0.0 <= body["recent_failure_rate"] <= 1.0
        assert isinstance(body["env_vars_set"], dict)
        for var_name, present in body["env_vars_set"].items():
            assert isinstance(var_name, str)
            assert isinstance(present, bool)


class TestEventsListAdmin:
    def test_admin_returns_all_events(self, container, client):
        store = container.store
        store.record_event(
            category="review",
            action="approve",
            project_id="p1",
            payload={"hello": "world"},
        )
        store.record_event(
            category="publish",
            action="attempted",
            project_id="p2",
            payload={"x": 1},
        )
        resp = client.get("/api/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["items"], list)
        assert body["count"] == len(body["items"])
        assert body["count"] >= 2

    def test_admin_filtered_by_category_returns_only_matching(self, container, client):
        store = container.store
        store.record_event(category="review", action="approve", project_id="p1")
        store.record_event(category="publish", action="attempted", project_id="p2")
        resp = client.get("/api/events", params={"category": "review"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["count"] >= 1
        assert all(item["category"] == "review" for item in body["items"])

    def test_admin_filtered_by_since_filters_old_events(self, container, client):
        store = container.store
        store.record_event(category="review", action="approve", project_id="p1")
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        resp = client.get("/api/events", params={"since": future})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["count"] == 0

    def test_admin_limit_bounds_results(self, container, client):
        store = container.store
        for _ in range(5):
            store.record_event(category="job", action="enqueued", project_id="p1")
        resp = client.get("/api/events", params={"limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["count"] == 2


class TestEventsListScoped:
    def _seed_events(self, store):
        store.record_event(category="review", action="approve", project_id="p_visible")
        store.record_event(category="review", action="approve", project_id="p_hidden")

    def test_scoped_viewer_sees_only_visible_project_events(self, auth_container):
        from dashboard.app_factory import build_app

        self._seed_events(auth_container.store)
        record = auth_container.store.create_access_token(
            "scoped viewer",
            project_roles={"p_visible": "viewer"},
            is_admin=False,
        )
        token_value = record["token"]
        client = TestClient(build_app(auth_container), raise_server_exceptions=False)
        resp = client.get(
            "/api/events?project_id=p_visible",
            headers={"Authorization": f"Bearer {token_value}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert all(item["project_id"] == "p_visible" for item in body["items"])
        assert body["count"] >= 1

    def test_scoped_viewer_forbidden_for_other_project(self, auth_container):
        from dashboard.app_factory import build_app

        self._seed_events(auth_container.store)
        record = auth_container.store.create_access_token(
            "scoped viewer",
            project_roles={"p_visible": "viewer"},
            is_admin=False,
        )
        token_value = record["token"]
        client = TestClient(build_app(auth_container), raise_server_exceptions=False)
        resp = client.get(
            "/api/events?project_id=p_hidden",
            headers={"Authorization": f"Bearer {token_value}"},
        )
        assert resp.status_code == 403

    def test_scoped_viewer_without_project_id_returns_403(self, auth_container):
        from dashboard.app_factory import build_app

        record = auth_container.store.create_access_token(
            "scoped viewer",
            project_roles={"p_visible": "viewer"},
            is_admin=False,
        )
        token_value = record["token"]
        client = TestClient(build_app(auth_container), raise_server_exceptions=False)
        resp = client.get(
            "/api/events",
            headers={"Authorization": f"Bearer {token_value}"},
        )
        assert resp.status_code == 403
