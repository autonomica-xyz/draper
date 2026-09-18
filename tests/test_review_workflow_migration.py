"""Plan 02-03 migration tests.

This module tests the MIGRATION of dashboard routes, MCP tools, and CLI
commands to ``services.review_workflow_service.ReviewWorkflowService``.
It does NOT re-test the service itself (that is
``tests/test_review_workflow_service.py``); it pins the architectural
invariant that callers no longer reach into ``FeedbackManager``'s private
single-record save method directly.

The grep-gate tests (``TestMigrationGrepGate``) are static-source
assertions: they read the production source files as text and assert the
literal private save method name does not appear. This is the CI-enforced
pin for ARCH-03 success criterion #1.

The remaining tests construct a real ``UnifiedDashboard`` instance against
an isolated ``tmp_path`` data dir and exercise the migrated route shape
via ``fastapi.testclient.TestClient`` against a minimal test app that
mirrors the migrated routes in ``dashboard/unified_dashboard.py``. The
test app composes ``dashboard_instance.review_workflow`` exactly the way
the production routes do; the route bodies are identical to the
production code. Patches on ``dashboard_instance.review_workflow`` or
``dashboard_instance.publishing_service`` are how the tests assert which
service method was (or was not) called.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from data.review_models import ReviewAction, ReviewRecord
from dashboard.unified_dashboard import ApproveContentRequest, _validation_error_message
from services.review_workflow_service import (
    INVALID_TRANSITION,
    UNKNOWN_REVIEW,
    ReviewTransitionError,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_SAVE_METHOD = "_save_review_record"


def _make_post(platform="twitter", project_id="proj-test", **overrides):
    post = {
        "platform": platform,
        "content_type": "tweet",
        "pillar": "growth",
        "hook_type": "question",
        "content": "Sample content for migration tests.",
        "project_id": project_id,
    }
    post.update(overrides)
    return post


def _build_test_review_app(dashboard_instance):
    """Build a FastAPI test app whose route bodies mirror the migrated routes.

    Each route body mirrors the corresponding production route in
    ``dashboard/unified_dashboard.py`` -- the same service calls, the same
    exception translation, the same response shapes, the same Pydantic
    validation (the test app imports ``ApproveContentRequest`` and
    ``_validation_error_message`` directly from the production module), and
    the same redirect semantics for the form-decline route. The test app
    exists only so TestClient can exercise them; production code is the
    source of truth and the grep gate (TestMigrationGrepGate) verifies it
    directly.
    """
    app = FastAPI(title="Test Review Migration App")
    dashboard = dashboard_instance

    @app.post("/api/decline/{review_id}")
    async def decline_content_api(review_id: str, request: Request):
        try:
            body = await request.json()
            feedback = body.get("feedback", "")
            explicit_tags = body.get("tags", "")
        except Exception:
            feedback = ""
            explicit_tags = ""

        try:
            dashboard.review_workflow.transition(
                review_id,
                ReviewAction.DECLINE,
                feedback=feedback,
                explicit_tags=explicit_tags,
            )
        except ReviewTransitionError as e:
            return {"success": False, "error": e.message, "code": e.code}

        return {"success": True, "review_id": review_id}

    @app.post("/decline/{review_id}")
    async def decline_content(review_id: str, request: Request, feedback: str = Form("")):
        class FakeRequest:
            async def json(self):
                return {"feedback": feedback}

        result = await decline_content_api(review_id, FakeRequest())
        if not result.get("success"):
            print(f"Warning: decline failed: {result.get('code')}: {result.get('error')}")
        return RedirectResponse(url="/?tab=pipeline", status_code=303)

    @app.post("/api/content/{review_id}/approve")
    async def api_approve_content(review_id: str, request: Request):
        try:
            body = ApproveContentRequest.model_validate(await request.json())
        except ValidationError as e:
            return {"success": False, "error": _validation_error_message(e)}
        except Exception:
            body = ApproveContentRequest()

        try:
            record = dashboard.review_workflow.transition(
                review_id,
                ReviewAction.APPROVE,
                feedback=body.feedback,
                explicit_tags=body.tags,
            )
        except ReviewTransitionError as e:
            return {"success": False, "error": e.message, "code": e.code}

        if not body.publish:
            return {
                "success": True,
                "review_id": review_id,
                "status": record.status.value,
                "scheduling": {"scheduled": False, "skipped": "publish=false"},
            }

        try:
            scheduled = dashboard.review_workflow.transition(
                review_id,
                ReviewAction.SCHEDULE,
                feedback=body.feedback or "Approved and scheduled via API",
                scheduled_date=body.scheduled_date,
            )
        except ReviewTransitionError as e:
            return {
                "success": True,
                "review_id": review_id,
                "status": record.status.value,
                "scheduling": {"scheduled": False, "error": e.message, "code": e.code},
            }

        return {
            "success": True,
            "review_id": review_id,
            "status": scheduled.status.value,
            "scheduling": {
                "scheduled": True,
                "provider": scheduled.raw.get("published_via"),
                "draft_url": scheduled.raw.get("draft_url"),
                "draft_id": scheduled.raw.get("draft_id"),
            },
        }

    @app.post("/approve/{review_id}")
    async def approve_content(
        review_id: str,
        request: Request,
        feedback: str = Form(""),
        channel: str = Form("twitter"),
        scheduled_date: str = Form(""),
        tags: str = Form(""),
        publish: str = Form("true"),
    ):
        try:
            dashboard.review_workflow.transition(
                review_id,
                ReviewAction.APPROVE,
                feedback=feedback,
                explicit_tags=tags,
            )
            if publish.lower() != "false":
                dashboard.review_workflow.transition(
                    review_id,
                    ReviewAction.SCHEDULE,
                    feedback=feedback or "Approved and scheduled",
                    scheduled_date=scheduled_date or None,
                    platform=channel,
                )
        except ReviewTransitionError as e:
            print(f"Warning: Approval failed: {e.code}: {e.message}")

        return RedirectResponse(url="/?tab=pipeline", status_code=303)

    return app


def _seed_pending_review(dashboard, **post_overrides):
    """Seed a pending_review record and return its review_id."""
    record = dashboard.feedback_manager.add_for_review(_make_post(**post_overrides))
    return record["review_id"]


@pytest.fixture
def dashboard(tmp_path):
    """Construct a real UnifiedDashboard against an isolated tmp_path."""
    from dashboard.unified_dashboard import UnifiedDashboard

    return UnifiedDashboard(data_dir=str(tmp_path))


@pytest.fixture
def review_client(dashboard):
    """TestClient wired to a test app mirroring the migrated routes."""
    app = _build_test_review_app(dashboard)
    return TestClient(app, raise_server_exceptions=False)


class TestMigrationGrepGate:
    """Static-source assertions pinning ARCH-03 success criterion #1.

    These tests read the production source files as text and assert the
    private single-record save method name does not appear. If a future
    commit reintroduces the direct call, the grep gate fails the build.
    """

    def test_no_dashboard_route_calls_private_persistence_directly(self):
        """dashboard/unified_dashboard.py must not call the private save method.

        ARCH-03 success criterion #1: dashboard routes flow through
        ReviewWorkflowService.transition() exclusively. The grep gate is
        the CI-enforced pin that converts the architectural rule from a
        code-review hope into a structural invariant.
        """
        source = (REPO_ROOT / "dashboard" / "unified_dashboard.py").read_text(
            encoding="utf-8"
        )
        assert PRIVATE_SAVE_METHOD not in source, (
            f"dashboard/unified_dashboard.py calls {PRIVATE_SAVE_METHOD!r} directly -- "
            "ARCH-03 success criterion #1 violated. Routes must go through "
            "ReviewWorkflowService.transition()."
        )

    def test_no_mcp_tool_calls_private_persistence_directly(self):
        """mcp_server/server.py must not call the private save method."""
        source = (REPO_ROOT / "mcp_server" / "server.py").read_text(encoding="utf-8")
        assert PRIVATE_SAVE_METHOD not in source, (
            f"mcp_server/server.py calls {PRIVATE_SAVE_METHOD!r} directly -- "
            "MCP tools must go through ReviewWorkflowService.transition()."
        )

    def test_no_cli_calls_private_persistence_directly(self):
        """cli.py must not call the private save method."""
        source = (REPO_ROOT / "cli.py").read_text(encoding="utf-8")
        assert PRIVATE_SAVE_METHOD not in source, (
            f"cli.py calls {PRIVATE_SAVE_METHOD!r} directly -- "
            "CLI commands must go through ReviewWorkflowService.transition()."
        )

    def test_review_workflow_service_is_only_production_caller(self):
        """Production callers of the private save method are tightly scoped.

        Only ``services/review_workflow_service.py`` (the canonical v2 writer),
        ``feedback/manager.py`` (the host module that defines the method), and
        ``services/content_workflow.py`` (the v1 JobRunner backer -- the plan
        explicitly preserves it for JobRunner compatibility) may reference
        the private save method name. Anywhere else in the production tree
        (excluding tests, .venv, .planning) is a violation of ARCH-03
        success criterion #1.
        """
        exclude_dirs = {
            ".venv",
            ".git",
            "__pycache__",
            ".planning",
            "tests",
            "node_modules",
            ".mypy_cache",
            ".ruff_cache",
            ".eggs",
            "build",
            "dist",
        }
        allow_files = {
            "services/review_workflow_service.py",
            "feedback/manager.py",
            "services/content_workflow.py",
        }
        violators = []
        for absolute_path in REPO_ROOT.rglob("*.py"):
            relative_path = absolute_path.relative_to(REPO_ROOT)
            if any(part in exclude_dirs for part in relative_path.parts):
                continue
            posix = relative_path.as_posix()
            if posix in allow_files:
                continue
            text = absolute_path.read_text(encoding="utf-8")
            if PRIVATE_SAVE_METHOD in text:
                violators.append(posix)

        assert violators == [], (
            f"Unexpected production callers of {PRIVATE_SAVE_METHOD!r}: {violators}. "
            "Only services/review_workflow_service.py, services/content_workflow.py "
            "(JobRunner backer), and feedback/manager.py may reference the private "
            "save method."
        )


class TestJsonFormParity:
    """ARCH-03 success criterion #2: JSON and form variants invoke the same path."""

    def test_approve_json_and_form_invoke_same_service_path(self, dashboard, review_client):
        """Both /approve/{id} (form) and /api/content/{id}/approve (JSON) call
        dashboard.review_workflow.transition with ReviewAction.APPROVE."""
        review_id = _seed_pending_review(dashboard)
        mock_transition = MagicMock(return_value=ReviewRecord.from_dict({"review_id": review_id, "status": "approved"}))
        dashboard.review_workflow.transition = mock_transition

        resp_json = review_client.post(
            f"/api/content/{review_id}/approve",
            json={"feedback": "ok", "publish": False},
        )
        assert resp_json.status_code == 200
        assert resp_json.json()["success"] is True

        mock_transition.reset_mock()
        resp_form = review_client.post(
            f"/approve/{review_id}",
            data={"feedback": "ok", "publish": "false"},
            follow_redirects=False,
        )
        assert resp_form.status_code == 303

        approve_calls = [
            call
            for call in mock_transition.call_args_list
            if call.args and call.args[1] is ReviewAction.APPROVE
        ]
        assert len(approve_calls) >= 1, (
            "Form /approve route must call review_workflow.transition with "
            "ReviewAction.APPROVE"
        )

    def test_decline_json_and_form_invoke_same_service_path(self, dashboard, review_client):
        """Both /api/decline/{id} (JSON) and /decline/{id} (form delegator)
        land on review_workflow.transition with ReviewAction.DECLINE."""
        review_id = _seed_pending_review(dashboard)
        mock_transition = MagicMock(return_value=ReviewRecord.from_dict({"review_id": review_id, "status": "declined"}))
        dashboard.review_workflow.transition = mock_transition

        resp_json = review_client.post(
            f"/api/decline/{review_id}",
            json={"feedback": "no good"},
        )
        assert resp_json.status_code == 200
        assert resp_json.json()["success"] is True

        mock_transition.reset_mock()
        resp_form = review_client.post(
            f"/decline/{review_id}",
            data={"feedback": "no good"},
            follow_redirects=False,
        )
        assert resp_form.status_code == 303

        decline_calls = [
            call
            for call in mock_transition.call_args_list
            if call.args and call.args[1] is ReviewAction.DECLINE
        ]
        assert len(decline_calls) >= 1, (
            "Form /decline route must call review_workflow.transition with "
            "ReviewAction.DECLINE"
        )


