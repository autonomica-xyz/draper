"""Type-contract tests for data.review_models (plan 02-01).

These tests pin the typed review-domain vocabulary that plan 02-02
(``services/review_workflow_service.py``) and plan 02-03 (route handlers)
build on. They are pure dataclass round-trips -- no SQLiteStore or
FeedbackManager construction -- so they stay unit-fast.

The cross-compatibility test (``TestFeedbackHistoryEntryContract``)
proves ``FeedbackHistoryEntry`` reads dicts serialized by
``data.models.FeedbackRecord``, satisfying AGENTS.md gotcha #2 (typed
wrappers project over the existing raw-dict shape, never replace it).
"""

import pytest

from data.models import FeedbackRecord
from data.review_models import (
    VALID_TRANSITIONS,
    ReviewAction,
    ReviewRecord,
    ReviewStatus,
    FeedbackHistoryEntry,
)


class TestReviewStatusContract:
    """Pin ReviewStatus membership and value mapping."""

    def test_status_has_exactly_seven_members(self):
        """Six current statuses + REJECTED alias = seven total members."""
        members = {member.value for member in ReviewStatus}
        assert members == {
            "pending_review",
            "approved",
            "scheduled",
            "published",
            "needs_work",
            "declined",
            "rejected",
        }

    @pytest.mark.parametrize(
        "member,expected_value",
        [
            (ReviewStatus.PENDING_REVIEW, "pending_review"),
            (ReviewStatus.APPROVED, "approved"),
            (ReviewStatus.SCHEDULED, "scheduled"),
            (ReviewStatus.PUBLISHED, "published"),
            (ReviewStatus.NEEDS_WORK, "needs_work"),
            (ReviewStatus.DECLINED, "declined"),
            (ReviewStatus.REJECTED, "rejected"),
        ],
    )
    def test_member_value_is_lowercased_name(self, member, expected_value):
        """Each member's .value matches its lowercased name (REJECTED explicit alias)."""
        assert member.value == expected_value

    def test_status_is_string_comparable(self):
        """(str, Enum) inheritance makes members equality-comparable to raw strings."""
        assert ReviewStatus.PENDING_REVIEW == "pending_review"
        assert ReviewStatus.DECLINED == "declined"


class TestReviewActionContract:
    """Pin ReviewAction membership and value mapping."""

    def test_action_has_exactly_six_members(self):
        """APPROVE, DECLINE, NEEDS_WORK, SCHEDULE, PUBLISH, ATTACH_MEDIA."""
        members = {member.value for member in ReviewAction}
        assert members == {
            "approve",
            "decline",
            "needs_work",
            "schedule",
            "publish",
            "attach_media",
        }

    @pytest.mark.parametrize(
        "member,expected_value",
        [
            (ReviewAction.APPROVE, "approve"),
            (ReviewAction.DECLINE, "decline"),
            (ReviewAction.NEEDS_WORK, "needs_work"),
            (ReviewAction.SCHEDULE, "schedule"),
            (ReviewAction.PUBLISH, "publish"),
            (ReviewAction.ATTACH_MEDIA, "attach_media"),
        ],
    )
    def test_member_value_is_lowercased_name(self, member, expected_value):
        """Each member's .value matches its lowercased name."""
        assert member.value == expected_value


class TestValidTransitionsContract:
    """Pin VALID_TRANSITIONS state-machine map."""

    def test_pending_review_permits_approve_decline_needs_work(self):
        """PENDING_REVIEW is the entry state -- three forward actions permitted."""
        assert VALID_TRANSITIONS[ReviewStatus.PENDING_REVIEW] == frozenset(
            {ReviewAction.APPROVE, ReviewAction.DECLINE, ReviewAction.NEEDS_WORK}
        )

    def test_approved_permits_schedule_decline(self):
        """APPROVED splits publish out -- only SCHEDULE and DECLINE permitted."""
        assert VALID_TRANSITIONS[ReviewStatus.APPROVED] == frozenset(
            {ReviewAction.SCHEDULE, ReviewAction.DECLINE}
        )

    def test_needs_work_permits_approve_decline(self):
        """NEEDS_WORK can resolve to APPROVED or DECLINED."""
        assert VALID_TRANSITIONS[ReviewStatus.NEEDS_WORK] == frozenset(
            {ReviewAction.APPROVE, ReviewAction.DECLINE}
        )

    def test_scheduled_permits_publish_only(self):
        """SCHEDULED can only move forward to PUBLISHED."""
        assert VALID_TRANSITIONS[ReviewStatus.SCHEDULED] == frozenset({ReviewAction.PUBLISH})

    @pytest.mark.parametrize(
        "terminal",
        [ReviewStatus.PUBLISHED, ReviewStatus.DECLINED, ReviewStatus.REJECTED],
    )
    def test_terminal_states_have_empty_action_sets(self, terminal):
        """DECLINED, PUBLISHED, REJECTED are terminal -- no transitions out."""
        assert VALID_TRANSITIONS[terminal] == frozenset()

    def test_every_status_has_an_entry(self):
        """The map covers all ReviewStatus members (no silent KeyError)."""
        for status in ReviewStatus:
            assert status in VALID_TRANSITIONS
            assert isinstance(VALID_TRANSITIONS[status], frozenset)

    def test_transition_values_are_frozenset(self):
        """Map values must be frozenset (immutable, hashable) per the contract."""
        for status, actions in VALID_TRANSITIONS.items():
            assert isinstance(actions, frozenset), (
                f"VALID_TRANSITIONS[{status}] must be frozenset, got {type(actions).__name__}"
            )


