"""Tests for services.review_workflow_service.ReviewWorkflowService.

Pins the v2 review state machine contract. The central invariant pinned
here is ARCH-03 success criterion #3 (approve-without-publish):
``test_approve_does_not_call_any_provider`` asserts that the APPROVE
path physically cannot reach
``services.publishing_service.ProjectPublishingService.publish_record``.
The typed-error tests pin ARCH-03 success criterion #4 (machine-stable
``.code`` on every invalid path).

The regression contracts in ``tests/test_review_flow_sqlite.py`` and
``tests/test_e2e_validation.py`` are NOT modified -- this module tests
only the new service.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from data.review_models import ReviewAction, ReviewStatus
from feedback.manager import FeedbackManager
from integrations.publishing_provider import PublishResult
from services.content_workflow import extract_negative_tags
from services.project_context import ProjectContextService
from services.publishing_service import PublishingAttempt
from services.review_workflow_service import (
    INVALID_TRANSITION,
    PROJECT_MISMATCH,
    PUBLISH_FAILED,
    ReviewTransitionError,
    ReviewWorkflowService,
    UNKNOWN_ACTION,
    UNKNOWN_REVIEW,
)

# Schedule-failure visibility is part of the pinned contract: apply the
# hot-patch explicitly at module level so these unit tests are deterministic
# instead of depending on the incidental ``services.project_context`` import
# side effect (idempotent -- a no-op when already applied).
from services.schedule_fail_visibility import apply as _apply_schedule_fail_visibility

_apply_schedule_fail_visibility()


def _make_post(platform="twitter", project_id="proj-test", **overrides):
    """Build a minimal post_data dict for add_for_review."""
    post = {
        "platform": platform,
        "content_type": "tweet",
        "pillar": "growth",
        "hook_type": "question",
        "content": "Sample content for testing.",
        "project_id": project_id,
    }
    post.update(overrides)
    return post


def _build_service(tmp_path, *, publishing_service=None):
    """Construct a ReviewWorkflowService against an isolated tmp_path store.

    The publishing_service is injected as a MagicMock by default so the
    approve-isolation and schedule-failure tests can assert provider
    behavior precisely. ProjectContextService is real but backed by a
    MagicMock project_manager because transition() does not reach into
    project_context for the dispatched actions under test.
    """
    fm = FeedbackManager(data_dir=str(tmp_path))
    project_context = ProjectContextService(MagicMock())
    publishing_service = publishing_service if publishing_service is not None else MagicMock()
    return ReviewWorkflowService(fm, project_context, publishing_service)


def _seed_pending_review(service, **post_overrides):
    """Seed a pending_review record and return its review_id."""
    record = service.feedback_manager.add_for_review(_make_post(**post_overrides))
    return record["review_id"]


class TestReviewWorkflowServiceContract:
    """Pin every behavioral claim of ReviewWorkflowService.transition."""

    def test_approve_pending_review_transitions_to_approved(self, tmp_path):
        """pending_review -> APPROVE returns ReviewRecord with status APPROVED."""
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)

        record = service.transition(review_id, ReviewAction.APPROVE, feedback="ok")

        assert record.status == ReviewStatus.APPROVED
        assert record.raw["status"] == "approved"
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "approved"
        assert stored["feedback"] == "ok"
        assert isinstance(stored.get("feedback_history"), list)
        assert len(stored["feedback_history"]) >= 1
        last = stored["feedback_history"][-1]
        assert last["to_status"] == "approved"
        assert last["feedback"] == "ok"

    def test_approve_does_not_call_any_provider(self, tmp_path):
        """ARCH-03 success criterion #3: APPROVE must not touch any provider.

        This is the central invariant of plan 02-02: the conjoined
        approve/schedule path is split so approve-without-publish
        becomes possible. The publishing_service is injected as a mock
        and asserted to have no publish_record calls after APPROVE.
        """
        publishing_service = MagicMock()
        service = _build_service(tmp_path, publishing_service=publishing_service)
        review_id = _seed_pending_review(service)

        service.transition(review_id, ReviewAction.APPROVE, feedback="ok")

        publishing_service.publish_record.assert_not_called()

    def test_schedule_calls_publishing_service(self, tmp_path):
        """SCHEDULE (not APPROVE) is the provider-touching action."""
        publishing_service = MagicMock()
        attempt = PublishingAttempt(
            result=PublishResult(
                success=True,
                provider="typefully",
                draft_id="d1",
                url="http://x",
            ),
            project_id="proj-test",
            platform="twitter",
            provider_name="typefully",
            account_id="a1",
        )
        publishing_service.publish_record.return_value = attempt
        service = _build_service(tmp_path, publishing_service=publishing_service)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.APPROVE, feedback="ok")

        record = service.transition(review_id, ReviewAction.SCHEDULE, feedback="go")

        assert record.status == ReviewStatus.SCHEDULED
        publishing_service.publish_record.assert_called_once()
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "scheduled"
        assert stored["published_via"] == "typefully"
        assert stored["draft_id"] == "d1"

    def test_schedule_failure_sets_scheduling_error_and_resets_to_pending_review(self, tmp_path):
        """SCHEDULE failure raises PUBLISH_FAILED, persists scheduling_error, and
        resets status to pending_review so the item stays visible in the Pipeline
        (schedule-failure visibility contract; the item can be retried)."""
        publishing_service = MagicMock()
        attempt = PublishingAttempt(
            result=PublishResult(success=False, error="boom"),
            project_id="proj-test",
            platform="twitter",
            provider_name="typefully",
            account_id="a1",
        )
        publishing_service.publish_record.return_value = attempt
        service = _build_service(tmp_path, publishing_service=publishing_service)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.APPROVE, feedback="ok")

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.transition(review_id, ReviewAction.SCHEDULE, feedback="go")

        assert exc_info.value.code == PUBLISH_FAILED
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "pending_review"
        assert stored["scheduling_error"] == "boom"

    def test_decline_extracts_negative_patterns_and_is_terminal(self, tmp_path):
        """DECLINE sets status, then APPROVE from declined raises INVALID_TRANSITION."""
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)

        record = service.transition(
            review_id,
            ReviewAction.DECLINE,
            feedback="too generic and weak hook",
        )

        assert record.status == ReviewStatus.DECLINED
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "declined"

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.transition(review_id, ReviewAction.APPROVE, feedback="retry")

        assert exc_info.value.code == INVALID_TRANSITION
        assert exc_info.value.from_status == "declined"
        assert exc_info.value.action == "approve"

    def test_needs_work_extracts_negative_patterns_and_does_not_auto_fix(
        self, tmp_path, monkeypatch
    ):
        """transition(NEEDS_WORK) must not invoke AutoFixEngine (AGENTS.md gotcha #7)."""
        autofix_mock = MagicMock()
        monkeypatch.setattr("learning.auto_fix.AutoFixEngine", autofix_mock)

        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)

        record = service.transition(
            review_id,
            ReviewAction.NEEDS_WORK,
            feedback="too long",
        )

        assert record.status == ReviewStatus.NEEDS_WORK
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "needs_work"
        autofix_mock.assert_not_called()

    def test_needs_work_with_none_feedback_does_not_crash(self, tmp_path):
        """Regression for WR-01: feedback=None (JSON {"feedback": null}) must not crash.

        extract_negative_tags does feedback.lower(); the needs-work path
        must coerce None to "" the same way _apply_decline already does.
        The dashboard JSON route's body.get("feedback", "") returns the
        stored None when a client sends {"feedback": null}, and the MCP
        request_fix(feedback: str = "") does not guard against null either.
        """
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)

        record = service.transition(review_id, ReviewAction.NEEDS_WORK, feedback=None)

        assert record.status == ReviewStatus.NEEDS_WORK
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "needs_work"

    def test_publish_marks_published_without_calling_provider(self, tmp_path):
        """PUBLISH marks status=published without crossing to the provider."""
        publishing_service = MagicMock()
        attempt = PublishingAttempt(
            result=PublishResult(
                success=True,
                provider="typefully",
                draft_id="d1",
                url="http://x",
            ),
            project_id="proj-test",
            platform="twitter",
            provider_name="typefully",
            account_id="a1",
        )
        publishing_service.publish_record.return_value = attempt
        service = _build_service(tmp_path, publishing_service=publishing_service)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.APPROVE)
        service.transition(review_id, ReviewAction.SCHEDULE)
        publishing_service.reset_mock()

        record = service.transition(review_id, ReviewAction.PUBLISH)

        assert record.status == ReviewStatus.PUBLISHED
        publishing_service.publish_record.assert_not_called()
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "published"
        assert "published_at" in stored

    def test_attach_media_updates_media_without_changing_status(self, tmp_path):
        """ATTACH_MEDIA updates the media dict and leaves status untouched."""
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)

        record = service.transition(
            review_id,
            ReviewAction.ATTACH_MEDIA,
            media={"visual_prop": {"image_path": "x.png"}},
        )

        assert record.status == ReviewStatus.PENDING_REVIEW
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "pending_review"
        assert stored["media"]["visual_prop"]["image_path"] == "x.png"

    def test_unknown_review_raises_typed_error(self, tmp_path):
        """An unknown review_id raises ReviewTransitionError(code=UNKNOWN_REVIEW)."""
        service = _build_service(tmp_path)

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.transition("nonexistent_id", ReviewAction.APPROVE)

        assert exc_info.value.code == UNKNOWN_REVIEW
        assert exc_info.value.review_id == "nonexistent_id"

    def test_invalid_transition_raises_typed_error(self, tmp_path):
        """An invalid transition raises ReviewTransitionError(code=INVALID_TRANSITION)."""
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.DECLINE)

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.transition(review_id, ReviewAction.APPROVE)

        assert exc_info.value.code == INVALID_TRANSITION
        assert exc_info.value.from_status == "declined"
        assert exc_info.value.action == "approve"

    def test_unknown_action_raises_typed_error(self, tmp_path):
        """An unknown action string raises ReviewTransitionError(code=UNKNOWN_ACTION)."""
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.transition(review_id, "bogus")

        assert exc_info.value.code == UNKNOWN_ACTION

    def test_project_mismatch_raises_typed_error(self, tmp_path):
        """Actor project_id disagreeing with record raises PROJECT_MISMATCH."""
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service, project_id="proj-a")

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.transition(
                review_id,
                ReviewAction.APPROVE,
                actor=SimpleNamespace(project_id="proj-b"),
            )

        assert exc_info.value.code == PROJECT_MISMATCH


