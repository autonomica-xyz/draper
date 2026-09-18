#!/usr/bin/env python3
"""Tests for CSRF protection middleware on mutation endpoints."""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Minimal app factory replicating the CSRF middleware + endpoint pattern
# ---------------------------------------------------------------------------


def _create_csrf_app() -> tuple:
    """Return (app, csrf_token_holder) for testing."""
    import secrets

    _token_holder = {"token": secrets.token_hex(32)}

    app = FastAPI(title="CSRF Test App")

    @app.middleware("http")
    async def csrf_protect(request: Request, call_next):
        request.state.auth_transport = request.headers.get("x-auth-transport", "cookie")
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        if request.url.path in ("/login", "/logout"):
            return await call_next(request)
        if request.state.auth_transport == "header":
            return await call_next(request)
        submitted = request.headers.get("x-csrf-token", "")
        if submitted and submitted == _token_holder["token"]:
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "CSRF token missing or invalid"},
        )

    @app.get("/api/csrf-token")
    async def get_csrf_token():
        return {"success": True, "csrf_token": _token_holder["token"]}

    @app.get("/api/data")
    async def get_data():
        return {"success": True, "data": []}

    @app.post("/api/data")
    async def post_data():
        return {"success": True, "created": True}

    @app.put("/api/data/{item_id}")
    async def put_data(item_id: str):
        return {"success": True, "updated": item_id}

    @app.delete("/api/data/{item_id}")
    async def delete_data(item_id: str):
        return {"success": True, "deleted": item_id}

    @app.post("/login")
    async def login():
        return {"success": True, "token": "abc"}

    @app.post("/logout")
    async def logout():
        return {"success": True}

    return app, _token_holder


@pytest.fixture
def csrf_client():
    app, holder = _create_csrf_app()
    client = TestClient(app)
    client._token_holder = holder  # stash for test access
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCSRFTokenEndpoint:
    """GET /api/csrf-token returns a valid token."""

    def test_csrf_token_endpoint_returns_token(self, csrf_client):
        resp = csrf_client.get("/api/csrf-token")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "csrf_token" in body
        assert len(body["csrf_token"]) == 64  # 32 bytes hex

    def test_csrf_token_is_stable_across_gets(self, csrf_client):
        r1 = csrf_client.get("/api/csrf-token").json()["csrf_token"]
        r2 = csrf_client.get("/api/csrf-token").json()["csrf_token"]
        assert r1 == r2


class TestCSRFGETExempt:
    """GET requests should never require CSRF tokens."""

    def test_get_without_origin_passes(self, csrf_client):
        resp = csrf_client.get("/api/data")
        assert resp.status_code == 200

    def test_get_with_origin_passes(self, csrf_client):
        resp = csrf_client.get("/api/data", headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 200


class TestCSRFBrowserMutations:
    """Browser requests (with Origin/Referer) require a valid CSRF token."""

    def test_post_with_origin_no_token_rejected(self, csrf_client):
        resp = csrf_client.post("/api/data", headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["error"]

    def test_post_with_referer_no_token_rejected(self, csrf_client):
        resp = csrf_client.post("/api/data", headers={"referer": "http://localhost:8000/"})
        assert resp.status_code == 403

    def test_post_with_origin_and_valid_token_passes(self, csrf_client):
        token = csrf_client._token_holder["token"]
        resp = csrf_client.post(
            "/api/data",
            headers={"origin": "http://localhost:8000", "x-csrf-token": token},
        )
        assert resp.status_code == 200

    def test_post_with_referer_and_valid_token_passes(self, csrf_client):
        token = csrf_client._token_holder["token"]
        resp = csrf_client.post(
            "/api/data",
            headers={"referer": "http://localhost:8000/", "x-csrf-token": token},
        )
        assert resp.status_code == 200

    def test_post_with_wrong_token_rejected(self, csrf_client):
        resp = csrf_client.post(
            "/api/data",
            headers={"origin": "http://localhost:8000", "x-csrf-token": "badtoken"},
        )
        assert resp.status_code == 403

    def test_put_with_origin_no_token_rejected(self, csrf_client):
        resp = csrf_client.put("/api/data/1", headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 403

    def test_put_with_valid_token_passes(self, csrf_client):
        token = csrf_client._token_holder["token"]
        resp = csrf_client.put(
            "/api/data/1",
            headers={"origin": "http://localhost:8000", "x-csrf-token": token},
        )
        assert resp.status_code == 200

    def test_delete_with_origin_no_token_rejected(self, csrf_client):
        resp = csrf_client.delete("/api/data/1", headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 403

    def test_delete_with_valid_token_passes(self, csrf_client):
        token = csrf_client._token_holder["token"]
        resp = csrf_client.delete(
            "/api/data/1",
            headers={"origin": "http://localhost:8000", "x-csrf-token": token},
        )
        assert resp.status_code == 200


class TestCSRFHeaderAuthExempt:
    """Header-authenticated API calls do not need CSRF tokens."""

    def test_post_with_header_auth_transport_passes(self, csrf_client):
        resp = csrf_client.post("/api/data", headers={"x-auth-transport": "header"})
        assert resp.status_code == 200

    def test_put_with_header_auth_transport_passes(self, csrf_client):
        resp = csrf_client.put("/api/data/1", headers={"x-auth-transport": "header"})
        assert resp.status_code == 200

    def test_delete_with_header_auth_transport_passes(self, csrf_client):
        resp = csrf_client.delete("/api/data/1", headers={"x-auth-transport": "header"})
        assert resp.status_code == 200

    def test_cookie_post_without_origin_or_referer_is_rejected(self, csrf_client):
        resp = csrf_client.post("/api/data")
        assert resp.status_code == 403


class TestCSRFLoginExempt:
    """Login/logout paths are exempt from CSRF validation."""

    def test_login_with_origin_no_token_passes(self, csrf_client):
        resp = csrf_client.post("/login", headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 200

    def test_logout_with_origin_no_token_passes(self, csrf_client):
        resp = csrf_client.post("/logout", headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 200


class TestCSRFIntegration:
    """End-to-end: fetch token then use it on a mutation."""

    def test_fetch_token_then_mutation(self, csrf_client):
        # Step 1: fetch CSRF token
        token_resp = csrf_client.get("/api/csrf-token")
        token = token_resp.json()["csrf_token"]

        # Step 2: make mutation with the token
        resp = csrf_client.post(
            "/api/data",
            json={"value": "test"},
            headers={"origin": "http://localhost:8000", "x-csrf-token": token},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_fetch_token_then_cookie_mutation_without_origin_uses_token(self, csrf_client):
        token_resp = csrf_client.get("/api/csrf-token")
        token = token_resp.json()["csrf_token"]

        resp = csrf_client.post(
            "/api/data", json={"value": "test"}, headers={"x-csrf-token": token}
        )
        assert resp.status_code == 200
