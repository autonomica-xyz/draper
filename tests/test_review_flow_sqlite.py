"""Integration tests for the review lifecycle through FeedbackManager ↔ SQLiteStore.

Exercises the real FeedbackManager code path backed by SQLiteStore,
proving that status transitions, stats, project isolation, and
deprecation warnings all work correctly.
"""

import warnings

import pytest

from feedback.manager import FeedbackManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post(platform="twitter", **overrides):
    """Build a minimal post_data dict for add_for_review."""
    post = {
        "platform": platform,
        "content_type": "tweet",
        "pillar": "growth",
        "hook_type": "question",
        "content": "Sample content for testing.",
    }
    post.update(overrides)
    return post


def _project_dir(tmp_path, project_id):
    """Return a path shaped like data/projects/{project_id}/."""
    p = tmp_path / "projects" / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# 1. Full lifecycle: create → approve → schedule
# ---------------------------------------------------------------------------


class TestReviewLifecycle:
    """End-to-end status transitions through FeedbackManager."""

    def test_review_lifecycle(self, tmp_path):
        """Create a review, approve it, schedule it — verify each stage."""
        fm = FeedbackManager(data_dir=str(tmp_path))

        # --- Create ---
        record = fm.add_for_review(_make_post())
        review_id = record["review_id"]

        assert record["status"] == "pending_review"
        assert record["review_id"] == review_id

        pending = fm.get_pending_reviews()
        assert len(pending) == 1
        assert pending[0]["review_id"] == review_id
        assert pending[0]["status"] == "pending_review"

        # Verify single-record loader sees it
        loaded = fm._load_review_record(review_id)
        assert loaded is not None
        assert loaded["status"] == "pending_review"

        # --- Approve ---
        ok = fm.approve(review_id, feedback="Looks good")
        assert ok is True

        loaded = fm._load_review_record(review_id)
        assert loaded["status"] == "approved"
        assert loaded["feedback"] == "Looks good"
        assert "approved_at" in loaded

        approved = fm.get_approved()
        assert any(r["review_id"] == review_id for r in approved)

        # No longer in pending
        pending = fm.get_pending_reviews()
        assert not any(r["review_id"] == review_id for r in pending)

        # --- Schedule ---
        ok = fm.mark_scheduled(review_id, schedule_data={"slot": "2026-01-15T10:00:00"})
        assert ok is True

        loaded = fm._load_review_record(review_id)
        assert loaded["status"] == "scheduled"
        assert "scheduled_at" in loaded
        assert loaded["schedule_data"]["slot"] == "2026-01-15T10:00:00"

        scheduled = fm.get_scheduled()
        assert any(r["review_id"] == review_id for r in scheduled)


# ---------------------------------------------------------------------------
# 2. Reject path
# ---------------------------------------------------------------------------


class TestReviewReject:
    """Reject transitions and timestamp recording."""

    def test_review_reject(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))

        record = fm.add_for_review(_make_post())
        review_id = record["review_id"]

        ok = fm.reject(review_id, feedback="Not on brand")
        assert ok is True

        loaded = fm._load_review_record(review_id)
        assert loaded["status"] == "rejected"
        assert loaded["feedback"] == "Not on brand"
        assert "rejected_at" in loaded

        # Rejected item should not appear in pending, approved, or scheduled
        assert not any(r["review_id"] == review_id for r in fm.get_pending_reviews())
        assert not any(r["review_id"] == review_id for r in fm.get_approved())
        assert not any(r["review_id"] == review_id for r in fm.get_scheduled())


# ---------------------------------------------------------------------------
# 3. Stats accuracy
# ---------------------------------------------------------------------------


class TestStats:
    """Verify get_stats() counts match actual operations."""

    def test_stats_after_operations(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))

        # Create 4 reviews with different platforms
        r1 = fm.add_for_review(_make_post(platform="twitter"))
        r2 = fm.add_for_review(_make_post(platform="linkedin"))
        r3 = fm.add_for_review(_make_post(platform="twitter"))
        r4 = fm.add_for_review(_make_post(platform="nostr"))

        # Approve r1, reject r2, schedule r3, leave r4 pending
        fm.approve(r1["review_id"])
        fm.reject(r2["review_id"])
        fm.mark_scheduled(r3["review_id"])

        stats = fm.get_stats()

        assert stats["total"] == 4
        assert stats["pending"] == 1       # r4
        assert stats["approved"] == 1      # r1
        assert stats["rejected"] == 1      # r2
        assert stats["scheduled"] == 1     # r3

        # Platform breakdown (by_platform tracks pending/approved/scheduled/needs_work/declined,
        # but NOT rejected — rejected is only in the top-level counts)
        assert stats["by_platform"]["twitter"]["scheduled"] == 1
        assert stats["by_platform"]["nostr"]["pending"] == 1
        # LinkedIn review was rejected; the platform entry exists but only has the
        # statuses the stats code tracks (no "rejected" key in by_platform)
        assert "linkedin" in stats["by_platform"]