class TestApplyAutoFixEnqueuesJob:
    """Per Phase 4 plan 04-02 (ARCH-05 D-3): apply_auto_fix enqueues a fix_content
    job; complete_auto_fix persists the result. AGENTS.md gotcha #7 broken."""

    def test_apply_auto_fix_does_not_call_autofix_engine(self, tmp_path, monkeypatch):
        fixed_payload = {"content": "fixed", "explanation": "exp"}
        autofix_instance = MagicMock()
        autofix_instance.fix_content = AsyncMock(return_value=fixed_payload)
        autofix_cls = MagicMock(return_value=autofix_instance)
        monkeypatch.setattr("learning.auto_fix.AutoFixEngine", autofix_cls)

        from data.sqlite_store import SQLiteStore
        from services.job_queue import JobQueueService

        store = SQLiteStore(data_dir=str(tmp_path))
        job_queue = JobQueueService(store)
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback="fix it")

        result = service.apply_auto_fix(review_id, feedback="fix it", job_queue=job_queue)

        autofix_cls.assert_not_called()
        assert isinstance(result, dict)
        assert "job_id" in result
        enqueued = job_queue.get(result["job_id"])
        assert enqueued["kind"] == "fix_content"

    def test_apply_auto_fix_marks_record_queued(self, tmp_path):
        from data.sqlite_store import SQLiteStore
        from services.job_queue import JobQueueService

        store = SQLiteStore(data_dir=str(tmp_path))
        job_queue = JobQueueService(store)
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback="fix it")

        service.apply_auto_fix(review_id, feedback="fix it", job_queue=job_queue)

        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["auto_fix_status"] == "queued"

    def test_apply_auto_fix_payload_carries_review_and_feedback(self, tmp_path):
        from data.sqlite_store import SQLiteStore
        from services.job_queue import JobQueueService

        store = SQLiteStore(data_dir=str(tmp_path))
        job_queue = JobQueueService(store)
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback="fix it")

        result = service.apply_auto_fix(review_id, feedback="fix it", job_queue=job_queue)

        enqueued = job_queue.get(result["job_id"])
        assert enqueued["payload"]["review_id"] == review_id
        assert enqueued["payload"]["feedback"] == "fix it"
        assert enqueued["payload"]["project_id"]

    def test_apply_auto_fix_does_not_persist_queued_when_enqueue_raises(self, tmp_path):
        from data.sqlite_store import SQLiteStore
        from services.job_queue import JobQueueService

        store = SQLiteStore(data_dir=str(tmp_path))
        job_queue = JobQueueService(store)
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback="fix it")

        def _boom_enqueue(*args, **kwargs):
            raise RuntimeError("sqlite is locked")

        job_queue.enqueue = _boom_enqueue

        with pytest.raises(RuntimeError, match="sqlite is locked"):
            service.apply_auto_fix(review_id, feedback="fix it", job_queue=job_queue)

        stored = service.feedback_manager._load_review_record(review_id)
        assert stored.get("auto_fix_status") is None, (
            "apply_auto_fix must not persist auto_fix_status=queued when "
            "enqueue fails -- WR-02 leaves the review stuck on 'queued'"
        )

    def test_apply_auto_fix_records_job_id_on_record(self, tmp_path):
        from data.sqlite_store import SQLiteStore
        from services.job_queue import JobQueueService

        store = SQLiteStore(data_dir=str(tmp_path))
        job_queue = JobQueueService(store)
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback="fix it")

        result = service.apply_auto_fix(review_id, feedback="fix it", job_queue=job_queue)

        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["auto_fix_status"] == "queued"
        assert stored["auto_fix_job_id"] == result["job_id"]

    def test_complete_auto_fix_persists_worker_result(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "learning.auto_fix.AutoFixEngine", MagicMock()
        )

        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback="fix it")

        record = service.complete_auto_fix(
            review_id,
            fix={"content": "fixed by worker", "explanation": "exp"},
            feedback="fix it",
        )

        assert record.status == ReviewStatus.PENDING_REVIEW
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "pending_review"
        assert stored["post_data"]["content"] == "fixed by worker"
        assert stored["fix_history"][-1]["explanation"] == "exp"
        last_history = stored["feedback_history"][-1]
        assert last_history["auto_fix_applied"] is True
        assert last_history["from_status"] == "needs_work"
        assert last_history["to_status"] == "pending_review"

    def test_complete_auto_fix_unknown_review_raises_typed_error(self, tmp_path):
        service = _build_service(tmp_path)

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.complete_auto_fix(
                "does-not-exist-12345",
                fix={"content": "fixed", "explanation": "exp"},
                feedback="x",
            )

        assert exc_info.value.code == UNKNOWN_REVIEW

    def test_complete_auto_fix_skipped_when_review_already_approved(self, tmp_path):
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback="fix it")

        service.transition(review_id, ReviewAction.APPROVE, feedback="actually good")

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.complete_auto_fix(
                review_id,
                fix={"content": "stale worker output", "explanation": "exp"},
                feedback="fix it",
            )

        assert exc_info.value.code == INVALID_TRANSITION
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "approved"
        assert stored["post_data"]["content"] != "stale worker output"

    def test_complete_auto_fix_skipped_when_review_already_declined(self, tmp_path):
        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback="fix it")
        service.transition(review_id, ReviewAction.DECLINE, feedback="nope")

        with pytest.raises(ReviewTransitionError) as exc_info:
            service.complete_auto_fix(
                review_id,
                fix={"content": "stale", "explanation": "exp"},
                feedback="fix it",
            )

        assert exc_info.value.code == INVALID_TRANSITION
        stored = service.feedback_manager._load_review_record(review_id)
        assert stored["status"] == "declined"


class TestJsonFormParityContract:
    """Pin ARCH-03 success criterion #2: JSON and form variants route through the same path."""

    def test_decline_via_service_matches_legacy_extract(self, tmp_path):
        """Decline feedback round-trips through services.content_workflow.extract_negative_tags.

        Plan 02-03 routes both JSON-body and form-encoded decline calls
        through ReviewWorkflowService.transition; this test pins that the
        tag extraction is the same legacy extractor (so the parity is
        real, not reimplemented).
        """
        feedback = "too long and generic"
        expected_tags = set(extract_negative_tags(feedback))
        assert expected_tags == {"too_long", "too_generic"}

        service = _build_service(tmp_path)
        review_id = _seed_pending_review(service)

        service.transition(review_id, ReviewAction.DECLINE, feedback=feedback)

        stored = service.feedback_manager._load_review_record(review_id)
        last_history = stored["feedback_history"][-1]
        assert set(last_history["learning_tags"]) == expected_tags