class TestReviewRecordContract:
    """Pin ReviewRecord.from_dict / to_dict projection semantics."""

    def _representative_raw(self) -> dict:
        """Build a representative raw record covering all known keys plus an extra."""
        return {
            "review_id": "review-2026-07-05T10:00:00",
            "project_id": "fixture-project-id",
            "status": "pending_review",
            "channel": "dashboard",
            "post_data": {
                "platform": "twitter",
                "content": "hello world",
                "project_id": "fixture-project-id",
            },
            "feedback_history": [
                {
                    "timestamp": "2026-07-05T10:00:00",
                    "from_status": "",
                    "to_status": "pending_review",
                    "feedback": "",
                    "learning_tags": [],
                    "auto_fix_applied": False,
                }
            ],
            "feedback": None,
            "created_at": "2026-07-05T10:00:00",
            "approved_at": None,
            "scheduled_at": None,
            "published_at": None,
            "draft_id": None,
            "draft_url": None,
            "scheduling_error": None,
            "media": {"carousels": [], "infographic_url": None},
            "custom_extra_field": "preserve_me",
        }

    def test_from_dict_then_to_dict_is_identity(self):
        """Round-trip preserves every key, including arbitrary extras."""
        raw = self._representative_raw()

        record = ReviewRecord.from_dict(raw)

        assert record.to_dict() is raw
        assert record.to_dict() == raw

    def test_review_id_property_reads_through_raw(self):
        """review_id property reflects raw['review_id']."""
        raw = self._representative_raw()
        record = ReviewRecord.from_dict(raw)

        assert record.review_id == raw["review_id"]

    def test_status_property_returns_typed_enum(self):
        """status property returns the ReviewStatus member, not the raw string."""
        record = ReviewRecord.from_dict(self._representative_raw())

        assert record.status == ReviewStatus.PENDING_REVIEW
        assert isinstance(record.status, ReviewStatus)

    def test_project_id_property_reads_through_raw(self):
        """project_id property reflects raw['project_id']."""
        record = ReviewRecord.from_dict(self._representative_raw())

        assert record.project_id == "fixture-project-id"

    def test_post_data_property_reads_through_raw(self):
        """post_data property reflects raw['post_data']."""
        record = ReviewRecord.from_dict(self._representative_raw())

        assert record.post_data == {
            "platform": "twitter",
            "content": "hello world",
            "project_id": "fixture-project-id",
        }

    def test_post_data_property_returns_empty_dict_when_absent(self):
        """Missing post_data degrades to empty dict, not None."""
        record = ReviewRecord.from_dict({"review_id": "r", "status": "pending_review"})

        assert record.post_data == {}

    def test_feedback_history_returns_typed_entries(self):
        """feedback_history property returns List[FeedbackHistoryEntry]."""
        record = ReviewRecord.from_dict(self._representative_raw())

        history = record.feedback_history
        assert len(history) == 1
        assert isinstance(history[0], FeedbackHistoryEntry)
        assert history[0].to_status == "pending_review"

    def test_feedback_history_empty_when_absent(self):
        """Missing feedback_history degrades to empty list."""
        record = ReviewRecord.from_dict({"review_id": "r", "status": "pending_review"})

        assert record.feedback_history == []

    def test_optional_properties_read_through_raw(self):
        """channel/created_at/approved_at/draft_id/scheduling_error/media project raw."""
        raw = self._representative_raw()
        record = ReviewRecord.from_dict(raw)

        assert record.channel == raw["channel"]
        assert record.created_at == raw["created_at"]
        assert record.approved_at is None
        assert record.scheduled_at is None
        assert record.published_at is None
        assert record.draft_id is None
        assert record.draft_url is None
        assert record.scheduling_error is None
        assert record.media == raw["media"]

    def test_review_record_accepts_unknown_status_string(self):
        """Defensive contract: unknown status falls back to PENDING_REVIEW, no raise."""
        raw = {"review_id": "r1", "status": "totally-bogus-status", "post_data": {}}
        record = ReviewRecord.from_dict(raw)

        assert record.status == ReviewStatus.PENDING_REVIEW
        assert record.raw["status"] == "totally-bogus-status"

    def test_review_record_handles_empty_dict(self):
        """from_dict({}) yields an empty review_id and PENDING_REVIEW status."""
        record = ReviewRecord.from_dict({})

        assert record.review_id == ""
        assert record.status == ReviewStatus.PENDING_REVIEW

    def test_review_record_handles_legacy_rejected_status(self):
        """Legacy records with status='rejected' map to ReviewStatus.REJECTED."""
        record = ReviewRecord.from_dict({"review_id": "r", "status": "rejected"})

        assert record.status == ReviewStatus.REJECTED

    def test_review_record_preserves_arbitrary_extras_in_raw(self):
        """Custom keys ride through the wrapper unchanged (storage forward-compat)."""
        raw = {
            "review_id": "r1",
            "status": "pending_review",
            "future_field_a": {"nested": [1, 2, 3]},
            "future_field_b": "string-value",
        }
        record = ReviewRecord.from_dict(raw)

        assert record.to_dict() is raw
        assert record.to_dict()["future_field_a"] == {"nested": [1, 2, 3]}
        assert record.to_dict()["future_field_b"] == "string-value"


