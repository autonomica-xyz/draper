"""Unit tests for feedback-honoring auto-fix contracts.

Pins the fix/autofix-honor-needs-work-feedback branch contracts:

- ``_build_fix_prompt`` treats FEEDBACK as the source of truth (verbatim
  inclusion, hard-constraint language, structure preservation, brand voice
  secondary to fact/rewrite constraints).
- ``_generate_explanation`` never emits a canned "improved hook" claim unless
  the feedback itself is about the hook/opening; explanations are derived from
  the feedback.
- Concrete feedback (rewrites, slide/report fact fixes, DO NOT claims) plus no
  LLM (or an LLM failure) raises ``AutoFixSkipped`` instead of silently
  substituting a rule-based hook hack.
- Soft/vague feedback still gets the rule-based fallback.
- ``JobRunner._fix_content`` leaves the review in ``needs_work`` and records
  the skip instead of marking ``pending_review`` with fabricated content.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from learning.auto_fix import (
    AutoFixEngine,
    AutoFixSkipped,
    is_concrete_feedback,
)
from services.review_workflow_service import ReviewWorkflowService

FEEDBACK_FACT_REWRITE = (
    "Slide 3 states 40% growth but the Q3 report says 12%. "
    "Rewrite the slide to match the report. Do not claim 40% anywhere."
)


def _make_engine(llm_available: bool = False, llm_generator=None) -> AutoFixEngine:
    """Build an AutoFixEngine without running the generator-importing __init__."""
    engine = AutoFixEngine.__new__(AutoFixEngine)
    engine.base_dir = Path(".")
    engine.llm_available = llm_available
    engine.llm_generator = llm_generator
    return engine


def _make_post(**overrides):
    post = {
        "platform": "linkedin",
        "content_type": "carousel",
        "content": "Big wins ahead\nSlide 1: intro\nSlide 3: 40% growth",
        "project_id": "proj-test",
    }
    post.update(overrides)
    return post


@pytest.fixture
def stub_project_manager(monkeypatch):
    """Replace ProjectManager so fix_content needs no real project store."""

    class _StubProjectManager:
        def __init__(self, *args, **kwargs):
            pass

        def get_project(self, project_id):
            return {"id": project_id}

        def get_brand_voice(self, project_id):
            return "Be plain and honest."

    monkeypatch.setattr("projects.manager.ProjectManager", _StubProjectManager)


class TestIsConcreteFeedback:
    def test_keyword_matches_are_concrete(self):
        assert is_concrete_feedback("Rewrite slide 3 to match the report")
        assert is_concrete_feedback("Do not claim 40% growth")
        assert is_concrete_feedback("This fact is incorrect, ground it in the report")
        assert is_concrete_feedback("The numbers are wrong")
        assert is_concrete_feedback("Keep the carousel slides as-is, fix the facts")
        assert is_concrete_feedback("Must not mention competitors")

    def test_long_detailed_feedback_is_concrete_without_keywords(self):
        detailed = (
            "Please go through each section carefully before changing anything. "
            "The second paragraph drifts from the approved messaging and needs "
            "to be brought back in line with the pilot program positioning. "
            "The closing line should reference the pilot program explicitly."
        )
        assert is_concrete_feedback(detailed)

    def test_short_vague_feedback_is_not_concrete(self):
        assert not is_concrete_feedback("make it punchier")
        assert not is_concrete_feedback("too generic, liven it up")
        assert not is_concrete_feedback("")
        assert not is_concrete_feedback(None)

    def test_word_boundaries_prevent_substring_false_positives(self):
        # "fact" inside "factor" must not count.
        assert not is_concrete_feedback("talk about the X factor more")


class TestBuildFixPrompt:
    def test_prompt_contains_feedback_verbatim_and_hard_constraint_language(self):
        engine = _make_engine()
        feedback = (
            "VERBATIM-MARKER-7f3a: rewrite slide 2 to ground the claim in the "
            "annual report. Do not invent numbers."
        )
        prompt = engine._build_fix_prompt(
            "original content", feedback, "linkedin", "carousel", "Brand voice text"
        )

        assert feedback in prompt, "feedback must be included verbatim"
        assert "SOURCE OF TRUTH" in prompt
        assert "HARD CONSTRAINT" in prompt
        assert "OBEY THE FEEDBACK EXACTLY" in prompt

    def test_prompt_forbids_generic_hook_substitution(self):
        engine = _make_engine()
        prompt = engine._build_fix_prompt("original", "fix the facts", "twitter", "post", "")
        assert "Do NOT substitute a generic engagement/hook rewrite" in prompt

    def test_prompt_preserves_structure_and_makes_brand_voice_secondary(self):
        engine = _make_engine()
        prompt = engine._build_fix_prompt(
            "original",
            "fix slide facts",
            "linkedin",
            "carousel",
            "Brand voice text",
        )
        assert "Preserve the existing structure" in prompt
        assert "SECONDARY" in prompt
        # Feedback (source of truth) appears before the brand voice block.
        assert prompt.index("SOURCE OF TRUTH") < prompt.index("BRAND VOICE GUIDELINES")


class TestGenerateExplanation:
    def test_no_hook_claim_for_fact_rewrite_feedback_even_when_first_line_changes(self):
        engine = _make_engine()
        original = "Big wins ahead\nSlide 3: 40% growth"
        fixed = "Q3 results: steady and real\nSlide 3: 12% growth"

        explanation = engine._generate_explanation(original, fixed, FEEDBACK_FACT_REWRITE)

        lowered = explanation.lower()
        assert "hook" not in lowered, explanation
        assert "Improved hook" not in explanation
        assert "better engagement" not in explanation
        # Explanation is anchored in the feedback itself.
        assert "Addressed feedback" in explanation
        assert "Slide 3 states 40% growth" in explanation

    def test_hook_feedback_may_mention_hook_in_explanation(self):
        engine = _make_engine()
        original = "Plain old opening\nbody text"
        fixed = "What if your data is lying to you?\nbody text"

        explanation = engine._generate_explanation(original, fixed, "make the hook stronger")

        assert "hook" in explanation.lower()
        assert "Addressed feedback: make the hook stronger" in explanation

    def test_empty_feedback_gets_neutral_explanation(self):
        engine = _make_engine()
        explanation = engine._generate_explanation("a", "a", "")
        assert explanation == "Applied refinements based on feedback"


class TestFixContentSkipPath:
    @pytest.mark.asyncio
    async def test_concrete_feedback_no_llm_raises_autofix_skipped(self, stub_project_manager):
        engine = _make_engine(llm_available=False)

        with pytest.raises(AutoFixSkipped) as exc_info:
            await engine.fix_content(_make_post(), FEEDBACK_FACT_REWRITE, "proj-test")

        assert exc_info.value.reason == "llm_unavailable_concrete_feedback"

    @pytest.mark.asyncio
    async def test_concrete_feedback_llm_failure_raises_autofix_skipped(self, stub_project_manager):
        llm = MagicMock()
        llm.generate_text = MagicMock(side_effect=RuntimeError("API down"))
        engine = _make_engine(llm_available=True, llm_generator=llm)

        with pytest.raises(AutoFixSkipped) as exc_info:
            await engine.fix_content(_make_post(), FEEDBACK_FACT_REWRITE, "proj-test")

        assert exc_info.value.reason == "llm_unavailable_concrete_feedback"
        assert "API down" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_soft_feedback_still_gets_rule_based_fallback(self, stub_project_manager):
        engine = _make_engine(llm_available=False)

        result = await engine.fix_content(
            _make_post(content="Strong opening line\nbody"), "make the hook better", "proj-test"
        )

        assert "content" in result and "explanation" in result
        assert result["content"].startswith("Strong opening line?")
        assert "hook" in result["explanation"].lower()

    @pytest.mark.asyncio
    async def test_explanation_computed_against_cleaned_content(self, stub_project_manager):
        llm = MagicMock()
        llm.generate_text = MagicMock(
            return_value="Platform: linkedin\nQ3 results: steady and real\nSlide 3: 12% growth"
        )
        engine = _make_engine(llm_available=True, llm_generator=llm)

        result = await engine.fix_content(_make_post(), FEEDBACK_FACT_REWRITE, "proj-test")

        assert result["content"].startswith("Q3 results")
        assert "Platform:" not in result["content"]


class TestJobRunnerFixContentSkip:
    def _runner_with_review(self, seeded_store, record):
        from services.job_queue import JobQueueService
        from services.job_runner import JobRunner

        queue = JobQueueService(seeded_store)
        review_workflow = MagicMock()
        review_workflow.feedback_manager._load_review_record.return_value = record
        review_workflow.complete_auto_fix = MagicMock()
        review_workflow.fail_auto_fix = MagicMock()
        runner = JobRunner(queue=queue, review_workflow=review_workflow)
        return runner, review_workflow

    def _execute_fix(self, runner):
        return runner.execute(
            {
                "kind": "fix_content",
                "job_id": "job-fix-1",
                "payload": {
                    "review_id": "live-review",
                    "feedback": FEEDBACK_FACT_REWRITE,
                    "project_id": "fixture-proj-001",
                },
                "project_id": "fixture-proj-001",
            }
        )

    def test_autofix_skipped_leaves_review_alone_and_records_skip(self, seeded_store, monkeypatch):
        record = {
            "review_id": "live-review",
            "status": "needs_work",
            "post_data": {"platform": "twitter", "content": "original"},
            "project_id": "fixture-proj-001",
        }
        runner, review_workflow = self._runner_with_review(seeded_store, record)

        autofix_instance = MagicMock()
        autofix_instance.fix_content = AsyncMock(
            side_effect=AutoFixSkipped(
                reason="llm_unavailable_concrete_feedback",
                message="no llm for concrete feedback",
            )
        )
        monkeypatch.setattr(
            "learning.auto_fix.AutoFixEngine",
            MagicMock(return_value=autofix_instance),
        )

        result = self._execute_fix(runner)

        assert result["skipped"] is True
        assert result["reason"] == "llm_unavailable_concrete_feedback"
        review_workflow.complete_auto_fix.assert_not_called()
        review_workflow.fail_auto_fix.assert_called_once_with(
            "live-review",
            reason="llm_unavailable_concrete_feedback",
            error="no llm for concrete feedback",
        )

    def test_structured_skip_result_is_handled_like_raised_skip(self, seeded_store, monkeypatch):
        record = {
            "review_id": "live-review",
            "status": "needs_work",
            "post_data": {"platform": "twitter", "content": "original"},
            "project_id": "fixture-proj-001",
        }
        runner, review_workflow = self._runner_with_review(seeded_store, record)

        autofix_instance = MagicMock()
        autofix_instance.fix_content = AsyncMock(
            return_value={
                "skipped": True,
                "reason": "llm_unavailable_concrete_feedback",
            }
        )
        monkeypatch.setattr(
            "learning.auto_fix.AutoFixEngine",
            MagicMock(return_value=autofix_instance),
        )

        result = self._execute_fix(runner)

        assert result["skipped"] is True
        review_workflow.complete_auto_fix.assert_not_called()
        review_workflow.fail_auto_fix.assert_called_once()


class TestEndToEndSkipLeavesNeedsWork:
    def test_skip_keeps_needs_work_and_does_not_fabricate_content(
        self, tmp_path, seeded_store, monkeypatch
    ):
        from data.review_models import ReviewAction
        from feedback.manager import FeedbackManager
        from services.job_queue import JobQueueService
        from services.job_runner import JobRunner
        from services.project_context import ProjectContextService

        fm = FeedbackManager(data_dir=str(tmp_path))
        record = fm.add_for_review(_make_post(project_id="fixture-proj-001"))
        review_id = record["review_id"]

        service = ReviewWorkflowService(fm, ProjectContextService(MagicMock()), MagicMock())
        service.transition(review_id, ReviewAction.NEEDS_WORK, feedback=FEEDBACK_FACT_REWRITE)
        service.apply_auto_fix(
            review_id, feedback=FEEDBACK_FACT_REWRITE, job_queue=JobQueueService(seeded_store)
        )
        seeded = fm._load_review_record(review_id)
        assert seeded["auto_fix_status"] == "queued"

        autofix_instance = MagicMock()
        autofix_instance.fix_content = AsyncMock(
            side_effect=AutoFixSkipped(
                reason="llm_unavailable_concrete_feedback",
                message="no llm",
            )
        )
        monkeypatch.setattr(
            "learning.auto_fix.AutoFixEngine",
            MagicMock(return_value=autofix_instance),
        )

        queue = JobQueueService(seeded_store)
        runner = JobRunner(queue=queue, review_workflow=service)
        result = runner.run_once(kinds=["fix_content"])

        assert result is not None and result["success"] is True
        completed = result["job"]
        assert completed["result"]["skipped"] is True

        stored = fm._load_review_record(review_id)
        assert stored["status"] == "needs_work", (
            "skip must leave the review in needs_work, not pending_review"
        )
        assert stored["post_data"]["content"] == _make_post()["content"], (
            "skip must not fabricate fixed content"
        )
        assert stored["auto_fix_status"] == "skipped"
        assert stored["auto_fix_skip_reason"] == "llm_unavailable_concrete_feedback"
