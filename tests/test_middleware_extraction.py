"""Plan 03-01 Task 2: Middleware extraction regression contracts.

Each test class builds a minimal FastAPI app wiring one extracted middleware
class against a stub container (no ``build_app`` dependency — Task 2 must be
independently verifiable). Behaviors must match the inline closures in
``unified_dashboard.py:main()`` byte-for-byte.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from services.access_control import DashboardAccessPolicy


def _build_security_app() -> FastAPI:
    from dashboard.middleware.security_headers import SecurityHeaders

    app = FastAPI()
    app.middleware("http")(SecurityHeaders())

    @app.get("/anything")
    async def anything():
        return {"ok": True}

    return app


def _build_csrf_app(csrf: Any) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def csrf_dispatch(request: Request, call_next):
        request.state.auth_transport = request.headers.get("x-auth-transport", "cookie")
        result = await csrf.validate(request)
        if result is not None:
            return result
        return await call_next(request)

    @app.get("/api/csrf-token")
    async def get_token():
        return {"success": True, "csrf_token": csrf.current_token()}

    @app.post("/api/anything")
    async def post_anything():
        return {"success": True}

    @app.post("/login")
    async def login():
        return {"success": True}

    return app


def _build_rate_limit_app(rate_limiter: Any) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def rate_dispatch(request: Request, call_next):
        return await rate_limiter(request, call_next)

    @app.post("/api/generate")
    async def generate():
        return {"success": True}

    return app


def _build_auth_app(access_policy: DashboardAccessPolicy, container: Any) -> FastAPI:
    from dashboard.middleware.auth import AuthMiddleware

    app = FastAPI()
    app.state.container = container
    app.middleware("http")(AuthMiddleware(access_policy=access_policy, container=container))

    @app.get("/api/anything")
    async def api_anything():
        return {"success": True}

    @app.get("/page")
    async def page():
        return {"success": True}

    return app


class TestSecurityHeaders:
    def test_sets_nosniff_header(self):
        client = TestClient(_build_security_app())
        resp = client.get("/anything")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_sets_frame_options_deny(self):
        client = TestClient(_build_security_app())
        resp = client.get("/anything")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_sets_referrer_policy(self):
        client = TestClient(_build_security_app())
        resp = client.get("/anything")
        assert resp.headers["Referrer-Policy"] == "same-origin"

    def test_sets_csp_header(self):
        client = TestClient(_build_security_app())
        resp = client.get("/anything")
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_sets_hsts_when_forwarded_proto_is_https(self):
        client = TestClient(_build_security_app())
        resp = client.get("/anything", headers={"x-forwarded-proto": "https"})
        assert (
            resp.headers["Strict-Transport-Security"]
            == "max-age=31536000; includeSubDomains"
        )


class TestCSRFService:
    def test_get_bypasses_csrf(self):
        from dashboard.middleware.csrf import CSRFService

        csrf = CSRFService()
        client = TestClient(_build_csrf_app(csrf))
        assert client.get("/api/csrf-token").status_code == 200

    def test_post_without_token_returns_403(self):
        from dashboard.middleware.csrf import CSRFService

        csrf = CSRFService()
        client = TestClient(_build_csrf_app(csrf))
        resp = client.post("/api/anything")
        assert resp.status_code == 403
        assert resp.json() == {"success": False, "error": "CSRF token missing or invalid"}

    def test_post_with_matching_token_succeeds(self):
        from dashboard.middleware.csrf import CSRFService

        csrf = CSRFService()
        client = TestClient(_build_csrf_app(csrf))
        resp = client.post(
            "/api/anything", headers={"x-csrf-token": csrf.current_token()}
        )
        assert resp.status_code == 200

    def test_login_path_bypasses_csrf(self):
        from dashboard.middleware.csrf import CSRFService

        csrf = CSRFService()
        client = TestClient(_build_csrf_app(csrf))
        resp = client.post("/login")
        assert resp.status_code == 200

    def test_header_auth_transport_bypasses_csrf(self):
        from dashboard.middleware.csrf import CSRFService

        csrf = CSRFService()
        client = TestClient(_build_csrf_app(csrf))
        resp = client.post(
            "/api/anything",
            headers={"x-auth-transport": "header"},
        )
        assert resp.status_code == 200

    def test_rotate_token_changes_value(self):
        from dashboard.middleware.csrf import CSRFService

        csrf = CSRFService()
        old = csrf.current_token()
        new = csrf.rotate_token()
        assert new != old
        assert csrf.current_token() == new


class TestRateLimiter:
    def test_first_request_succeeds(self):
        from dashboard.middleware.rate_limit import RateLimiter

        limiter = RateLimiter()
        client = TestClient(_build_rate_limit_app(limiter))
        resp = client.post("/api/generate")
        assert resp.status_code == 200

    def test_eleventh_request_returns_429(self):
        from dashboard.middleware.rate_limit import RateLimiter

        limiter = RateLimiter()
        client = TestClient(_build_rate_limit_app(limiter))
        for _ in range(10):
            assert client.post("/api/generate").status_code == 200
        resp = client.post("/api/generate")
        assert resp.status_code == 429
        assert resp.json() == {"success": False, "error": "Rate limit exceeded"}

    def test_unlimited_path_passes(self):
        from dashboard.middleware.rate_limit import RateLimiter

        limiter = RateLimiter()

        app = FastAPI()

        @app.middleware("http")
        async def rate_dispatch(request: Request, call_next):
            return await limiter(request, call_next)

        @app.post("/api/anything-not-throttled")
        async def not_throttled():
            return {"success": True}

        client = TestClient(app)
        for _ in range(20):
            assert client.post("/api/anything-not-throttled").status_code == 200


class TestAuthMiddleware:
    def test_unauthenticated_local_affixes_dev_principal(self, monkeypatch):
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
        monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
        policy = DashboardAccessPolicy(host="127.0.0.1")
        container = type("C", (), {"store": None})()
        client = TestClient(_build_auth_app(policy, container))
        assert client.get("/api/anything").status_code == 200

    def test_unauthenticated_api_returns_401(self, monkeypatch):
        monkeypatch.delenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", raising=False)
        monkeypatch.setenv("DRAPER_DASHBOARD_TOKEN", "fixture-dashboard-token-1234")
        policy = DashboardAccessPolicy(host="127.0.0.1")
        container = type("C", (), {"store": None})()
        client = TestClient(_build_auth_app(policy, container))
        resp = client.get("/api/anything")
        assert resp.status_code == 401
        assert resp.json() == {"success": False, "error": "Unauthorized"}

    def test_unauthenticated_page_redirects_to_login(self, monkeypatch):
        monkeypatch.delenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", raising=False)
        monkeypatch.setenv("DRAPER_DASHBOARD_TOKEN", "fixture-dashboard-token-1234")
        policy = DashboardAccessPolicy(host="127.0.0.1")
        container = type("C", (), {"store": None})()
        client = TestClient(_build_auth_app(policy, container))
        resp = client.get("/page", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_valid_token_authenticates(self, monkeypatch):
        monkeypatch.delenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", raising=False)
        monkeypatch.setenv("DRAPER_DASHBOARD_TOKEN", "fixture-dashboard-token-1234")
        policy = DashboardAccessPolicy(host="127.0.0.1")
        container = type("C", (), {"store": None})()
        client = TestClient(_build_auth_app(policy, container))
        resp = client.get(
            "/api/anything",
            headers={"Authorization": "Bearer fixture-dashboard-token-1234"},
        )
        assert resp.status_code == 200


class TestInferProjectAuthzImportable:
    def test_infer_project_authz_is_module_level_callable(self):
        from dashboard.middleware.auth import infer_project_authz

        assert callable(infer_project_authz)

    def test_role_by_method_dict_present(self):
        from dashboard.middleware.auth import role_by_method

        assert role_by_method["POST"] == "editor"
        assert role_by_method["DELETE"] == "owner"
        assert role_by_method["GET"] == "viewer"