class TestFeedbackHistoryEntryContract:
    """Pin FeedbackHistoryEntry round-trip and shape compatibility."""

    def test_from_dict_then_to_dict_round_trip_preserves_canonical_keys(self):
        """Six canonical keys round-trip through from_dict/to_dict losslessly."""
        data = {
            "timestamp": "2026-07-05T10:00:00",
            "from_status": "pending_review",
            "to_status": "approved",
            "feedback": "looks great",
            "learning_tags": ["great_hook", "on_brand"],
            "auto_fix_applied": False,
        }

        out = FeedbackHistoryEntry.from_dict(data).to_dict()

        for key, expected in data.items():
            assert out[key] == expected, f"canonical key '{key}' not preserved"

    def test_from_dict_populates_defaults_for_missing_keys(self):
        """Empty input yields an entry with all six canonical keys defaulted."""
        out = FeedbackHistoryEntry.from_dict({}).to_dict()

        assert "timestamp" in out
        assert isinstance(out["timestamp"], str)
        assert out["from_status"] == ""
        assert out["to_status"] == ""
        assert out["feedback"] == ""
        assert out["learning_tags"] == []
        assert out["auto_fix_applied"] is False

    def test_from_dict_tolerates_none(self):
        """None input yields a defaulted entry, not a raise."""
        out = FeedbackHistoryEntry.from_dict(None).to_dict()

        assert out["from_status"] == ""
        assert out["learning_tags"] == []

    def test_unknown_keys_preserved_in_extras(self):
        """Unknown keys ride through _extras so historical records survive."""
        data = {
            "timestamp": "T",
            "from_status": "a",
            "to_status": "b",
            "feedback": "f",
            "learning_tags": [],
            "auto_fix_applied": True,
            "reviewer_id": "user-123",
            "source": "dashboard",
        }

        out = FeedbackHistoryEntry.from_dict(data).to_dict()

        assert out["reviewer_id"] == "user-123"
        assert out["source"] == "dashboard"
        for canonical_key in (
            "timestamp",
            "from_status",
            "to_status",
            "feedback",
            "learning_tags",
            "auto_fix_applied",
        ):
            assert canonical_key in out

    def test_learning_tags_returns_a_copy(self):
        """to_dict() returns a fresh list for learning_tags (no aliasing _extras)."""
        original = ["x", "y"]
        entry = FeedbackHistoryEntry(learning_tags=original)
        out = entry.to_dict()
        out["learning_tags"].append("z")

        assert "z" not in entry.learning_tags

    def test_cross_compatible_with_data_models_feedback_record(self):
        """Pin shape compatibility: FeedbackHistoryEntry reads FeedbackRecord dicts.

        Per AGENTS.md gotcha #2 -- the typed wrapper projects over the raw
        dict shape; serialized ``data.models.FeedbackRecord`` must remain
        readable through ``FeedbackHistoryEntry.from_dict``.
        """
        legacy = FeedbackRecord(
            timestamp="2026-07-05T10:00:00",
            from_status="pending_review",
            to_status="approved",
            feedback="ok",
            learning_tags=["great_hook"],
            auto_fix_applied=False,
        )

        projected = FeedbackHistoryEntry.from_dict(legacy.to_dict()).to_dict()

        for key in (
            "timestamp",
            "from_status",
            "to_status",
            "feedback",
            "learning_tags",
            "auto_fix_applied",
        ):
            assert projected[key] == legacy.to_dict()[key], (
                f"FeedbackHistoryEntry mismatch on '{key}' "
                f"when reading a FeedbackRecord-serialized dict"
            )