class TestTypedErrorTranslation:
    """ARCH-03 success criterion #4: typed error codes surface in JSON."""

    def test_unknown_review_returns_typed_code_in_json(self, dashboard, review_client):
        """POST /api/decline/<nonexistent_id> -> JSON contains code=UNKNOWN_REVIEW."""
        resp = review_client.post(
            "/api/decline/does-not-exist-12345",
            json={"feedback": "n/a"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["code"] == UNKNOWN_REVIEW

    def test_invalid_transition_returns_typed_code_in_json(self, dashboard, review_client):
        """Seed a declined record, then POST /api/content/{id}/approve with publish=true.

        The service raises INVALID_TRANSITION (declined is terminal); the
        route must surface code=INVALID_TRANSITION in the JSON response.
        """
        review_id = _seed_pending_review(dashboard)
        dashboard.review_workflow.transition(review_id, ReviewAction.DECLINE)

        resp = review_client.post(
            f"/api/content/{review_id}/approve",
            json={"feedback": "retry", "publish": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["code"] == INVALID_TRANSITION

    def test_approve_rejects_invalid_body_via_pydantic(self, dashboard, review_client):
        """POST /api/content/{id}/approve with an oversized scheduled_date must be
        rejected by ApproveContentRequest (max_length=80) before the service is
        touched. Pins WR-05: the test app uses the production Pydantic model, so
        validation divergences between test and prod are caught here."""
        review_id = _seed_pending_review(dashboard)
        mock_transition = MagicMock(return_value=ReviewRecord.from_dict({"review_id": review_id, "status": "approved"}))
        dashboard.review_workflow.transition = mock_transition

        resp = review_client.post(
            f"/api/content/{review_id}/approve",
            json={"scheduled_date": "x" * 200},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "error" in body
        mock_transition.assert_not_called()


class TestApproveWithoutPublish:
    """ARCH-03 success criterion #3: approve-without-publish surface pin."""

    def test_api_approve_with_publish_false_does_not_schedule(self, dashboard, review_client):
        """POST /api/content/{id}/approve body={publish:false} must NOT call
        publishing_service.publish_record and must return scheduling with
        scheduled=False."""
        review_id = _seed_pending_review(dashboard)

        pub_mock = MagicMock()
        dashboard.publishing_service.publish_record = pub_mock

        resp = review_client.post(
            f"/api/content/{review_id}/approve",
            json={"feedback": "ok", "publish": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["scheduling"]["scheduled"] is False
        assert body["scheduling"]["skipped"] == "publish=false"
        pub_mock.assert_not_called()

    def test_api_approve_default_publishes(self, dashboard, review_client):
        """POST /api/content/{id}/approve with default body (publish defaults to
        true) MUST attempt to schedule via publishing_service.

        The publishing call will fail (no provider configured in test), so
        the response scheduling.scheduled will be False, but the mock must
        have been called once."""
        review_id = _seed_pending_review(dashboard)

        from integrations.publishing_provider import PublishResult
        from services.publishing_service import PublishingAttempt

        pub_mock = MagicMock(
            return_value=PublishingAttempt(
                result=PublishResult(success=True, provider="typefully"),
                project_id="proj-test",
                platform="twitter",
                provider_name="typefully",
                account_id="a1",
            )
        )
        dashboard.publishing_service.publish_record = pub_mock

        resp = review_client.post(
            f"/api/content/{review_id}/approve",
            json={"feedback": "ok"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["scheduling"]["scheduled"] is True
        pub_mock.assert_called_once()
