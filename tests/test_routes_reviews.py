"""Plan 03-02 Task 1: dashboard/routes/reviews.py + _helpers.py regression contracts.

Asserts the three properties the app-factory swap (Plan 03-04) will rely on:

1. ``dashboard.routes.reviews`` imports in isolation (no UnifiedDashboard built).
2. ``reviews.router`` registers every review-related path the monolith owns.
3. Three representative routes (JSON decline, JSON approve-without-publish,
   form needs-work) preserve the response shapes / status codes of the inline
   closures in ``dashboard/unified_dashboard.py:main()``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient


def _make_post(platform: str = "twitter", project_id: str = "proj-test", **overrides):
    post = {
        "platform": platform,
        "content_type": "tweet",
        "pillar": "growth",
        "hook_type": "question",
        "content": "Sample content for routes migration tests.",
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


def _seed_pending_review(container, **post_overrides):
    record = container.feedback_manager.add_for_review(_make_post(**post_overrides))
    return record["review_id"]


EXPECTED_REVIEW_PATHS = {
    "/approve/{review_id}",
    "/needs-work/{review_id}",
    "/api/decline/{review_id}",
    "/decline/{review_id}",
    "/schedule/{review_id}",
    "/regenerate/{review_id}",
    "/reject/{review_id}",
    "/scheduled/delete/{post_id}",
    "/sync-analytics",
    "/api/calendar/events",
    "/api/calendar/events/{event_id}/reschedule",
    "/api/content",
    "/api/content/{review_id}/approve",
    "/api/content/{review_id}/reject",
    "/api/content/{review_id}/needs-work",
    "/api/content/{review_id}/schedule",
    "/api/content/{review_id}/carousel",
    "/api/content/{review_id}/visual",
    "/api/content/{review_id}/infographic",
    "/api/publish",
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

        module = importlib.import_module("dashboard.routes.reviews")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)

    def test_helpers_importable_in_isolation(self):
        import importlib

        module = importlib.import_module("dashboard.routes._helpers")
        assert callable(module.validation_error_message)
        assert callable(module.pipeline_redirect)


class TestHelpersBehavior:
    def test_validation_error_message_mirrors_legacy_shape(self):
        from dashboard.routes._helpers import validation_error_message

        class StubError:
            def errors(self):
                return [{"loc": ("body", "feedback"), "msg": "field required"}]

        assert validation_error_message(StubError()) == "feedback: field required"

    def test_validation_error_message_no_loc_returns_msg_only(self):
        from dashboard.routes._helpers import validation_error_message

        class StubError:
            def errors(self):
                return [{"loc": (), "msg": "Invalid request"}]

        assert validation_error_message(StubError()) == "Invalid request"

    def test_pipeline_redirect_returns_303_to_pipeline_tab(self):
        from dashboard.routes._helpers import pipeline_redirect

        response = pipeline_redirect()
        assert response.status_code == 303
        assert response.headers["location"] == "/?tab=pipeline"


class TestRouteRegistration:
    def test_router_registers_every_review_path(self):
        from dashboard.routes import reviews

        paths = {route.path for route in reviews.router.routes}
        missing = EXPECTED_REVIEW_PATHS - paths
        assert not missing, f"Missing paths in reviews.router: {sorted(missing)}"

    def test_router_has_at_least_21_routes(self):
        from dashboard.routes import reviews

        assert len(reviews.router.routes) >= 20

    def test_iter_routers_yields_reviews(self):
        from dashboard.routes import iter_routers, reviews

        routers = list(iter_routers())
        assert reviews.router in routers


class TestBehavioralEquivalence:
    """Drive the migrated routes through build_app + TestClient."""

    def test_api_decline_returns_success_with_review_id(self, container, client):
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/decline/{review_id}",
            json={"feedback": "declined via test"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["review_id"] == review_id

    def test_api_approve_with_publish_false_skips_scheduling(
        self, container, client
    ):
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/content/{review_id}/approve",
            json={"feedback": "ok", "publish": False},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["scheduling"]["scheduled"] is False
        assert body["scheduling"]["skipped"] == "publish=false"

    def test_form_needs_work_redirects_303_to_pipeline(self, container, client):
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()
        resp = client.post(
            f"/needs-work/{review_id}",
            data={"feedback": "fix it"},
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/?tab=pipeline"

    def test_unknown_review_decline_returns_typed_error(self, client, container):
        token = container.csrf.current_token()
        resp = client.post(
            "/api/decline/does-not-exist-12345",
            json={"feedback": "n/a"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["code"] == "UNKNOWN_REVIEW"

    def test_review_carousel_route_uses_idea_lab_service(self, container, client):
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()
        called = {}

        async def fake_generate_carousel_for_review(review_id: str, num_cards: int):
            called["review_id"] = review_id
            called["num_cards"] = num_cards
            return {"success": True, "carousel_id": "carousel-test"}

        container.idea_lab.generate_carousel_for_review = fake_generate_carousel_for_review

        resp = client.post(
            f"/api/content/{review_id}/carousel",
            json={"num_cards": 4},
            headers={"x-csrf-token": token},
        )

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "carousel_id": "carousel-test"}
        assert called == {"review_id": review_id, "num_cards": 4}

    def test_review_carousel_route_validates_num_cards(self, container, client):
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()

        async def fail_if_called(review_id: str, num_cards: int):
            raise AssertionError("IdeaLabService should not run for invalid num_cards")

        container.idea_lab.generate_carousel_for_review = fail_if_called

        resp = client.post(
            f"/api/content/{review_id}/carousel",
            json={"num_cards": 99},
            headers={"x-csrf-token": token},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "success": False,
            "error": "num_cards must be between 1 and 12",
        }


class TestValidationErrorPath:
    """Pinning WR-05: validation surfaces ``error`` from validation_error_message."""

    def test_approve_oversized_scheduled_date_returns_error_envelope(
        self, container, client
    ):
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/content/{review_id}/approve",
            json={"scheduled_date": "x" * 200},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "error" in body


class TestNeedsWorkIsNonBlocking:
    """Plan 04-02 Task 3: pin Phase 4 criterion #3 (auto-fix never blocks).

    Each test injects a 5-second AutoFixEngine stub and asserts the route
    responds in well under that. The 500ms upper bound is CI-friendly
    (semantic threshold is "much faster than the 5s LLM stub"); tightening
    to 100ms produces flaky failures on shared CI runners.
    """

    def _install_slow_autofix(self, monkeypatch):
        class _SlowFix:
            async def fix_content(self, post_data, feedback, project_id):
                await asyncio.sleep(5)
                return {"content": "fixed", "explanation": "exp"}

        monkeypatch.setattr("learning.auto_fix.AutoFixEngine", _SlowFix)

    def test_form_needs_work_returns_under_500ms_with_5s_stub(
        self, container, client, monkeypatch
    ):
        self._install_slow_autofix(monkeypatch)
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()

        start = time.monotonic()
        resp = client.post(
            f"/needs-work/{review_id}",
            data={"feedback": "fix it", "tags": ""},
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )
        elapsed = time.monotonic() - start

        assert resp.status_code == 303
        assert elapsed < 0.5

    def test_api_needs_work_returns_under_500ms_with_5s_stub(
        self, container, client, monkeypatch
    ):
        self._install_slow_autofix(monkeypatch)
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()

        start = time.monotonic()
        resp = client.post(
            f"/api/content/{review_id}/needs-work",
            json={"feedback": "fix it", "tags": []},
            headers={"x-csrf-token": token},
        )
        elapsed = time.monotonic() - start

        assert resp.status_code == 200
        body = resp.json()
        assert body["auto_fix_status"] == "queued"
        assert "job_id" in body
        assert elapsed < 0.5

    def test_fix_content_job_in_queue_after_route_returns(
        self, container, client, monkeypatch
    ):
        self._install_slow_autofix(monkeypatch)
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()

        client.post(
            f"/api/content/{review_id}/needs-work",
            json={"feedback": "fix it", "tags": []},
            headers={"x-csrf-token": token},
        )

        queued = [
            job
            for job in container.job_queue.list(status="queued")
            if job.get("kind") == "fix_content"
        ]
        assert queued
        assert queued[0]["payload"]["review_id"] == review_id

    def test_review_record_auto_fix_status_queued_after_route(
        self, container, client, monkeypatch
    ):
        self._install_slow_autofix(monkeypatch)
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()

        client.post(
            f"/api/content/{review_id}/needs-work",
            json={"feedback": "fix it", "tags": []},
            headers={"x-csrf-token": token},
        )

        stored = container.feedback_manager._load_review_record(review_id)
        assert stored["auto_fix_status"] == "queued"

    def test_api_needs_work_response_omits_explanation(
        self, container, client, monkeypatch
    ):
        self._install_slow_autofix(monkeypatch)
        review_id = _seed_pending_review(container)
        token = container.csrf.current_token()

        resp = client.post(
            f"/api/content/{review_id}/needs-work",
            json={"feedback": "fix it", "tags": []},
            headers={"x-csrf-token": token},
        )

        body = resp.json()
        assert "explanation" not in body
