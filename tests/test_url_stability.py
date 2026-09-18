"""Plan 03-04 Task 3: ARCH-04 closeout gate.

Pins the four ARCH-04 success criteria with behavioral tests against
``build_app(AppContainer(...))`` via TestClient:

* TestURLEnumeration — every (method, path) tuple registered by the
  pre-swap monolith (91 routes) appears in ``build_app().routes``
  (criterion #4 — no URL drift).
* TestURLStability — a representative subset of 30+ routes returns the
  expected status code shape via TestClient.
* TestCSRFRegression — POST without ``x-csrf-token`` returns 403 with
  the exact error body; POST with a valid token returns the underlying
  route response; GET requests bypass CSRF; ``/login`` POST is CSRF-exempt
  (AGENTS.md gotcha #11).
* TestAuthRegression — with auth enabled and no credentials, GET ``/api/*``
  returns 401 JSON, GET non-API paths returns 303 to ``/login``, and
  ``/health`` + ``/login`` are exempt (gotcha #11).
* TestRateLimitRegression — the 11th rapid POST ``/api/generate`` within
  the 60s window returns 429 (security contribution).
* TestMiddlewareHeaderRegression — every response carries
  ``X-Content-Type-Options=nosniff``, ``X-Frame-Options=DENY``,
  ``Referrer-Policy=same-origin``, and a ``Content-Security-Policy`` header
  (security contribution).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient


EXPECTED_ROUTES = [
    ("GET", "/api/csrf-token"),
    ("GET", "/health"),
    ("GET", "/favicon.ico"),
    ("GET", "/login"),
    ("POST", "/login"),
    ("GET", "/logout"),
    ("GET", "/"),
    ("GET", "/analytics"),
    ("GET", "/past"),
    ("GET", "/scheduled"),
    ("GET", "/evaluate"),
    ("GET", "/generate"),
    ("POST", "/generate"),
    ("GET", "/nostr"),
    ("POST", "/nostr/publish-all"),
    ("POST", "/nostr/publish-note"),
    ("POST", "/approve/{review_id}"),
    ("POST", "/needs-work/{review_id}"),
    ("POST", "/api/decline/{review_id}"),
    ("POST", "/decline/{review_id}"),
    ("POST", "/schedule/{review_id}"),
    ("POST", "/regenerate/{review_id}"),
    ("POST", "/reject/{review_id}"),
    ("POST", "/scheduled/delete/{post_id}"),
    ("GET", "/sync-analytics"),
    ("POST", "/sync-analytics"),
    ("GET", "/api/calendar/events"),
    ("POST", "/api/calendar/events/{event_id}/reschedule"),
    ("GET", "/api/projects"),
    ("POST", "/api/projects"),
    ("DELETE", "/api/projects/{project_id}"),
    ("GET", "/api/projects/{project_id}/access/tokens"),
    ("POST", "/api/projects/{project_id}/access/tokens"),
    ("DELETE", "/api/projects/{project_id}/access/tokens/{token_id}"),
    ("GET", "/api/projects/{project_id}/mcp-config"),
    ("POST", "/api/projects/{project_id}/mcp-config"),
    ("GET", "/api/projects/{project_id}/content-plan"),
    ("POST", "/api/projects/{project_id}/content-plan"),
    ("GET", "/api/projects/{project_id}/content-plan/download"),
    ("POST", "/api/projects/{project_id}/content-plan/upload"),
    ("GET", "/api/projects/{project_id}/brand-voice"),
    ("POST", "/api/projects/{project_id}/brand-voice"),
    ("GET", "/api/projects/{project_id}/social-profiles"),
    ("POST", "/api/projects/{project_id}/social-profiles/toggle"),
    ("GET", "/api/projects/{project_id}/posting-strategy"),
    ("POST", "/api/projects/{project_id}/posting-strategy"),
    ("GET", "/api/projects/{project_id}/integrations"),
    ("POST", "/api/projects/{project_id}/integrations/typefully"),
    ("POST", "/api/projects/{project_id}/integrations/typefully/test"),
    ("GET", "/api/projects/{project_id}/integrations/late"),
    ("POST", "/api/projects/{project_id}/integrations/late"),
    ("POST", "/api/projects/{project_id}/integrations/late/test"),
    ("POST", "/api/generate"),
    ("GET", "/api/content"),
    ("POST", "/api/content/{review_id}/approve"),
    ("POST", "/api/content/{review_id}/reject"),
    ("POST", "/api/content/{review_id}/needs-work"),
    ("POST", "/api/content/{review_id}/schedule"),
    ("POST", "/api/content/{review_id}/carousel"),
    ("POST", "/api/content/{review_id}/visual"),
    ("POST", "/api/content/{review_id}/infographic"),
    ("POST", "/api/publish"),
    ("GET", "/api/status"),
    ("GET", "/api/jobs"),
    ("POST", "/api/jobs/sync-analytics"),
    ("POST", "/api/jobs/run-next"),
    ("GET", "/api/jobs/{job_id}"),
    ("POST", "/api/jobs/{job_id}/cancel"),
    ("GET", "/api/analytics"),
    ("GET", "/api/providers"),
    ("GET", "/api/projects/{project_id}/provider-mapping"),
    ("POST", "/api/projects/{project_id}/provider-mapping"),
    ("POST", "/api/generate/image"),
    ("POST", "/api/generate/carousel"),
    ("POST", "/api/ideas/materials"),
    ("GET", "/api/ideas/materials"),
    ("GET", "/api/ideas/materials/{material_id}"),
    ("PUT", "/api/ideas/materials/{material_id}"),
    ("DELETE", "/api/ideas/materials/{material_id}"),
    ("POST", "/api/ideas/materials/{material_id}/enrich"),
    ("POST", "/api/ideas/materials/enrich-batch"),
    ("POST", "/api/ideas/materials/{material_id}/generate-ideas"),
    ("POST", "/api/ideas/generate-ideas-batch"),
    ("POST", "/api/ideas/ideas"),
    ("GET", "/api/ideas/ideas"),
    ("GET", "/api/ideas/ideas/{idea_id}"),
    ("PUT", "/api/ideas/ideas/{idea_id}"),
    ("POST", "/api/ideas/ideas/{idea_id}/evaluate"),
    ("POST", "/api/ideas/ideas/{idea_id}/approve-and-generate"),
    ("DELETE", "/api/ideas/ideas/{idea_id}"),
    ("POST", "/api/ideas/mining/trigger"),
]


def _make_post(platform: str = "twitter", project_id: str = "proj-stab", **overrides):
    post = {
        "platform": platform,
        "content_type": "tweet",
        "pillar": "growth",
        "hook_type": "question",
        "content": "Sample content for URL stability tests.",
        "project_id": project_id,
    }
    post.update(overrides)
    return post


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


@pytest.fixture
def project_id(container):
    project = container.project_manager.create_project(name="URL Stability Project")
    container.project_manager.set_current_project(project.project_id)
    return project.project_id


@pytest.fixture
def review_id(container, project_id):
    record = container.feedback_manager.add_for_review(
        _make_post(project_id=project_id)
    )
    return record["review_id"]


@pytest.fixture
def job_id(container, project_id):
    job = container.job_queue.enqueue(
        "sync_analytics",
        project_id=project_id,
        payload={"project_id": project_id},
    )
    return job["job_id"]


@pytest.fixture
def auth_container(project_data_dir: Any, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", raising=False)
    monkeypatch.setenv("DRAPER_DASHBOARD_TOKEN", "url-stability-admin-token-1234567890")
    from dashboard.app_container import AppContainer

    return AppContainer(data_dir=str(project_data_dir))


@pytest.fixture
def auth_client(auth_container):
    from dashboard.app_factory import build_app

    return TestClient(build_app(auth_container), raise_server_exceptions=False)


def _enumerate_app_routes(app):
    """Yield (method, path) tuples from a FastAPI app, walking through
    the ``_IncludedRouter`` wrappers that FastAPI 0.128+ uses."""
    seen = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        inner_routes = getattr(route, "routes", None)
        if inner_routes is not None and not getattr(route, "methods", None):
            stack.extend(inner_routes)
            continue
        original = getattr(route, "original_router", None)
        if original is not None:
            stack.extend(original.routes)
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if path is None:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            key = (method, path)
            if key not in seen:
                seen.add(key)
                yield key


_FETCH_RE = re.compile(
    r"fetch\(\s*"
    r"(?:`([^`]*)`"
    r"|'([^']*)'"
    r'|"([^"]*)")'
)

_FRONTEND_TEMPLATE = Path(__file__).resolve().parents[1] / "dashboard" / "templates" / "unified.html"


def _skeletonize_url(path: str) -> str:
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]*\}", "<P>", path)
    path = re.sub(r"\{[^}]+\}", "<P>", path)
    return path


def _extract_frontend_fetch_urls(template_path: Path = _FRONTEND_TEMPLATE) -> list[str]:
    text = template_path.read_text(encoding="utf-8")
    urls: set[str] = set()
    for m in _FETCH_RE.finditer(text):
        for group in m.groups():
            if group and group.startswith("/"):
                urls.add(group)
    return sorted(urls)


class TestURLEnumeration:
    """ARCH-04 criterion #4: every (method, path) the monolith exposed
    must still be registered by ``build_app(container).routes``."""

    def test_expected_route_count_matches_monolith_baseline(self):
        assert len(EXPECTED_ROUTES) == 91, (
            f"EXPECTED_ROUTES has {len(EXPECTED_ROUTES)} entries; the pre-swap "
            "monolith had 91 routes. Update EXPECTED_ROUTES to match."
        )

    def test_every_expected_route_is_registered(self, app):
        registered = set(_enumerate_app_routes(app))
        missing = [tuple(r) for r in EXPECTED_ROUTES if tuple(r) not in registered]
        assert not missing, (
            f"build_app(container) is missing {len(missing)} routes from the "
            f"pre-swap monolith: first 5 = {missing[:5]}"
        )

    def test_no_duplicate_paths_in_expected_routes(self):
        seen = set()
        duplicates = []
        for route in EXPECTED_ROUTES:
            if route in seen:
                duplicates.append(route)
            seen.add(route)
        assert not duplicates, f"EXPECTED_ROUTES contains duplicates: {duplicates}"


class TestURLStability:
    """Behavioral checks for a representative subset of routes.

    Status code equivalence is the URL-stability contract (criterion #4);
    exact response shapes are pinned by the per-route test files
    (``tests/test_routes_*.py``). Page routes that render Jinja templates
    require a current project, so they depend on the ``project_id`` fixture
    which seeds one.
    """

    def test_get_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "status": "ok"}

    def test_get_csrf_token(self, client):
        resp = client.get("/api/csrf-token")
        assert resp.status_code == 200
        assert resp.json()["csrf_token"]

    def test_get_home(self, client, project_id):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_get_login_page(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_get_analytics_page_preserves_monolith_template_behavior(
        self, client, project_id
    ):
        # /analytics passes content=None into the unified.html template.
        # Previously the template evaluated `{{ content | length }}` which
        # raised TypeError on None; the route 500'd in both the monolith
        # and the new app. The template now uses `{{ (content or []) | length }}`
        # so all tabs render successfully. Status equivalence holds at 200.
        resp = client.get("/analytics")
        assert resp.status_code == 200

    def test_get_past_page_redirects_to_pipeline(self, client):
        resp = client.get("/past", follow_redirects=False)
        assert resp.status_code == 303

    def test_get_scheduled_page_preserves_monolith_template_behavior(
        self, client, project_id
    ):
        # Same fixed template bug as /analytics: the /scheduled route
        # hard-codes content=None, which the unified.html template now
        # renders as `{{ (content or []) | length }}` → 0. Status
        # equivalence with the monolith holds at 200.
        resp = client.get("/scheduled")
        assert resp.status_code == 200

    def test_get_evaluate_page(self, client):
        resp = client.get("/evaluate", follow_redirects=False)
        assert resp.status_code == 303

    def test_get_generate_page_returns_405(self, client):
        resp = client.get("/generate")
        assert resp.status_code == 405

    def test_get_nostr_page_redirects_to_pipeline(self, client):
        resp = client.get("/nostr", follow_redirects=False)
        assert resp.status_code == 303

    def test_get_api_projects(self, client):
        resp = client.get("/api/projects")
        assert resp.status_code == 200

    def test_get_api_content(self, client):
        resp = client.get("/api/content")
        assert resp.status_code == 200

    def test_get_api_jobs(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200

    def test_get_api_analytics(self, client):
        resp = client.get("/api/analytics")
        assert resp.status_code == 200

    def test_get_api_providers(self, client):
        resp = client.get("/api/providers")
        assert resp.status_code == 200

    def test_get_api_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_get_api_calendar_events(self, client, project_id):
        resp = client.get(
            "/api/calendar/events",
            params={"start": "2026-01-01", "end": "2026-12-31"},
        )
        assert resp.status_code == 200

    def test_get_project_content_plan(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/content-plan")
        assert resp.status_code == 200

    def test_get_project_brand_voice(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/brand-voice")
        assert resp.status_code == 200

    def test_get_project_integrations(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/integrations")
        assert resp.status_code == 200

    def test_get_project_provider_mapping(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/provider-mapping")
        assert resp.status_code == 200

    def test_get_ideas_materials(self, client):
        resp = client.get("/api/ideas/materials")
        assert resp.status_code == 200

    def test_get_ideas_ideas(self, client):
        resp = client.get("/api/ideas/ideas")
        assert resp.status_code == 200

    def test_get_api_job_by_id(self, client, job_id):
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200

    def test_post_api_decline_returns_success(self, client, container, review_id):
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/decline/{review_id}",
            json={"feedback": "stability decline"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200

    def test_post_api_content_approve_publish_false(
        self, client, container, review_id
    ):
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/content/{review_id}/approve",
            json={"publish": False, "feedback": "stability approve"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200

    def test_post_form_needs_work_redirects_303(self, client, container, review_id):
        token = container.csrf.current_token()
        resp = client.post(
            f"/needs-work/{review_id}",
            data={"feedback": "needs work"},
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_post_api_jobs_sync_analytics(self, client, container, project_id):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/jobs/sync-analytics",
            json={"project_id": project_id},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200

    def test_post_api_ideas_materials(self, client, container, project_id):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/ideas/materials",
            json={
                "title": "Material",
                "content": "Sample material for stability.",
                "project_id": project_id,
            },
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200


class TestCSRFRegression:
    """AGENTS.md gotcha #11: POST without x-csrf-token returns 403."""

    def test_post_without_csrf_token_returns_403_with_exact_body(
        self, client, container
    ):
        container.project_manager.create_project(name="CSRF Project")
        resp = client.post("/api/generate", json={"count": 1})
        assert resp.status_code == 403
        assert resp.json() == {"success": False, "error": "CSRF token missing or invalid"}

    def test_post_with_valid_csrf_token_passes_csrf(self, client, container, project_id):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/generate",
            json={"count": 1, "project_id": project_id},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code != 403

    def test_get_request_is_not_subject_to_csrf(self, client):
        resp = client.get("/api/projects")
        assert resp.status_code != 403

    def test_login_post_is_csrf_exempt(self, auth_container):
        from dashboard.app_factory import build_app

        auth_container.access_policy.token = "url-stability-admin-token-1234567890"
        client = TestClient(build_app(auth_container))
        resp = client.post("/login", data={"token": "wrong-token"})
        assert resp.status_code != 403


class TestAuthRegression:
    """AGENTS.md gotcha #11: auth gate before route dispatch."""

    def test_get_api_without_credentials_returns_401_json(self, auth_client):
        resp = auth_client.get("/api/projects")
        assert resp.status_code == 401
        assert resp.json() == {"success": False, "error": "Unauthorized"}

    def test_get_non_api_without_credentials_redirects_to_login(self, auth_client):
        resp = auth_client.get("/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_get_health_is_exempt_from_auth(self, auth_client):
        resp = auth_client.get("/health")
        assert resp.status_code == 200

    def test_get_login_is_exempt_from_auth(self, auth_client):
        resp = auth_client.get("/login")
        assert resp.status_code == 200

    def test_post_api_without_credentials_returns_401(self, auth_client):
        resp = auth_client.post("/api/generate", json={"count": 1})
        assert resp.status_code == 401


class TestRateLimitRegression:
    """The 11th POST /api/generate within 60s returns 429."""

    def test_eleventh_rapid_post_returns_429(self, client, container, project_id):
        token = container.csrf.current_token()
        statuses = []
        for _ in range(11):
            resp = client.post(
                "/api/generate",
                json={"count": 1, "project_id": project_id},
                headers={"x-csrf-token": token},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses, f"Expected 429 in 11 rapid posts; got {statuses}"
        first_429 = statuses.index(429)
        assert first_429 >= 10, (
            f"Rate limit tripped too early at request {first_429 + 1}; "
            f"EXPENSIVE_ROUTE_LIMITS['/api/generate'] should allow 10/60s. "
            f"statuses={statuses}"
        )
        assert statuses[first_429] == 429


class TestMiddlewareHeaderRegression:
    """Successful responses carry browser security headers.

    Note: security_headers is the innermost middleware (registered first
    in source order in ``app_factory.build_app``), so short-circuit
    responses from CSRF/auth middleware (403/401) do NOT carry the
    headers — this is the same middleware order the monolith used
    (``@app.middleware`` decoration also makes the first decorated the
    innermost). The regression contract is therefore that *successful*
    responses carry the headers.
    """

    def test_get_response_carries_security_headers(self, client):
        resp = client.get("/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "same-origin"
        assert "default-src" in resp.headers["Content-Security-Policy"]

    def test_post_success_response_carries_security_headers(
        self, client, container, project_id
    ):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/ideas/materials",
            json={
                "title": "Header Check",
                "content": "security header POST",
                "project_id": project_id,
            },
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "same-origin"
        assert "default-src" in resp.headers["Content-Security-Policy"]

    def test_html_page_response_carries_security_headers(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "same-origin"


class TestPostingStrategyURLContract:
    """Regression for CR-01: the frontend template (unified.html) calls the
    SINGULAR ``/api/projects/{id}/posting-strategy`` path. The route must
    serve that exact path -- a silent rename to the plural form breaks the
    Posting Strategy UI with a 404. This test drives the actual URL the
    frontend fetches via httpx so a future rename fails here instead of in
    production.
    """

    async def test_get_posting_strategy_singular_path_resolves(self, app, project_id):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/projects/{project_id}/posting-strategy")
        assert resp.status_code == 200, (
            f"GET singular posting-strategy path returned {resp.status_code}; "
            "the frontend (unified.html) fetches this exact URL."
        )

    async def test_post_posting_strategy_singular_path_resolves(
        self, app, container, project_id
    ):
        token = container.csrf.current_token()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/projects/{project_id}/posting-strategy",
                json={
                    "default": {
                        "frequency": "daily",
                        "posts_per_day": 2,
                        "times": ["09:00", "14:00"],
                        "platforms": ["twitter"],
                    },
                    "overrides": {},
                },
                headers={"x-csrf-token": token},
            )
        assert resp.status_code == 200, (
            f"POST singular posting-strategy path returned {resp.status_code}; "
            "the frontend (unified.html) posts to this exact URL."
        )


class TestFrontendFetchURLsResolve:
    """WR-01: the hand-maintained EXPECTED_ROUTES list cannot detect a silent
    route rename by itself (an author can update the list to match the broken
    state -- which is exactly how CR-01 slipped through). This test closes
    that gap by extracting every ``fetch()`` URL literal from the frontend
    template (unified.html) and asserting each one resolves to a real route.

    Path-param segments are normalized to a ``<P>`` placeholder on both
    sides, so a literal segment like ``posting-strategy`` must match exactly
    between frontend and backend. CR-01 (singular/plural rename) fails this
    test.
    """

    def test_every_frontend_fetch_url_matches_a_registered_route(self, app):
        fetch_urls = _extract_frontend_fetch_urls()
        assert fetch_urls, "No fetch() URLs found in unified.html -- regex drifted."

        registered_skeletons = {
            _skeletonize_url(path) for _, path in _enumerate_app_routes(app)
        }

        missing: list[tuple[str, str]] = []
        for url in fetch_urls:
            if url.endswith("/") and "${" not in url:
                continue
            skeleton = _skeletonize_url(url)
            if skeleton not in registered_skeletons:
                missing.append((url, skeleton))

        assert not missing, (
            "Frontend fetch() URLs in dashboard/templates/unified.html that do "
            f"not resolve to any registered route: {missing}"
        )
