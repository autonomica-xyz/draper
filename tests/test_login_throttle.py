"""Failed-login throttling and auth audit events for ``POST /login``.

Covers the login brute-force finding from the 2026-08 security review:

* ``LoginRateLimiter`` locks a client IP out after a failure budget,
  expires old failures with the window, resets on success, and keeps
  per-IP buckets separate.
* ``client_ip`` uses the socket peer address and never trusts
  ``X-Forwarded-For``.
* The wired ``/login`` route returns 429 once locked (even for a valid
  token), resets the budget after a successful login, and records
  ``auth`` audit events without ever persisting token material.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from dashboard.middleware.rate_limit import LoginRateLimiter, client_ip


def _stub_request(ip: str = "1.2.3.4") -> Any:
    return SimpleNamespace(client=SimpleNamespace(host=ip))


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


VALID_TOKEN = "valid-test-token-1234567890abc"


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

    container.login_limiter = LoginRateLimiter(max_failures=3, window_seconds=300.0)
    return build_app(container)


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


class TestLoginRateLimiterUnit:
    def test_locks_after_failure_budget(self):
        clock = _FakeClock()
        limiter = LoginRateLimiter(max_failures=2, window_seconds=60, clock=clock)
        request = _stub_request()

        assert limiter.is_locked(request) is False
        limiter.record_failure(request)
        assert limiter.is_locked(request) is False
        limiter.record_failure(request)
        assert limiter.is_locked(request) is True

    def test_failures_expire_with_window(self):
        clock = _FakeClock()
        limiter = LoginRateLimiter(max_failures=2, window_seconds=60, clock=clock)
        request = _stub_request()

        limiter.record_failure(request)
        limiter.record_failure(request)
        assert limiter.is_locked(request) is True

        clock.now += 61.0
        assert limiter.is_locked(request) is False

    def test_success_resets_bucket(self):
        clock = _FakeClock()
        limiter = LoginRateLimiter(max_failures=2, window_seconds=60, clock=clock)
        request = _stub_request()

        limiter.record_failure(request)
        limiter.record_failure(request)
        limiter.reset(request)
        assert limiter.is_locked(request) is False

    def test_buckets_are_per_ip(self):
        clock = _FakeClock()
        limiter = LoginRateLimiter(max_failures=1, window_seconds=60, clock=clock)
        attacker = _stub_request("9.9.9.9")
        honest = _stub_request("8.8.8.8")

        limiter.record_failure(attacker)
        assert limiter.is_locked(attacker) is True
        assert limiter.is_locked(honest) is False

    def test_client_ip_ignores_forwarded_for(self):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/login",
                "headers": [(b"x-forwarded-for", b"6.6.6.6, 7.7.7.7")],
                "query_string": b"",
                "client": ("1.2.3.4", 51234),
            }
        )
        assert client_ip(request) == "1.2.3.4"

    def test_client_ip_handles_missing_client(self):
        assert client_ip(SimpleNamespace(client=None)) == "unknown"


class TestLoginRouteThrottle:
    def test_failed_logins_lock_out_then_reject_valid_token(self, container, client):
        container.access_policy.token = VALID_TOKEN

        for _ in range(3):
            resp = client.post("/login", data={"token": "wrong-token"})
            assert resp.status_code == 401

        locked = client.post("/login", data={"token": "wrong-token"})
        assert locked.status_code == 429
        assert locked.json() == {
            "success": False,
            "error": "Too many failed login attempts. Try again later.",
        }

        # Locked out even with the correct token.
        locked_valid = client.post(
            "/login", data={"token": VALID_TOKEN}, follow_redirects=False
        )
        assert locked_valid.status_code == 429

    def test_successful_login_resets_failure_budget(self, container, client):
        container.access_policy.token = VALID_TOKEN

        for _ in range(2):
            assert client.post("/login", data={"token": "wrong-token"}).status_code == 401

        ok = client.post("/login", data={"token": VALID_TOKEN}, follow_redirects=False)
        assert ok.status_code == 303

        # Without the reset this third post-success failure would already be
        # a 429 (bucket would hold 5 cumulative failures).
        assert client.post("/login", data={"token": "wrong-token"}).status_code == 401
        assert client.post("/login", data={"token": "wrong-token"}).status_code == 401
        assert client.post("/login", data={"token": "wrong-token"}).status_code == 401
        assert client.post("/login", data={"token": "wrong-token"}).status_code == 429

class TestAuthAuditEvents:
    def test_failed_login_records_event_without_token_material(self, container, client):
        container.access_policy.token = VALID_TOKEN
        resp = client.post("/login", data={"token": "super-secret-guess-value"})
        assert resp.status_code == 401

        events = container.store.list_events(category="auth")
        assert len(events) == 1
        event = events[0]
        assert event["action"] == "login_failed"
        assert event["payload"]["ip"] == "testclient"
        assert "super-secret-guess-value" not in str(event["payload"])

    def test_successful_login_records_event(self, container, client):
        container.access_policy.token = VALID_TOKEN
        resp = client.post("/login", data={"token": VALID_TOKEN}, follow_redirects=False)
        assert resp.status_code == 303

        events = container.store.list_events(category="auth")
        assert [event["action"] for event in events] == ["login_succeeded"]

    def test_locked_attempt_records_throttled_event(self, container, client):
        container.access_policy.token = VALID_TOKEN
        for _ in range(4):
            client.post("/login", data={"token": "wrong-token"})

        events = container.store.list_events(category="auth")
        assert events[0]["action"] == "login_failed"
        assert events[0]["payload"].get("throttled") is True

    def test_events_api_accepts_auth_category(self, container, client):
        container.access_policy.token = VALID_TOKEN
        client.post("/login", data={"token": "wrong-token"})

        resp = client.get(
            "/api/events",
            params={"category": "auth"},
            headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["count"] >= 1
