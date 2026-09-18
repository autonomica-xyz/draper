"""Plan 04-03 Task 1: services.job_types payload + result registry contracts.

Pins the typed-envelope surface (ARCH-05 D-4):

* 8 Pydantic payload models registered in ``KIND_PAYLOAD_REGISTRY``
* 8 Pydantic result models registered in ``KIND_RESULT_REGISTRY``
* ``validate_payload(kind, payload)`` accepts valid payloads, rejects
  malformed ones with ``pydantic.ValidationError``, and raises ``KeyError``
  for unknown kinds.

Plan-checker WARNING #4 backward-compat contracts live in
``TestEnqueueBackwardCompat`` (added in Task 2 alongside the
``JobQueueService.enqueue`` validation hook).
"""

from __future__ import annotations

from typing import Any

import pytest
import pydantic

from services.job_types import (
    ALL_JOB_KINDS,
    FixContentPayload,
    GenerateContentPayload,
    GenerateCarouselPayload,
    GenerateVisualPayload,
    KIND_PAYLOAD_REGISTRY,
    KIND_RESULT_REGISTRY,
    MineIdeasPayload,
    PublishScheduledPostPayload,
    SyncAnalyticsPayload,
    SyncProviderAnalyticsPayload,
    validate_payload,
)


class TestValidatePayloadContracts:
    def test_validate_generate_content_returns_payload_with_api_channel_default(self):
        result = validate_payload("generate_content", {"project_id": "p1", "count": 5})
        assert isinstance(result, GenerateContentPayload)
        assert result.count == 5
        assert result.platform is None
        assert result.content_type is None
        assert result.channel == "API"

    def test_validate_generate_content_rejects_oversized_count(self):
        with pytest.raises(pydantic.ValidationError):
            validate_payload("generate_content", {"count": 999})

    def test_validate_generate_content_requires_project_id(self):
        with pytest.raises(pydantic.ValidationError):
            validate_payload("generate_content", {})

    def test_validate_fix_content_returns_payload(self):
        result = validate_payload(
            "fix_content",
            {"review_id": "r1", "feedback": "fix", "project_id": "p1"},
        )
        assert isinstance(result, FixContentPayload)
        assert result.review_id == "r1"
        assert result.feedback == "fix"
        assert result.project_id == "p1"

    def test_validate_generate_visual_accepts_valid_and_rejects_empty_prompt(self):
        result = validate_payload(
            "generate_visual", {"prompt": "p", "platform": "twitter"}
        )
        assert isinstance(result, GenerateVisualPayload)
        assert result.prompt == "p"
        assert result.platform == "twitter"
        with pytest.raises(pydantic.ValidationError):
            validate_payload("generate_visual", {"prompt": "", "platform": "twitter"})

    def test_validate_generate_carousel_rejects_out_of_range_num_cards(self):
        result = validate_payload(
            "generate_carousel", {"content": "c", "num_cards": 5}
        )
        assert isinstance(result, GenerateCarouselPayload)
        with pytest.raises(pydantic.ValidationError):
            validate_payload("generate_carousel", {"content": "c", "num_cards": 0})
        with pytest.raises(pydantic.ValidationError):
            validate_payload("generate_carousel", {"content": "c", "num_cards": 13})

    def test_validate_mine_ideas_requires_project_id(self):
        result = validate_payload("mine_ideas", {"project_id": "p1"})
        assert isinstance(result, MineIdeasPayload)
        assert result.project_id == "p1"
        with pytest.raises(pydantic.ValidationError):
            validate_payload("mine_ideas", {})

    def test_validate_sync_provider_analytics_accepts_empty_payload(self):
        result = validate_payload("sync_provider_analytics", {})
        assert isinstance(result, SyncProviderAnalyticsPayload)
        assert result.project_id is None
        assert result.provider is None

    def test_validate_publish_scheduled_post_requires_post_id(self):
        result = validate_payload(
            "publish_scheduled_post", {"post_id": "po1"}
        )
        assert isinstance(result, PublishScheduledPostPayload)
        assert result.post_id == "po1"
        with pytest.raises(pydantic.ValidationError):
            validate_payload("publish_scheduled_post", {})

    def test_validate_sync_analytics_accepts_empty_payload(self):
        result = validate_payload("sync_analytics", {})
        assert isinstance(result, SyncAnalyticsPayload)
        assert result.project_id is None

    def test_validate_unknown_kind_raises_key_error(self):
        with pytest.raises(KeyError):
            validate_payload("unknown_kind", {})


