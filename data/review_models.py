"""Typed review-domain vocabulary for the v2 review workflow consolidation.

This module is purely additive in plan 02-01: no production caller imports
it yet. Plan 02-02 (``services/review_workflow_service.py``) will be the
first consumer; plan 02-03 will reference ``ReviewAction`` by name at the
dashboard/MCP/CLI route boundary.

Per AGENTS.md gotcha #2 ("Review records are raw dicts, not dataclass
instances") the typed wrappers here *project* over the existing raw-dict
shape persisted by ``feedback.manager.FeedbackManager`` and
``data.sqlite_store.SQLiteStore`` -- they do not replace dict storage.
``ReviewRecord.from_dict(raw).to_dict()`` is identity, including arbitrary
extra keys the storage layer may grow in the future.

The status vocabulary mirrors the existing literals produced by
``FeedbackManager`` (pending_review, approved, scheduled, needs_work,
declined) plus the legacy "rejected" alias that some historical records
carry. ``ReviewAction`` is the split transition surface: ``SCHEDULE``
creates a provider draft; ``PUBLISH`` marks an already-scheduled item as
published; ``ATTACH_MEDIA`` covers the non-transition media metadata
updates that today bypass any service.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class ReviewStatus(str, Enum):
    """Enumeration of review record statuses.

    Inherits ``(str, Enum)`` so each member is JSON-serializable and
    equality-comparable to its raw string value -- the same form
    ``FeedbackManager`` and ``SQLiteStore`` persist. ``REJECTED`` is an
    explicit alias for legacy records that still carry the "rejected"
    literal; it is treated as terminal alongside ``DECLINED``.
    """

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    NEEDS_WORK = "needs_work"
    DECLINED = "declined"
    REJECTED = "rejected"


class ReviewAction(str, Enum):
    """Enumeration of user actions that drive review state transitions.

    ``SCHEDULE`` and ``PUBLISH`` are split so approve-without-publish
    becomes possible (CONTEXT.md 'Approve-without-publish (locked by
    success criterion #3)'). ``ATTACH_MEDIA`` covers the non-transition
    media metadata updates that today bypass any service.
    """

    APPROVE = "approve"
    DECLINE = "decline"
    NEEDS_WORK = "needs_work"
    SCHEDULE = "schedule"
    PUBLISH = "publish"
    ATTACH_MEDIA = "attach_media"


VALID_TRANSITIONS: Dict[ReviewStatus, frozenset] = {
    ReviewStatus.PENDING_REVIEW: frozenset(
        {ReviewAction.APPROVE, ReviewAction.DECLINE, ReviewAction.NEEDS_WORK}
    ),
    ReviewStatus.APPROVED: frozenset({ReviewAction.SCHEDULE, ReviewAction.DECLINE}),
    ReviewStatus.NEEDS_WORK: frozenset({ReviewAction.APPROVE, ReviewAction.DECLINE}),
    ReviewStatus.SCHEDULED: frozenset({ReviewAction.PUBLISH}),
    ReviewStatus.PUBLISHED: frozenset(),
    ReviewStatus.DECLINED: frozenset(),
    ReviewStatus.REJECTED: frozenset(),
}


@dataclass
class FeedbackHistoryEntry:
    """Typed wrapper for a single feedback_history entry.

    Shape-compatible with ``data.models.FeedbackRecord`` -- the same six
    canonical keys round-trip through both classes. Unknown keys are
    preserved in ``_extras`` so historical records with additional fields
    are not silently stripped on read.
    """

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    from_status: str = ""
    to_status: str = ""
    feedback: str = ""
    learning_tags: List[str] = field(default_factory=list)
    auto_fix_applied: bool = False
    _extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return the six canonical keys merged over any preserved extras."""
        result = dict(self._extras)
        result["timestamp"] = self.timestamp
        result["from_status"] = self.from_status
        result["to_status"] = self.to_status
        result["feedback"] = self.feedback
        result["learning_tags"] = list(self.learning_tags)
        result["auto_fix_applied"] = self.auto_fix_applied
        return result

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "FeedbackHistoryEntry":
        """Project a raw history dict into the typed wrapper.

        Tolerates ``None`` and missing keys. Pops the six canonical keys
        and stores any remainder in ``_extras`` so the round-trip is
        lossless even when storage carries additional fields.
        """
        if not data:
            return cls()
        raw = dict(data)
        timestamp = raw.pop("timestamp", datetime.now(timezone.utc).isoformat())
        from_status = raw.pop("from_status", "")
        to_status = raw.pop("to_status", "")
        feedback = raw.pop("feedback", "")
        learning_tags = list(raw.pop("learning_tags", []))
        auto_fix_applied = raw.pop("auto_fix_applied", False)
        return cls(
            timestamp=timestamp,
            from_status=from_status,
            to_status=to_status,
            feedback=feedback,
            learning_tags=learning_tags,
            auto_fix_applied=auto_fix_applied,
            _extras=raw,
        )


@dataclass
class ReviewRecord:
    """Typed projection over a raw review-record dict.

    Per AGENTS.md gotcha #2 the wrapper projects over the dict -- it never
    replaces storage. ``raw`` is kept verbatim and ``to_dict()`` returns it
    unchanged so read-write cycles through the wrapper are identity.
    Derived read-only properties (``project_id``, ``post_data``,
    ``feedback_history`` ...) read through to ``raw.get(...)`` so the
    wrapper never lies about what is in storage.
    """

    review_id: str
    status: ReviewStatus
    raw: dict

    @property
    def project_id(self) -> Optional[str]:
        """Return the raw project_id if present, else None."""
        return self.raw.get("project_id")

    @property
    def post_data(self) -> dict:
        """Return the raw post_data dict (empty dict when absent)."""
        return self.raw.get("post_data") or {}

    @property
    def feedback_history(self) -> List[FeedbackHistoryEntry]:
        """Project the raw feedback_history list into typed entries."""
        return [
            FeedbackHistoryEntry.from_dict(entry)
            for entry in (self.raw.get("feedback_history") or [])
        ]

    @property
    def channel(self) -> Optional[str]:
        """Return the raw channel if present, else None."""
        return self.raw.get("channel")

    @property
    def created_at(self) -> Optional[str]:
        """Return the raw created_at if present, else None."""
        return self.raw.get("created_at")

    @property
    def approved_at(self) -> Optional[str]:
        """Return the raw approved_at if present, else None."""
        return self.raw.get("approved_at")

    @property
    def scheduled_at(self) -> Optional[str]:
        """Return the raw scheduled_at if present, else None."""
        return self.raw.get("scheduled_at")

    @property
    def published_at(self) -> Optional[str]:
        """Return the raw published_at if present, else None."""
        return self.raw.get("published_at")

    @property
    def draft_id(self) -> Optional[str]:
        """Return the raw draft_id if present, else None."""
        return self.raw.get("draft_id")

    @property
    def draft_url(self) -> Optional[str]:
        """Return the raw draft_url if present, else None."""
        return self.raw.get("draft_url")

    @property
    def scheduling_error(self) -> Optional[str]:
        """Return the raw scheduling_error if present, else None."""
        return self.raw.get("scheduling_error")

    @property
    def media(self) -> Optional[dict]:
        """Return the raw media dict if present, else None."""
        return self.raw.get("media")

    def to_dict(self) -> dict:
        """Return the underlying raw dict (the wrapper is a projection)."""
        return self.raw

    @classmethod
    def from_dict(cls, raw: dict) -> "ReviewRecord":
        """Project a raw review-record dict into the typed wrapper.

        Defensively reads ``review_id`` and ``status``; an unknown status
        string falls back to ``ReviewStatus.PENDING_REVIEW`` rather than
        raising, so legacy records with arbitrary status values survive a
        read-write cycle unchanged.
        """
        raw_review_id = (raw or {}).get("review_id", "")
        raw_status = (raw or {}).get("status", "pending_review")
        try:
            status = ReviewStatus(raw_status)
        except ValueError:
            status = ReviewStatus.PENDING_REVIEW
        return cls(review_id=raw_review_id, status=status, raw=raw or {})
