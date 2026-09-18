"""Plan 04-03 Task 3: JobRunner dispatch contracts for the 4 new job kinds.

Each test exercises ``JobRunner.execute`` with a mocked integration service
and asserts the handler returns the typed result-envelope shape defined in
``services.job_types``.

Per Plan-checker WARNING #2: tests pin the EXACT return-key contract:

* ZAI ``generate_social_image`` returns a dict with ``url`` (NOT ``image_url``)
  — handler reads ``result.get("url")`` and re-exposes it as ``image_url``.
* Gamma ``generate_carousel`` returns a dict with ``generation_id`` (NOT
  ``carousel_id`` or ``id``) — handler reads ``result.get("generation_id")``
  and re-exposes it as ``carousel_id``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _runner_with_store(store, **overrides):
    from services.job_queue import JobQueueService
    from services.job_runner import JobRunner

    queue = JobQueueService(store)
    defaults = dict(
        queue=queue,
        generator=None,
        feedback_manager=None,
        analytics=None,
        project_manager=None,
        content_workflow=None,
        publishing_service=None,
        review_workflow=None,
    )
    defaults.update(overrides)
    return JobRunner(**defaults)


class _FakeProjectManager:
    def __init__(self, valid_ids):
        self._valid_ids = set(valid_ids)

    def get_project(self, project_id):
        if project_id in self._valid_ids:
            return {"project_id": project_id}
        return None


class TestGenerateVisualHandler:
    def test_generate_visual_calls_zai_and_returns_image_url(self, seeded_store):
        runner = _runner_with_store(seeded_store)

        async def _fake_generate_social_image(self, topic, platform, style):
            return {
                "success": True,
                "url": "https://example/i.png",
                "provider": "zai",
                "platform": platform,
                "topic": topic,
                "style": style,
            }

        with patch(
            "integrations.zai_image.ZAIImageGenerator.generate_social_image",
            new=_fake_generate_social_image,
        ), patch(
            "integrations.zai_image.ZAIImageGenerator.is_configured",
            return_value=True,
        ):
            result = runner.execute(
                {
                    "kind": "generate_visual",
                    "payload": {"prompt": "p", "platform": "twitter"},
                    "project_id": None,
                }
            )

        assert result["success"] is True
        assert result["image_url"] == "https://example/i.png"
        assert result["provider"] == "zai"

    def test_generate_visual_raises_when_not_configured(self, seeded_store):
        runner = _runner_with_store(seeded_store)

        with patch(
            "integrations.zai_image.ZAIImageGenerator.is_configured",
            return_value=False,
        ):
            with pytest.raises(ValueError, match="not configured"):
                runner.execute(
                    {"kind": "generate_visual", "payload": {"prompt": "p"}}
                )

    def test_generate_visual_with_empty_prompt_raises_value_error(self, seeded_store):
        runner = _runner_with_store(seeded_store)

        with pytest.raises(ValueError):
            runner.execute(
                {"kind": "generate_visual", "payload": {}, "project_id": "p1"}
            )


class TestGenerateCarouselHandler:
    def test_generate_carousel_calls_gamma_and_returns_carousel_id(self, seeded_store):
        runner = _runner_with_store(seeded_store)

        async def _fake_generate_carousel(
            self, content, title="", num_cards=5, platform="linkedin"
        ):
            return {
                "success": True,
                "gamma_url": "https://g/1",
                "export_url": "https://g/1.png",
                "generation_id": "gen_abc",
                "error": None,
            }

        with patch(
            "integrations.gamma_api.GammaAPIClient.generate_carousel",
            new=_fake_generate_carousel,
        ), patch(
            "integrations.gamma_api.GammaAPIClient.is_configured",
            return_value=True,
        ):
            result = runner.execute(
                {
                    "kind": "generate_carousel",
                    "payload": {"content": "c", "num_cards": 5},
                    "project_id": "p1",
                }
            )

        assert result["success"] is True
        assert result["carousel_id"] == "gen_abc"
        assert result["provider"] == "gamma"
        assert result["gamma_url"] == "https://g/1"

    def test_generate_carousel_raises_when_not_configured(
        self, seeded_store
    ):
        runner = _runner_with_store(seeded_store)

        with patch(
            "integrations.gamma_api.GammaAPIClient.is_configured",
            return_value=False,
        ):
            with pytest.raises(ValueError, match="not configured"):
                runner.execute(
                    {"kind": "generate_carousel", "payload": {"content": "c"}}
                )


class TestMineIdeasHandler:
    def test_mine_ideas_calls_idea_lab_and_returns_idea_ids(self, seeded_store):
        pm = _FakeProjectManager({"p1"})
        runner = _runner_with_store(seeded_store, project_manager=pm)

        def _fake_mine_ideas(self, project_id, source_material_id=None, max_ideas=5):
            return [{"idea_id": "ci_1"}, {"idea_id": "ci_2"}]

        with patch(
            "services.idea_lab.IdeaLabService.mine_ideas", new=_fake_mine_ideas
        ):
            result = runner.execute(
                {"kind": "mine_ideas", "payload": {"project_id": "p1"}}
            )

        assert result["success"] is True
        assert result["idea_ids"] == ["ci_1", "ci_2"]

    def test_mine_ideas_unknown_project_id_raises_value_error(self, seeded_store):
        pm = _FakeProjectManager({"p1"})
        runner = _runner_with_store(seeded_store, project_manager=pm)

        with pytest.raises(ValueError):
            runner.execute(
                {"kind": "mine_ideas", "payload": {"project_id": "does-not-exist"}}
            )


class TestSyncProviderAnalyticsHandler:
    def test_sync_provider_analytics_returns_synced_list(self, seeded_store):
        analytics = MagicMock()
        analytics.sync_all_platforms.return_value = {
            "synced_platforms": ["twitter", "linkedin"]
        }
        runner = _runner_with_store(seeded_store, analytics=analytics)

        result = runner.execute({"kind": "sync_provider_analytics", "payload": {}})

        assert result["success"] is True
        assert result["synced"] == ["twitter", "linkedin"]

    def test_sync_provider_analytics_handles_non_dict_result(self, seeded_store):
        analytics = MagicMock()
        analytics.sync_all_platforms.return_value = None
        runner = _runner_with_store(seeded_store, analytics=analytics)

        result = runner.execute({"kind": "sync_provider_analytics", "payload": {}})

        assert result["success"] is True
        assert result["synced"] == []


class TestUnknownKindRaises:
    def test_unknown_kind_raises_value_error_with_message(self, seeded_store):
        runner = _runner_with_store(seeded_store)

        with pytest.raises(ValueError, match="Unknown job kind"):
            runner.execute({"kind": "new_kind", "payload": {}})


class TestFixContentDeletedReviewShortCircuit:
    """WR-05: _fix_content must not invoke AutoFixEngine when the review
    was deleted between enqueue and worker pickup."""

    def test_deleted_review_returns_skipped_without_calling_autofix(
        self, seeded_store, monkeypatch
    ):
        from services.job_queue import JobQueueService
        from services.job_runner import JobRunner

        queue = JobQueueService(seeded_store)
        review_workflow = MagicMock()
        review_workflow.feedback_manager._load_review_record.return_value = None
        runner = JobRunner(queue=queue, review_workflow=review_workflow)

        autofix_instance = MagicMock()
        autofix_instance.fix_content = MagicMock()
        autofix_cls = MagicMock(return_value=autofix_instance)
        monkeypatch.setattr("learning.auto_fix.AutoFixEngine", autofix_cls)

        result = runner.execute(
            {
                "kind": "fix_content",
                "payload": {
                    "review_id": "deleted-review-id",
                    "feedback": "fix it",
                    "project_id": "fixture-proj-001",
                },
                "project_id": "fixture-proj-001",
            }
        )

        assert result["skipped"] is True
        assert result["reason"] == "review_deleted"
        autofix_cls.assert_not_called()

    def test_existing_review_proceeds_to_autofix(self, seeded_store, monkeypatch):
        from unittest.mock import AsyncMock

        from services.job_queue import JobQueueService
        from services.job_runner import JobRunner

        queue = JobQueueService(seeded_store)
        review_workflow = MagicMock()
        review_workflow.feedback_manager._load_review_record.return_value = {
            "review_id": "live-review",
            "status": "needs_work",
            "post_data": {"platform": "twitter", "content": "original"},
            "project_id": "fixture-proj-001",
        }
        review_workflow.complete_auto_fix = MagicMock()
        runner = JobRunner(queue=queue, review_workflow=review_workflow)

        autofix_instance = MagicMock()
        autofix_instance.fix_content = AsyncMock(
            return_value={"content": "fixed", "explanation": "exp"}
        )
        autofix_cls = MagicMock(return_value=autofix_instance)
        monkeypatch.setattr("learning.auto_fix.AutoFixEngine", autofix_cls)

        result = runner.execute(
            {
                "kind": "fix_content",
                "payload": {
                    "review_id": "live-review",
                    "feedback": "fix it",
                    "project_id": "fixture-proj-001",
                },
                "project_id": "fixture-proj-001",
            }
        )

        autofix_cls.assert_called_once()
        review_workflow.complete_auto_fix.assert_called_once()


class TestFailureCategorizationForIntegrationJobs:
    """WR-04: visual/carousel/ideas handlers must surface failures through
    fail_with_category rather than swallowing them as 'completed' jobs."""

    def test_generate_visual_not_configured_marks_job_failed_permanent(
        self, seeded_store
    ):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        runner = _runner_with_store(seeded_store, queue=queue)
        record = queue.enqueue(
            "generate_visual",
            payload={"prompt": "p"},
            project_id="fixture-proj-001",
        )
        job_id = record["job_id"]

        with patch(
            "integrations.zai_image.ZAIImageGenerator.is_configured",
            return_value=False,
        ):
            result = runner.run_once()

        assert result is not None
        assert result["success"] is False
        assert result["failure_category"] == "permanent"
        stored = queue.get(job_id)
        assert stored["status"] == "failed"
        assert stored["failure_category"] == "permanent"

    def test_generate_visual_transient_provider_error_retries(self, seeded_store):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        runner = _runner_with_store(seeded_store, queue=queue)
        record = queue.enqueue(
            "generate_visual",
            payload={"prompt": "p"},
            project_id="fixture-proj-001",
        )
        job_id = record["job_id"]

        async def _boom(self, topic, platform, style):
            raise ConnectionError("upstream timeout")

        with patch(
            "integrations.zai_image.ZAIImageGenerator.generate_social_image",
            new=_boom,
        ), patch(
            "integrations.zai_image.ZAIImageGenerator.is_configured",
            return_value=True,
        ):
            result = runner.run_once()

        assert result is not None
        assert result["success"] is False
        assert result["failure_category"] == "transient"
        stored = queue.get(job_id)
        assert stored["status"] == "queued"
        assert stored["failure_category"] == "transient"

    def test_generate_carousel_not_configured_marks_job_failed_permanent(
        self, seeded_store
    ):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        runner = _runner_with_store(seeded_store, queue=queue)
        record = queue.enqueue(
            "generate_carousel",
            payload={"content": "c"},
            project_id="fixture-proj-001",
        )
        job_id = record["job_id"]

        with patch(
            "integrations.gamma_api.GammaAPIClient.is_configured",
            return_value=False,
        ):
            result = runner.run_once()

        assert result is not None
        assert result["failure_category"] == "permanent"
        stored = queue.get(job_id)
        assert stored["status"] == "failed"
        assert stored["failure_category"] == "permanent"

    def test_mine_ideas_provider_failure_marks_job_failed(self, seeded_store):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        pm = _FakeProjectManager({"fixture-proj-001"})
        runner = _runner_with_store(seeded_store, queue=queue, project_manager=pm)
        record = queue.enqueue(
            "mine_ideas",
            payload={"project_id": "fixture-proj-001"},
            project_id="fixture-proj-001",
        )
        job_id = record["job_id"]

        def _boom(self, project_id, source_material_id=None, max_ideas=5):
            raise RuntimeError("LLM idea generation failed: connection reset")

        with patch("services.idea_lab.IdeaLabService.mine_ideas", new=_boom):
            result = runner.run_once()

        assert result is not None
        assert result["success"] is False
        stored = queue.get(job_id)
        assert stored["status"] in {"failed", "queued"}