class TestRegistries:
    EXPECTED_KINDS = {
        "generate_content",
        "fix_content",
        "generate_visual",
        "generate_carousel",
        "mine_ideas",
        "sync_provider_analytics",
        "publish_scheduled_post",
        "sync_analytics",
        "nostr_publish_request",
    }

    def test_payload_registry_keys_cover_expected_kinds(self):
        assert set(KIND_PAYLOAD_REGISTRY.keys()) == self.EXPECTED_KINDS

    def test_result_registry_keys_match_payload_registry(self):
        assert set(KIND_RESULT_REGISTRY.keys()) == set(
            KIND_PAYLOAD_REGISTRY.keys()
        )

    def test_all_job_kinds_constant_matches_payload_registry(self):
        assert ALL_JOB_KINDS == frozenset(KIND_PAYLOAD_REGISTRY.keys())
        assert len(ALL_JOB_KINDS) == 9

    def test_payload_registry_generate_content_class_name(self):
        assert (
            KIND_PAYLOAD_REGISTRY["generate_content"].__name__
            == "GenerateContentPayload"
        )


class TestCallerProvidedValuesRespected:
    def test_validate_generate_content_preserves_scheduler_channel(self):
        result = validate_payload(
            "generate_content",
            {"project_id": "p1", "count": 5, "channel": "SCHEDULER"},
        )
        assert result.channel == "SCHEDULER"


class TestJobQueueEnqueueValidation:
    """Plan 04-03 Task 2: JobQueueService.enqueue validates payloads at enqueue."""

    def test_enqueue_generate_content_succeeds_with_valid_payload(self, seeded_store):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        record = queue.enqueue(
            "generate_content",
            payload={"project_id": "fixture-proj-001", "count": 5},
            project_id="fixture-proj-001",
        )
        assert isinstance(record, dict)
        assert "job_id" in record
        assert record["kind"] == "generate_content"

    def test_enqueue_rejects_malformed_payload_with_validation_error(self, seeded_store):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        with pytest.raises(pydantic.ValidationError):
            queue.enqueue(
                "generate_content",
                payload={"count": 999},
                project_id="fixture-proj-001",
            )

    def test_enqueue_rejects_unknown_kind_with_key_error(self, seeded_store):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        with pytest.raises(KeyError):
            queue.enqueue("unknown_kind", payload={})

    def test_enqueue_sync_analytics_accepts_empty_payload(self, seeded_store):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        record = queue.enqueue("sync_analytics", payload={}, project_id=None)
        assert record["kind"] == "sync_analytics"

    def test_enqueue_publish_scheduled_post_accepts_post_id(self, seeded_store):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        record = queue.enqueue(
            "publish_scheduled_post",
            payload={"post_id": "po1"},
            project_id="fixture-proj-001",
        )
        assert record["kind"] == "publish_scheduled_post"

    def test_enqueued_payload_round_trips_through_validate_payload(self, seeded_store):
        from services.job_queue import JobQueueService

        queue = JobQueueService(seeded_store)
        record = queue.enqueue(
            "generate_content",
            payload={"project_id": "fixture-proj-001", "count": 5},
            project_id="fixture-proj-001",
        )
        persisted_payload = record.get("payload") or {}
        re_validated = validate_payload("generate_content", persisted_payload)
        assert re_validated.project_id == "fixture-proj-001"
        assert re_validated.count == 5