# ---------------------------------------------------------------------------
# 4. Deprecation warnings
# ---------------------------------------------------------------------------


class TestDeprecationWarnings:
    """FeedbackManager must warn when legacy reviews.json exists."""

    def test_deprecation_warning_when_reviews_json_exists(self, tmp_path):
        """A reviews.json file in data_dir should emit DeprecationWarning."""
        (tmp_path / "reviews.json").write_text("{}")

        with pytest.warns(DeprecationWarning, match="reviews.json is deprecated"):
            FeedbackManager(data_dir=str(tmp_path))

    def test_no_deprecation_warning_when_no_json(self, tmp_path):
        """No DeprecationWarning when reviews.json is absent."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            FeedbackManager(data_dir=str(tmp_path))

        deprecation = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation) == 0


# ---------------------------------------------------------------------------
# 5. Project-scoped isolation
# ---------------------------------------------------------------------------


class TestProjectIsolation:
    """Two FeedbackManagers with different project_ids must not see each
    other's reviews."""

    def test_project_scoped_reviews(self, tmp_path):
        dir_a = _project_dir(tmp_path, "proj-alpha")
        dir_b = _project_dir(tmp_path, "proj-beta")

        fm_a = FeedbackManager(data_dir=str(dir_a))
        fm_b = FeedbackManager(data_dir=str(dir_b))

        # Add a review in each project
        rec_a = fm_a.add_for_review(_make_post(platform="twitter"))
        rec_b = fm_b.add_for_review(_make_post(platform="linkedin"))

        # Each manager should see only its own reviews
        pending_a = fm_a.get_pending_reviews()
        pending_b = fm_b.get_pending_reviews()

        assert len(pending_a) == 1
        assert pending_a[0]["review_id"] == rec_a["review_id"]
        assert pending_a[0]["post_data"]["platform"] == "twitter"

        assert len(pending_b) == 1
        assert pending_b[0]["review_id"] == rec_b["review_id"]
        assert pending_b[0]["post_data"]["platform"] == "linkedin"

        # _load_review_record should be scoped too
        assert fm_a._load_review_record(rec_a["review_id"]) is not None
        assert fm_a._load_review_record(rec_b["review_id"]) is None
        assert fm_b._load_review_record(rec_b["review_id"]) is not None
        assert fm_b._load_review_record(rec_a["review_id"]) is None


# ---------------------------------------------------------------------------
# 6. Single-record load/save operations
# ---------------------------------------------------------------------------


class TestSingleRecordOperations:
    """Direct _load_review_record / _save_review_record round-trip."""

    def test_single_record_operations(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))

        record = fm.add_for_review(_make_post())
        review_id = record["review_id"]

        # Load the record back
        loaded = fm._load_review_record(review_id)
        assert loaded is not None
        assert loaded["status"] == "pending_review"

        # Mutate and save
        loaded["status"] = "approved"
        loaded["custom_field"] = "injected_value"
        fm._save_review_record(review_id, loaded)

        # Reload and verify persistence
        reloaded = fm._load_review_record(review_id)
        assert reloaded["status"] == "approved"
        assert reloaded["custom_field"] == "injected_value"

    def test_load_nonexistent_record(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        assert fm._load_review_record("nonexistent_id") is None

    def test_approve_nonexistent_returns_false(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        assert fm.approve("no_such_id") is False

    def test_reject_nonexistent_returns_false(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        assert fm.reject("no_such_id") is False

    def test_mark_scheduled_nonexistent_returns_false(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        assert fm.mark_scheduled("no_such_id") is False


# ---------------------------------------------------------------------------
# 7. Backwards-compatibility aliases
# ---------------------------------------------------------------------------


class TestCompatibilityAliases:
    """Verify alias methods delegate correctly."""

    def test_post_content_for_review_alias(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        record = fm.post_content_for_review(_make_post())
        assert record["status"] == "pending_review"

    def test_process_feedback_approve(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        rec = fm.add_for_review(_make_post())
        assert fm.process_feedback(rec["review_id"], "approve", "ok") is True
        assert fm._load_review_record(rec["review_id"])["status"] == "approved"

    def test_process_feedback_reject(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        rec = fm.add_for_review(_make_post())
        assert fm.process_feedback(rec["review_id"], "reject", "bad") is True
        assert fm._load_review_record(rec["review_id"])["status"] == "rejected"

    def test_process_feedback_schedule(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        rec = fm.add_for_review(_make_post())
        fm.approve(rec["review_id"])
        assert fm.process_feedback(rec["review_id"], "schedule", "done") is True
        assert fm._load_review_record(rec["review_id"])["status"] == "scheduled"

    def test_process_feedback_unknown_action(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        assert fm.process_feedback("any_id", "bogus") is False

    def test_content_feedback_manager_alias(self):
        """ContentFeedbackManager is a backwards-compatible alias."""
        from feedback.manager import ContentFeedbackManager
        assert ContentFeedbackManager is FeedbackManager
