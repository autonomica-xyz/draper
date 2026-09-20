"""Pipeline must keep needs_work (autofix-skip) items visible with DTO fields.

After autofix skip, reviews stay in ``needs_work`` with ``auto_fix_status=skipped``.
They must remain in ``get_pending_reviews`` / ``get_content_to_evaluate`` so the
Pipeline UI can show an "Autofix skipped" banner instead of vanishing.
"""

from __future__ import annotations

from feedback.manager import FeedbackManager


def _make_post(platform="twitter", **overrides):
    post = {
        "platform": platform,
        "content_type": "tweet",
        "pillar": "growth",
        "hook_type": "question",
        "content": "Sample content for pipeline visibility.",
        "topic": "testing",
    }
    post.update(overrides)
    return post


class TestPendingReviewsIncludesNeedsWork:
    def test_needs_work_appears_in_pending_list(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        record = fm.add_for_review(_make_post())
        review_id = record["review_id"]

        loaded = fm._load_review_record(review_id)
        loaded["status"] = "needs_work"
        loaded["feedback"] = "Make the hook sharper"
        loaded["auto_fix_status"] = "skipped"
        loaded["auto_fix_skip_reason"] = "Concrete feedback requires LLM; none available"
        fm.store.save_review_record(loaded)

        pending = fm.get_pending_reviews()
        match = [r for r in pending if r["review_id"] == review_id]
        assert len(match) == 1
        assert match[0]["status"] == "needs_work"
        assert match[0]["auto_fix_status"] == "skipped"
        assert "Concrete feedback" in match[0]["auto_fix_skip_reason"]

    def test_declined_still_excluded(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        record = fm.add_for_review(_make_post())
        review_id = record["review_id"]
        assert fm.reject(review_id, feedback="No")

        pending_ids = {r["review_id"] for r in fm.get_pending_reviews()}
        assert review_id not in pending_ids

    def test_approved_without_scheduling_error_excluded(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        record = fm.add_for_review(_make_post())
        review_id = record["review_id"]
        assert fm.approve(review_id)

        pending_ids = {r["review_id"] for r in fm.get_pending_reviews()}
        assert review_id not in pending_ids


class TestContentToEvaluateDtoFields:
    def test_forwards_auto_fix_and_feedback_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)

        from dashboard.unified_dashboard import UnifiedDashboard

        dashboard = UnifiedDashboard(data_dir=str(tmp_path))
        fm = dashboard.feedback_manager
        record = fm.add_for_review(_make_post(project_id="proj-a"))
        review_id = record["review_id"]

        loaded = fm._load_review_record(review_id)
        loaded["status"] = "needs_work"
        loaded["feedback"] = "Tighten the CTA"
        loaded["auto_fix_status"] = "skipped"
        loaded["auto_fix_skip_reason"] = "No LLM available for concrete feedback"
        loaded["auto_fix_error"] = "AutoFixSkipped"
        loaded["scheduling_error"] = None
        fm.store.save_review_record(loaded)

        items = dashboard.get_content_to_evaluate(limit=20)
        match = [i for i in items if i["review_id"] == review_id]
        assert len(match) == 1
        card = match[0]
        assert card["status"] == "needs_work"
        assert card["feedback"] == "Tighten the CTA"
        assert card["auto_fix_status"] == "skipped"
        assert card["auto_fix_skip_reason"] == "No LLM available for concrete feedback"
        assert card["auto_fix_error"] == "AutoFixSkipped"
        assert "scheduling_error" in card