class TestEnqueueBackwardCompat:
    """Plan-checker WARNING #4 fix: exercise every existing enqueue call site
    against a real ``AppContainer`` + ``TestClient`` so backward-compat is
    enforced by test, not by reasoning.

    Each test asserts the route returns its normal envelope AND a job of the
    expected kind lands in the queue (i.e. ``enqueue`` validation did not
    raise ``pydantic.ValidationError`` for that call site's payload shape).
    """

    @pytest.fixture
    def container(self, project_data_dir: Any, monkeypatch):
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
    def app(self, container):
        from dashboard.app_factory import build_app

        return build_app(container)

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient

        return TestClient(app, raise_server_exceptions=True)

    @staticmethod
    def _queued_kinds(container) -> set:
        return {job.get("kind") for job in container.job_queue.list(status="queued")}

    def test_generate_content_route_payload_passes_validation(
        self, container, client, fixture_project
    ):
        token = container.csrf.current_token()
        project_id = fixture_project["project_id"]

        resp = client.post(
            "/api/generate",
            json={"async": True, "count": 1, "project_id": project_id},
            headers={"x-csrf-token": token},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body.get("async") is True
        assert "job_id" in body
        assert "generate_content" in self._queued_kinds(container)

    def test_publish_scheduled_post_route_payload_passes_validation(
        self, container, client, fixture_project
    ):
        token = container.csrf.current_token()
        project_id = fixture_project["project_id"]
        record = container.feedback_manager.add_for_review(
            {
                "platform": "twitter",
                "content_type": "tweet",
                "pillar": "growth",
                "hook_type": "question",
                "content": "schedule me",
                "project_id": project_id,
            }
        )
        review_id = record["review_id"]

        resp = client.post(
            f"/schedule/{review_id}",
            data={
                "scheduled_date": "2026-07-06",
                "scheduled_time": "09:00",
                "feedback": "",
            },
            headers={"x-csrf-token": token},
            follow_redirects=False,
        )

        assert resp.status_code == 303, f"body: {resp.text}"
        assert "publish_scheduled_post" in self._queued_kinds(container)

    def test_apply_auto_fix_payload_passes_validation(self, container, fixture_project):
        from data.review_models import ReviewAction

        project_id = fixture_project["project_id"]
        record = container.feedback_manager.add_for_review(
            {
                "platform": "twitter",
                "content_type": "tweet",
                "pillar": "growth",
                "hook_type": "question",
                "content": "fix me",
                "project_id": project_id,
            }
        )
        review_id = record["review_id"]

        container.review_workflow.transition(
            review_id, ReviewAction.NEEDS_WORK, feedback="make it punchier"
        )

        job = container.review_workflow.apply_auto_fix(
            review_id, feedback="make it punchier", job_queue=container.job_queue
        )

        assert job["kind"] == "fix_content"
        assert job["payload"]["review_id"] == review_id
        assert job["payload"]["feedback"] == "make it punchier"
        assert job["payload"]["project_id"] == project_id
        assert "fix_content" in self._queued_kinds(container)

    def test_scheduler_producer_payload_passes_validation(
        self, container, fixture_project
    ):
        from datetime import datetime

        from services.scheduler_producer import SchedulerProducer

        project_id = fixture_project["project_id"]
        record = container.store.get_project_record(project_id) or {}
        record["generation_schedule"] = {
            "frequency": "daily",
            "times": ["09:00"],
            "posts_per_batch": 2,
        }
        container.store.save_project_record(record)

        producer = SchedulerProducer(container)
        result = producer.tick(now=datetime(2026, 7, 5, 9, 5))

        assert result["enqueued"] == [project_id]
        assert "generate_content" in self._queued_kinds(container)

    def test_sync_analytics_route_payload_passes_validation(self, container, client):
        token = container.csrf.current_token()

        resp = client.post(
            "/api/jobs/sync-analytics",
            json={},
            headers={"x-csrf-token": token},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "sync_analytics" in self._queued_kinds(container)
