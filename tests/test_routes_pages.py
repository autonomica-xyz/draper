"""Plan 03-03 Task 3: dashboard/routes/pages.py regression contracts.

Asserts the three properties the app-factory swap (Plan 03-04) relies on:

1. ``dashboard.routes.pages`` imports in isolation.
2. ``pages.router`` registers every HTML page path the monolith owns.
3. Representative routes (home, login GET/POST, logout) preserve the
   response shapes of the inline closures in
   ``dashboard/unified_dashboard.py:main()``.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
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


EXPECTED_PAGES_PATHS = {
    "/login",
    "/logout",
    "/",
    "/analytics",
    "/past",
    "/scheduled",
    "/evaluate",
    "/generate",
    "/nostr",
    "/nostr/publish-all",
    "/nostr/publish-note",
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

        module = importlib.import_module("dashboard.routes.pages")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)


class TestRouteRegistration:
    def test_router_registers_every_page_path(self):
        from dashboard.routes import pages

        paths = {route.path for route in pages.router.routes}
        missing = EXPECTED_PAGES_PATHS - paths
        assert not missing, f"Missing paths in pages.router: {sorted(missing)}"

    def test_router_has_thirteen_routes(self):
        from dashboard.routes import pages

        assert len(pages.router.routes) == 13

    def test_iter_routers_yields_pages(self):
        from dashboard.routes import iter_routers, pages

        routers = list(iter_routers())
        assert pages.router in routers


class TestBehavioralEquivalence:
    def test_get_home_returns_200_html(self, container, client):
        token = container.csrf.current_token()
        resp = client.get("/", headers={"x-csrf-token": token})
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_scheduled_posts_handles_offset_and_invalid_timestamps(self, container):
        future = (datetime.now(timezone.utc) + timedelta(days=1)).astimezone(
            timezone(timedelta(hours=-4))
        )
        container.store.save_scheduled_record(
            container.store.normalize_scheduled_record(
                {
                    "post_id": "offset-scheduled",
                    "post_data": {"content": "future"},
                    "scheduled_at": future.isoformat(),
                    "status": "scheduled",
                }
            )
        )
        container.store.save_scheduled_record(
            container.store.normalize_scheduled_record(
                {
                    "post_id": "invalid-scheduled",
                    "post_data": {"content": "invalid"},
                    "scheduled_at": "not-a-timestamp",
                    "status": "scheduled",
                }
            )
        )

        scheduled = container.dashboard.get_scheduled_posts()

        assert [post["post_id"] for post in scheduled] == ["offset-scheduled"]

    def test_get_login_returns_200_html(self, container, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_post_login_with_valid_token_redirects_with_cookie(
        self, container, client
    ):
        valid_token = "valid-test-token-1234567890abc"
        container.access_policy.token = valid_token
        token = container.csrf.current_token()
        resp = client.post(
            "/login",
            data={"token": valid_token},
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        set_cookie = resp.headers.get("set-cookie", "")
        assert "draper_dashboard_token=" in set_cookie

    def test_login_cookie_defaults_secure_for_non_loopback_auth(
        self, project_data_dir, monkeypatch
    ):
        monkeypatch.delenv("DASHBOARD_SECURE_COOKIE", raising=False)
        monkeypatch.delenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", raising=False)
        valid_token = "valid-production-token-1234567890abc"
        monkeypatch.setenv("DRAPER_DASHBOARD_TOKEN", valid_token)

        from dashboard.app_container import AppContainer
        from dashboard.app_factory import build_app

        container = AppContainer(data_dir=str(project_data_dir), host="0.0.0.0")
        app = build_app(container, host="0.0.0.0")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/login",
            data={"token": valid_token},
            headers={"x-csrf-token": container.csrf.current_token()},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        set_cookie = resp.headers.get("set-cookie", "")
        assert "draper_dashboard_token=" in set_cookie
        # Over plain HTTP (TestClient), Secure flag must NOT be set —
        # browsers silently reject Secure cookies over HTTP.
        # The flag is now driven by request.url.scheme, not the bind host.
        assert "Secure" not in set_cookie

    def test_post_login_with_invalid_token_returns_401(self, container, client):
        container.access_policy.token = "valid-test-token-1234567890abc"
        token = container.csrf.current_token()
        resp = client.post(
            "/login",
            data={"token": "wrong-token"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 401

    def test_get_logout_redirects_to_login_with_clear_cookie(self, container, client):
        token = container.csrf.current_token()
        resp = client.get(
            "/logout",
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
        set_cookie = resp.headers.get("set-cookie", "")
        assert "draper_dashboard_token=" in set_cookie

    def test_get_past_redirects_to_pipeline(self, container, client):
        token = container.csrf.current_token()
        resp = client.get(
            "/past",
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/?tab=pipeline"

    def test_get_evaluate_redirects_to_pipeline(self, container, client):
        token = container.csrf.current_token()
        resp = client.get(
            "/evaluate",
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/?tab=pipeline"

    def test_get_nostr_redirects_to_pipeline(self, container, client):
        token = container.csrf.current_token()
        resp = client.get(
            "/nostr",
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/?tab=pipeline"

    def test_get_generate_returns_405_error_envelope(self, container, client):
        token = container.csrf.current_token()
        resp = client.get(
            "/generate",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 405
        body = resp.json()
        assert body["success"] is False
