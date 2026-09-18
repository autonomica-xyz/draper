"""Canonical review-workflow service per ARCH-03.

This service owns the v2 review state machine. It exposes a single
``transition(review_id, action, ...)`` entry point that validates the
requested transition against ``data.review_models.VALID_TRANSITIONS``,
mutates the underlying raw-dict record, extracts learning patterns, and
persists via ``feedback.manager.FeedbackManager``'s private single-record
save method. The service IS the legitimate caller of that private method
-- the structural exclusivity is closed at the dashboard boundary by plan
02-03.

The service splits the conjoined approve/schedule path so that
``ReviewAction.APPROVE`` performs ONLY the status change, history append,
and pattern extraction -- it does NOT call
``services.publishing_service.ProjectPublishingService.publish_record``
or any provider. ``ReviewAction.SCHEDULE`` is the only action that
crosses to the publishing service. This split is the heart of ARCH-03
success criterion #3 (approve-without-publish) and the precondition for
plan 02-03's caller migration.

Per AGENTS.md gotcha #7 ("Auto-fix runs synchronously in the request"),
the auto-fix LLM call is owned by a separate ``apply_auto_fix()``
helper; ``transition(..., ReviewAction.NEEDS_WORK, ...)`` does NOT
invoke ``learning.auto_fix.AutoFixEngine``. This preserves the existing
sync-in-request behavior; async migration is deferred to Phase 4.

The service mirrors the Phase 1 ``ProjectService`` pattern:
constructor-injected collaborators, return-dataclass-at-every-boundary,
project-match verification at the entry point.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from data.review_models import (
    VALID_TRANSITIONS,
    FeedbackHistoryEntry,
    ReviewAction,
    ReviewRecord,
    ReviewStatus,
)
from services.content_workflow import (
    extract_negative_tags,
    extract_positive_tags,
    merge_tags,
)
from services.observability import get_logger


_logger = get_logger(__name__)


INVALID_TRANSITION = "INVALID_TRANSITION"
UNKNOWN_REVIEW = "UNKNOWN_REVIEW"
UNKNOWN_ACTION = "UNKNOWN_ACTION"
PROJECT_MISMATCH = "PROJECT_MISMATCH"
PUBLISH_FAILED = "PUBLISH_FAILED"


class ReviewTransitionError(Exception):
    """Typed error raised by ``ReviewWorkflowService.transition``.

    Carries a machine-stable ``code`` (one of the module-level constants
    ``INVALID_TRANSITION``, ``UNKNOWN_REVIEW``, ``UNKNOWN_ACTION``,
    ``PROJECT_MISMATCH``, ``PUBLISH_FAILED``) plus the operational
    context (``review_id``, ``from_status``, ``to_status``, ``action``)
    so dashboard route handlers in plan 02-03 can switch on ``code``
    rather than parsing free-form messages.

    Per CONTEXT.md 'Typed Errors (locked by success criterion #4)':
    ``.code`` is a machine-stable string constant; ``.message`` is
    operational and contains no user feedback text or PII; ``.review_id``
    is the persisted identifier (not user-supplied PII).
    """

    def __init__(
        self,
        code: str,
        *,
        review_id: Optional[str] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        action: Optional[str] = None,
        message: Optional[str] = None,
    ):
        self.code = code
        self.review_id = review_id
        self.from_status = from_status
        self.to_status = to_status
        self.action = action
        self.message = message or (f"{code} for review_id={review_id} action={action}")
        super().__init__(self.message)

    def __str__(self) -> str:
        return (
            f"[{self.code}] review_id={self.review_id} "
            f"from={self.from_status} action={self.action}: {self.message}"
        )


class ReviewWorkflowService:
    """Owns the v2 review state machine.

    Composes the same three collaborators as
    ``services.content_workflow.ContentWorkflowService``:
    ``feedback_manager`` (persistence delegate and the only legitimate
    writer of its private single-record save method), ``project_context``
    (project identity / provider routing), and ``publishing_service``
    (called ONLY by ``_apply_schedule``). The service is constructed by
    plan 02-03 at ``dashboard_instance.review_workflow`` exactly the way
    ``dashboard_instance.content_workflow`` is wired today
    (``unified_dashboard.py:289-293``).
    """

    def __init__(self, feedback_manager, project_context, publishing_service):
        """Store the three collaborators as public attributes.

        Mirrors ``services.content_workflow.py:15-23`` naming so plan
        02-03 can wire ``dashboard_instance.review_workflow`` the same
        way ``dashboard_instance.content_workflow`` is wired today.
        """
        self.feedback_manager = feedback_manager
        self.project_context = project_context
        self.publishing_service = publishing_service

    def transition(
        self,
        review_id: str,
        action,
        *,
        feedback: str = "",
        explicit_tags: str = "",
        scheduled_date: Optional[str] = None,
        provider_name: Optional[str] = None,
        platform: Optional[str] = None,
        media: Optional[dict] = None,
        actor=None,
    ) -> ReviewRecord:
        """Validate and apply a single review-state transition.

        Returns the updated record as a typed ``ReviewRecord``. Raises
        ``ReviewTransitionError`` with a machine-stable ``code`` for
        every invalid path (unknown review, unknown action, invalid
        transition, project mismatch, publish failure).
        """
        feedback = feedback or ""
        if isinstance(action, ReviewAction):
            review_action = action
        else:
            try:
                review_action = ReviewAction(action)
            except (ValueError, TypeError):
                raise ReviewTransitionError(
                    UNKNOWN_ACTION,
                    review_id=review_id,
                    action=str(action),
                    message=f"Unknown review action: {action!r}",
                )

        record = self.feedback_manager._load_review_record(review_id)
        if record is None:
            raise ReviewTransitionError(
                UNKNOWN_REVIEW,
                review_id=review_id,
                action=review_action.value,
                message=f"Unknown review_id: {review_id}",
            )

        from_status_str = record.get("status", "pending_review")
        try:
            from_status = ReviewStatus(from_status_str)
        except ValueError:
            from_status = ReviewStatus.PENDING_REVIEW

        actor_project_id = getattr(actor, "project_id", None)
        record_project_id = record.get("project_id")
        if actor_project_id and record_project_id and actor_project_id != record_project_id:
            raise ReviewTransitionError(
                PROJECT_MISMATCH,
                review_id=review_id,
                action=review_action.value,
                from_status=from_status.value,
                message=(
                    f"Actor project_id={actor_project_id} does not match "
                    f"record project_id={record_project_id}"
                ),
            )

        allowed = VALID_TRANSITIONS.get(from_status, frozenset())
        is_status_change = review_action is not ReviewAction.ATTACH_MEDIA
        if is_status_change and review_action not in allowed:
            raise ReviewTransitionError(
                INVALID_TRANSITION,
                review_id=review_id,
                from_status=from_status.value,
                action=review_action.value,
                message=(f"Action {review_action.value} not valid from status {from_status.value}"),
            )

        if review_action is ReviewAction.APPROVE:
            from_status_before = from_status.value
            self._apply_approve(record, feedback, explicit_tags)
        elif review_action is ReviewAction.DECLINE:
            from_status_before = from_status.value
            self._apply_decline(record, feedback, explicit_tags)
        elif review_action is ReviewAction.NEEDS_WORK:
            from_status_before = from_status.value
            self._apply_needs_work(record, feedback, explicit_tags)
        elif review_action is ReviewAction.SCHEDULE:
            from_status_before = from_status.value
            self._apply_schedule(
                record,
                feedback=feedback,
                explicit_tags=explicit_tags,
                scheduled_date=scheduled_date,
                provider_name=provider_name,
                platform=platform,
            )
        elif review_action is ReviewAction.PUBLISH:
            from_status_before = from_status.value
            self._apply_publish(record, provider_name=provider_name, platform=platform)
        elif review_action is ReviewAction.ATTACH_MEDIA:
            from_status_before = from_status.value
            self._apply_attach_media(record, media=media)
        else:
            raise ReviewTransitionError(
                UNKNOWN_ACTION,
                review_id=review_id,
                action=review_action.value,
                message=f"Unhandled review action: {review_action.value}",
            )

        to_status_str = record.get("status", from_status_before)
        history = record.get("feedback_history") or []
        last_entry = history[-1] if history else {}
        tags_count = len(last_entry.get("learning_tags", []) or [])
        self._emit_event(
            review_id=review_id,
            action=review_action.value,
            project_id=record.get("project_id"),
            payload={
                "from_status": from_status_before,
                "to_status": to_status_str,
                "actor": _actor_label(actor),
                "tags_count": tags_count,
            },
        )

        return ReviewRecord.from_dict(record)

    def apply_auto_fix(
        self,
        review_id: str,
        feedback: str = "",
        *,
        job_queue: Any = None,
        actor: Any = None,
    ) -> Dict[str, Any]:
        """Per Phase 4 plan 04-02 (ARCH-05 D-3): enqueues a ``fix_content`` job
        and returns the enqueued job record.

        The worker (Plan 04-01) drains the job, calls AutoFixEngine, and
        calls ``complete_auto_fix()`` to persist the result. AGENTS.md
        gotcha #7 is broken here -- auto-fix no longer blocks the request.
        """
        record = self.feedback_manager._load_review_record(review_id)
        if record is None:
            raise ReviewTransitionError(
                UNKNOWN_REVIEW,
                review_id=review_id,
                message=f"Unknown review_id: {review_id}",
            )

        post_data = record.get("post_data") or {}
        project_id = record.get("project_id") or post_data.get("project_id", "")

        queue = job_queue
        if queue is None:
            queue = getattr(self, "job_queue", None)
        if queue is None:
            raise RuntimeError("job_queue is required to enqueue fix_content")

        payload = {
            "review_id": review_id,
            "feedback": feedback,
            "project_id": project_id,
        }
        enqueued = queue.enqueue(
            "fix_content",
            project_id=project_id,
            payload=payload,
        )

        record["auto_fix_status"] = "queued"
        record["auto_fix_job_id"] = enqueued.get("job_id")
        self._persist(review_id, record)
        return enqueued

    def complete_auto_fix(
        self,
        review_id: str,
        fix: Dict[str, Any],
        feedback: str = "",
    ) -> ReviewRecord:
        """Worker-side helper called by ``JobRunner._fix_content`` after
        AutoFixEngine returns.

        Persists the fixed content, resets status to pending_review,
        appends fix_history + feedback_history. Does NOT call AutoFixEngine
        (the worker already did).

        Raises ``ReviewTransitionError(INVALID_TRANSITION)`` if the review
        is no longer in ``needs_work`` status (e.g. the user approved or
        declined while the worker was running). The caller must treat that
        as a non-retryable skip -- the user's choice wins.
        """
        record = self.feedback_manager._load_review_record(review_id)
        if record is None:
            raise ReviewTransitionError(
                UNKNOWN_REVIEW,
                review_id=review_id,
                message=f"Unknown review_id: {review_id}",
            )

        current_status = record.get("status", "needs_work")
        if current_status != "needs_work":
            raise ReviewTransitionError(
                INVALID_TRANSITION,
                review_id=review_id,
                from_status=current_status,
                to_status="pending_review",
                message=(
                    f"Review is no longer in needs_work (now {current_status}); "
                    f"skipping auto-fix to preserve user action"
                ),
            )

        post_data = record.get("post_data") or {}
        post_data["content"] = fix.get("content", post_data.get("content", ""))
        record["post_data"] = post_data

        self._record_history(
            record,
            from_status_str=record.get("status", "needs_work"),
            to_status_str="pending_review",
            feedback=feedback,
            learning_tags=[],
            auto_fix_applied=True,
        )

        fix_history = record.get("fix_history") or []
        fix_history.append(
            {
                "feedback": feedback,
                "explanation": fix.get("explanation", ""),
                "fixed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        record["fix_history"] = fix_history
        record["status"] = "pending_review"
        record.pop("auto_fix_status", None)

        self._persist(review_id, record)
        return ReviewRecord.from_dict(record)

    def _record_history(
        self,
        record: dict,
        from_status_str: str,
        to_status_str: str,
        feedback: str,
        learning_tags,
        auto_fix_applied: bool = False,
    ) -> None:
        """Append a typed FeedbackHistoryEntry to record['feedback_history']."""
        entry = FeedbackHistoryEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            from_status=from_status_str,
            to_status=to_status_str,
            feedback=feedback,
            learning_tags=list(learning_tags or []),
            auto_fix_applied=auto_fix_applied,
        )
        history = record.get("feedback_history") or []
        history.append(entry.to_dict())
        record["feedback_history"] = history

    def _extract_patterns(
        self,
        record: dict,
        outcome_status_str: str,
        project_id: str,
        feedback: str,
        tags,
    ) -> None:
        """Defensively extract learning patterns; never raise into transition."""
        try:
            from learning.pattern_extractor import PatternExtractor

            PatternExtractor().extract_and_save_patterns(
                record.get("post_data") or {},
                outcome_status_str,
                project_id,
                feedback=feedback,
                tags=list(tags or []),
            )
        except Exception as exc:
            print(f"Warning: Could not extract learning patterns: {exc}")

    def _persist(self, review_id: str, record: dict) -> None:
        """Delegate to FeedbackManager's private single-record save method."""
        self.feedback_manager._save_review_record(review_id, record)

    def _apply_approve(self, record: dict, feedback: str, explicit_tags: str) -> None:
        """Mark approved, append history, extract positive patterns. No provider call."""
        from_status_str = record.get("status", "pending_review")
        tags = merge_tags(
            explicit_tags,
            extract_positive_tags(feedback) if feedback else [],
        )
        record["status"] = "approved"
        record["approved_at"] = datetime.now(timezone.utc).isoformat()
        record["feedback"] = feedback
        self._record_history(
            record,
            from_status_str=from_status_str,
            to_status_str="approved",
            feedback=feedback,
            learning_tags=tags,
        )
        self._extract_patterns(
            record,
            "approved",
            record.get("project_id", ""),
            feedback,
            tags,
        )
        record.pop("scheduling_error", None)
        self._persist(record.get("review_id", ""), record)

    def _apply_decline(self, record: dict, feedback: str, explicit_tags: str) -> None:
        """Mark declined (terminal), append history, extract negative patterns."""
        tags = merge_tags(
            explicit_tags,
            extract_negative_tags(feedback or "Content declined"),
        )
        from_status_str = record.get("status", "pending_review")
        record["status"] = "declined"
        record["declined_at"] = datetime.now(timezone.utc).isoformat()
        record["feedback"] = feedback
        self._record_history(
            record,
            from_status_str=from_status_str,
            to_status_str="declined",
            feedback=feedback,
            learning_tags=tags,
        )
        self._extract_patterns(
            record,
            "declined",
            record.get("project_id", ""),
            feedback,
            tags,
        )
        self._persist(record.get("review_id", ""), record)

    def _apply_needs_work(self, record: dict, feedback: str, explicit_tags: str) -> None:
        """Mark needs_work, append history, extract negative patterns. No auto-fix."""
        tags = merge_tags(
            explicit_tags,
            extract_negative_tags(feedback or ""),
        )
        from_status_str = record.get("status", "pending_review")
        record["status"] = "needs_work"
        record["needs_work_at"] = datetime.now(timezone.utc).isoformat()
        record["feedback"] = feedback
        self._record_history(
            record,
            from_status_str=from_status_str,
            to_status_str="needs_work",
            feedback=feedback,
            learning_tags=tags,
        )
        self._extract_patterns(
            record,
            "needs_work",
            record.get("project_id", ""),
            feedback,
            tags,
        )
        self._persist(record.get("review_id", ""), record)

    def _apply_schedule(
        self,
        record: dict,
        *,
        feedback: str,
        explicit_tags: str,
        scheduled_date: Optional[str],
        provider_name: Optional[str],
        platform: Optional[str],
    ) -> None:
        """Call publishing_service.publish_record; on success mark scheduled.

        On failure, restore the original status, persist scheduling_error,
        and raise ``ReviewTransitionError(code=PUBLISH_FAILED)`` so the
        caller can surface the typed error.
        """
        original_status = record.get("status", "approved")
        review_id = record.get("review_id", "")

        try:
            attempt = self.publishing_service.publish_record(
                record,
                provider_name=provider_name,
                platform=platform,
                scheduled_at=scheduled_date,
                schedule_next_slot=not bool(scheduled_date),
            )
        except Exception as exc:
            record["status"] = original_status
            record["scheduling_error"] = str(exc)
            self._persist(review_id, record)
            raise ReviewTransitionError(
                PUBLISH_FAILED,
                review_id=review_id,
                action="schedule",
                from_status=original_status,
                message=str(exc),
            )

        result = attempt.result
        if result.success:
            record["status"] = "scheduled"
            record["published_via"] = result.provider
            record["scheduled_at"] = (
                attempt.scheduled_at.isoformat()
                if attempt.scheduled_at
                else datetime.now(timezone.utc).isoformat()
            )
            if result.draft_id:
                record["draft_id"] = result.draft_id
            if result.url:
                record["draft_url"] = result.url
            record.pop("scheduling_error", None)

            tags = merge_tags(
                explicit_tags,
                extract_positive_tags(feedback) if feedback else [],
            )
            self._record_history(
                record,
                from_status_str=original_status,
                to_status_str="scheduled",
                feedback=feedback or "Approved and scheduled",
                learning_tags=tags,
            )
            self._extract_patterns(
                record,
                "approved",
                attempt.project_id,
                feedback,
                tags,
            )
            self._persist(review_id, record)
            return

        record["status"] = original_status
        record["scheduling_error"] = result.error
        self._persist(review_id, record)
        raise ReviewTransitionError(
            PUBLISH_FAILED,
            review_id=review_id,
            action="schedule",
            from_status=original_status,
            message=result.error or "Publishing failed",
        )

    def _apply_publish(
        self,
        record: dict,
        *,
        provider_name: Optional[str],
        platform: Optional[str],
    ) -> None:
        """Mark published without calling publishing_service.

        Distinct from SCHEDULE: this is the status mark for items already
        scheduled externally (mirrors services/content_workflow.py:148).
        """
        record["status"] = "published"
        record["published_at"] = datetime.now(timezone.utc).isoformat()
        self._persist(record.get("review_id", ""), record)

    def _apply_attach_media(self, record: dict, *, media: Optional[dict]) -> None:
        """Update the record's media dict without changing status."""
        existing_media = record.get("media") or {}
        if isinstance(existing_media, list):
            existing_media = {"carousels": existing_media}
        if media:
            existing_media.update(media)
        record["media"] = existing_media
        self._persist(record.get("review_id", ""), record)

    def _emit_event(
        self,
        *,
        review_id: str,
        action: str,
        project_id: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        store = getattr(self.feedback_manager, "store", None)
        if store is None or not hasattr(store, "record_event"):
            return
        try:
            store.record_event(
                category="review",
                action=action,
                review_id=review_id,
                project_id=project_id,
                payload=payload,
            )
        except Exception as exc:
            _logger.warning("system_events.review.%s failed: %s", action, exc)


def _actor_label(actor) -> str:
    if actor is None:
        return ""
    label = getattr(actor, "label", None)
    if label:
        return str(label)
    role = getattr(actor, "role", None)
    if role:
        return str(role)
    return type(actor).__name__
