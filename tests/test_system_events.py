"""Plan 05-01: system_events audit table contract tests.

Pins the v1 schema, append-only behavior, filter API, and per-category
emission from the five high-value-mutation flows (review, publish, job,
credential, settings). The credential no-leak regex is the security
contract for T-05-01-01: credential events record ONLY {provider:
<name>}; settings events record ONLY {keys: [...]} with no values.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest

from data.sqlite_store import SQLiteStore
from feedback.manager import FeedbackManager
from integrations.publishing_provider import (
    PublishErrorCode,
    PublishResult,
)
from services.job_queue import JobQueueService
from services.project_context import ProjectContextService
from services.project_service import ProjectService
from services.publishing_service import ProjectPublishingService
from services.review_workflow_service import ReviewWorkflowService
from services.retry_policy import FailureCategory
from services.secrets import ProjectSecretService


CREDENTIAL_LEAK_PATTERN = re.compile(r"api_key|secret|token|password", re.IGNORECASE)
SETTINGS_LEAK_PATTERN = re.compile(r"secret|token|password", re.IGNORECASE)


def _columns(conn, table: str) -> list:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _make_post(platform="twitter", project_id="proj-test", **overrides) -> Dict[str, Any]:
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


class _NullProjectManager:
    """Minimal project_manager stand-in that exposes .store."""

    def __init__(self, store=None):
        self.store = store
        self.data_dir = None

    def get_project_secrets(self, project_id):
        return {}

    def save_project_secrets(self, project_id, data):
        pass

    def verify_project_match(self, content_project_id, target_project_id):
        return True

    def get_provider_mapping(self, project_id):
        return {}

    def get_project_settings(self, project_id):
        return {}

    def list_projects(self):
        return []


class _StubProjectManager(_NullProjectManager):
    def get_provider_mapping(self, project_id):
        return {"twitter": "typefully"}

    def get_project_settings(self, project_id):
        return {
            "social_profiles": [
                {
                    "account_id": "typefully_1_twitter",
                    "platform": "twitter",
                    "provider": "typefully",
                    "enabled": True,
                }
            ]
        }


def _stub_publish(service: ProjectPublishingService, result: PublishResult) -> None:
    """Replace service.build_manager with a stub returning a fake PublishResult."""

    class _StubManager:
        def publish(self, request, provider_name=None):
            return result

    service.build_manager = lambda project_id=None: _StubManager()


class TestSystemEventsSchema:
    def test_pragma_table_info_returns_eight_columns(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        with store.connect() as conn:
            cols = _columns(conn, "system_events")
        assert cols == [
            "event_id",
            "ts",
            "category",
            "action",
            "project_id",
            "review_id",
            "job_id",
            "payload_json",
        ]


class TestRecordEvent:
    def test_record_event_persists_row_and_list_events_returns_it(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        row = store.record_event(
            category="review",
            action="approved",
            review_id="r1",
            project_id="p1",
            payload={"a": 1},
        )
        assert row["category"] == "review"
        assert row["action"] == "approved"
        assert row["review_id"] == "r1"
        assert row["project_id"] == "p1"
        assert row["payload"] == {"a": 1}
        assert row["ts"].endswith("+00:00")
        assert row["event_id"].startswith("evt_")

        rows = store.list_events()
        assert len(rows) == 1
        assert rows[0]["event_id"] == row["event_id"]

    def test_constructing_store_twice_is_idempotent(self, tmp_path):
        SQLiteStore(data_dir=str(tmp_path), migrate=False)
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        with store.connect() as conn:
            cols = _columns(conn, "system_events")
        assert len(cols) == 8

    def test_list_events_filters_and_orders_desc(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        store.record_event(category="review", action="approved", payload={})
        store.record_event(category="publish", action="attempted", payload={})

        review_events = store.list_events(category="review")
        assert len(review_events) == 1
        assert review_events[0]["category"] == "review"

        limited = store.list_events(limit=1)
        assert len(limited) == 1

    def test_payload_none_persists_empty_object(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        row = store.record_event(category="review", action="approved")
        assert row["payload"] == {}

    def test_non_serializable_payload_raises_type_error(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        with pytest.raises(TypeError):
            store.record_event(
                category="review",
                action="approved",
                payload={"bad": object()},
            )

    def test_unknown_category_raises_value_error(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        with pytest.raises(ValueError):
            store.record_event(category="bogus", action="x")

    def test_append_only_no_conflict_update(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        store.record_event(
            category="review", action="approved", review_id="r1", payload={}
        )
        store.record_event(
            category="review", action="approved", review_id="r1", payload={}
        )
        rows = store.list_events(category="review")
        assert len(rows) == 2


class TestListEventsFilters:
    def test_list_events_filters_by_category_since_project_and_bounds_limit(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        store.record_event(
            category="review", action="approved", project_id="p1", payload={}
        )
        store.record_event(
            category="publish", action="attempted", project_id="p1", payload={}
        )
        store.record_event(
            category="review", action="declined", project_id="p2", payload={}
        )

        assert len(store.list_events(category="review")) == 2
        assert len(store.list_events(project_id="p1")) == 2
        assert len(store.list_events(project_id="p2")) == 1
        assert len(store.list_events(limit=1)) == 1
        assert len(store.list_events(limit=0)) == 0

        future = "2999-12-31T23:59:59+00:00"
        assert store.list_events(since=future) == []

        past = "2000-01-01T00:00:00+00:00"
        assert len(store.list_events(since=past)) == 3


class TestReviewEventEmission:
    def test_review_transition_emits_one_event(self, tmp_path):
        fm = FeedbackManager(data_dir=str(tmp_path))
        project_context = ProjectContextService(_NullProjectManager(fm.store))
        publishing_service = ProjectPublishingService(
            _NullProjectManager(fm.store),
            data_dir=str(tmp_path),
            project_context=project_context,
        )
        service = ReviewWorkflowService(fm, project_context, publishing_service)

        record = fm.add_for_review(_make_post())
        review_id = record["review_id"]
        service.transition(review_id, "approve", feedback="ok")

        events = fm.store.list_events(category="review")
        assert len(events) == 1
        assert events[0]["action"] == "approve"
        assert events[0]["review_id"] == review_id


class TestPublishEventEmission:
    def test_publish_record_emits_attempted_then_terminal(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        manager = _StubProjectManager(store=store)
        service = ProjectPublishingService(manager, data_dir=str(tmp_path))
        record = {"post_data": {"content": "hi", "project_id": "p1"}}

        success = PublishResult(success=True, provider="typefully")
        _stub_publish(service, success)

        service.publish_record(record, provider_name="typefully", platform="twitter")

        events = store.list_events(category="publish")
        actions = [e["action"] for e in events]
        assert "attempted" in actions
        assert "succeeded" in actions

    def test_publish_failure_emits_failed_with_error_code(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        manager = _StubProjectManager(store=store)
        service = ProjectPublishingService(manager, data_dir=str(tmp_path))
        record = {"post_data": {"content": "hi", "project_id": "p1"}}

        failure = PublishResult(
            success=False,
            error="no provider",
            provider="typefully",
            error_code=PublishErrorCode.NOT_CONFIGURED,
        )
        _stub_publish(service, failure)

        service.publish_record(record, provider_name="typefully", platform="twitter")

        events = store.list_events(category="publish")
        actions = [e["action"] for e in events]
        assert "attempted" in actions
        assert "failed" in actions
        failed = next(e for e in events if e["action"] == "failed")
        assert failed["payload"].get("error_code") == "not_configured"


class TestJobEventEmission:
    def test_enqueue_complete_fail_with_category_emit_events(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        queue = JobQueueService(store)

        enqueued = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        job_id = enqueued["job_id"]
        queue.complete(job_id, result={"ok": True})

        failed = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        failed_id = failed["job_id"]
        failed["status"] = "running"
        failed["attempts"] = 1
        failed["started_at"] = datetime.now(timezone.utc).isoformat()
        store.save_job_record(failed)
        queue.fail_with_category(
            failed_id,
            error="boom",
            category=FailureCategory.PERMANENT,
        )

        events = store.list_events(category="job")
        actions = [e["action"] for e in events]
        assert "enqueued" in actions
        assert "completed" in actions
        assert "failed" in actions

    def test_failed_job_payload_truncates_long_error(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        queue = JobQueueService(store)
        record = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        record["status"] = "running"
        record["attempts"] = 1
        record["started_at"] = datetime.now(timezone.utc).isoformat()
        store.save_job_record(record)

        long_error = "x" * 500
        queue.fail_with_category(
            record["job_id"],
            error=long_error,
            category=FailureCategory.PERMANENT,
        )

        events = store.list_events(category="job")
        failed_events = [e for e in events if e["action"] == "failed"]
        assert failed_events
        payload = failed_events[0]["payload"]
        assert "error" in payload
        assert len(payload["error"]) <= 200

    def test_retry_path_and_terminal_path_emit_distinct_event_actions(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        queue = JobQueueService(store)

        retry_record = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        retry_record["status"] = "running"
        retry_record["attempts"] = 1
        retry_record["started_at"] = datetime.now(timezone.utc).isoformat()
        store.save_job_record(retry_record)
        retried = queue.fail_with_category(
            retry_record["job_id"],
            error="transient boom",
            category=FailureCategory.TRANSIENT,
        )

        terminal_record = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        terminal_record["status"] = "running"
        terminal_record["attempts"] = 1
        terminal_record["started_at"] = datetime.now(timezone.utc).isoformat()
        store.save_job_record(terminal_record)
        queue.fail_with_category(
            terminal_record["job_id"],
            error="permanent boom",
            category=FailureCategory.PERMANENT,
        )

        assert retried is not None
        assert retried["status"] == "queued"
        assert retried["finished_at"] is None
        retry_event = next(
            e for e in store.list_events(category="job")
            if e["job_id"] == retry_record["job_id"] and e["action"] != "enqueued"
        )
        terminal_event = next(
            e for e in store.list_events(category="job")
            if e["job_id"] == terminal_record["job_id"] and e["action"] != "enqueued"
        )
        assert retry_event["action"] == "retry_scheduled"
        assert terminal_event["action"] == "failed"
        assert retry_event["action"] != terminal_event["action"]
        assert "next_retry_at" in retry_event["payload"]
        assert "next_retry_at" not in terminal_event["payload"]

    def test_cancel_emits_cancelled_event_with_previous_status(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        queue = JobQueueService(store)
        enqueued = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )

        cancelled = queue.cancel(enqueued["job_id"])

        assert cancelled is not None
        assert cancelled["status"] == "cancelled"
        cancel_events = [
            e for e in store.list_events(category="job")
            if e["action"] == "cancelled"
        ]
        assert len(cancel_events) == 1
        event = cancel_events[0]
        assert event["job_id"] == enqueued["job_id"]
        assert event["payload"]["previous_status"] == "queued"
        assert event["payload"]["kind"] == "sync_analytics"

    def test_cancel_unknown_job_emits_no_event(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        queue = JobQueueService(store)

        result = queue.cancel("does-not-exist")

        assert result is None
        cancel_events = [
            e for e in store.list_events(category="job")
            if e["action"] == "cancelled"
        ]
        assert cancel_events == []

    def test_recover_stuck_emits_recovered_stuck_event_per_job(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        queue = JobQueueService(store)
        stuck = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        stuck["status"] = "running"
        stuck["started_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        stuck["attempts"] = 1
        store.save_job_record(stuck)

        recovered = queue.recover_stuck(threshold_minutes=30)

        assert len(recovered) == 1
        events = [
            e for e in store.list_events(category="job")
            if e["action"] == "recovered_stuck"
        ]
        assert len(events) == 1
        event = events[0]
        assert event["job_id"] == stuck["job_id"]
        assert event["payload"]["previous_status"] == "running"
        assert event["payload"]["threshold_minutes"] == 30

    def test_recover_stuck_with_no_stuck_jobs_emits_no_event(self, tmp_path):
        store = SQLiteStore(data_dir=str(tmp_path), migrate=False)
        queue = JobQueueService(store)

        recovered = queue.recover_stuck(threshold_minutes=30)

        assert recovered == []
        events = [
            e for e in store.list_events(category="job")
            if e["action"] == "recovered_stuck"
        ]
        assert events == []


class TestCredentialEventEmission:
    def test_update_provider_config_emits_rotated_event_with_only_provider_name(self, tmp_path):
        service = ProjectService(data_dir=str(tmp_path))
        project = service.create_project("Credential Project")
        secret_service = ProjectSecretService(service)

        secret_service.update_provider_config(
            project.project_id,
            "typefully",
            {
                "api_key": "super-secret-value-NOT-REAL",
                "drafts_enabled": True,
            },
        )

        events = service.store.list_events(category="credential")
        assert len(events) == 1
        event = events[0]
        assert event["action"] == "rotated"
        assert event["payload"] == {"providers": ["typefully"]}
        for key in event["payload"]:
            assert not CREDENTIAL_LEAK_PATTERN.search(key)
        for provider in event["payload"]["providers"]:
            assert not CREDENTIAL_LEAK_PATTERN.search(provider)
        assert "super-secret-value-NOT-REAL" not in str(event["payload"])

    def test_save_project_secrets_emits_rotated_event_with_provider_names_only(self, tmp_path):
        service = ProjectService(data_dir=str(tmp_path))
        project = service.create_project("Secrets Writer Project")

        service.save_project_secrets(
            project.project_id,
            {
                "typefully": {"api_key": "value-A-NOT-REAL"},
                "late": {"api_key": "value-B-NOT-REAL"},
            },
        )

        events = service.store.list_events(category="credential")
        assert len(events) == 1
        event = events[0]
        assert event["action"] == "rotated"
        assert event["payload"] == {"providers": ["late", "typefully"]}
        assert "value-A-NOT-REAL" not in str(event["payload"])
        assert "value-B-NOT-REAL" not in str(event["payload"])


class TestSettingsEventEmission:
    def test_save_project_settings_emits_event_with_keys_only(self, tmp_path):
        service = ProjectService(data_dir=str(tmp_path))
        project = service.create_project("Settings Project")

        service.save_project_settings(
            project.project_id,
            {
                "posting_strategy": {"frequency": "hourly"},
                "secrets": {"typefully": {"api_key": "abc"}},
            },
        )

        events = service.store.list_events(category="settings")
        assert len(events) == 1
        event = events[0]
        assert event["action"] == "updated"
        assert "keys" in event["payload"]
        assert isinstance(event["payload"]["keys"], list)
        assert len(event["payload"]["keys"]) >= 1

        for key in event["payload"]["keys"]:
            assert not SETTINGS_LEAK_PATTERN.search(key)
        assert "abc" not in str(event["payload"])


class TestAllFiveCategoriesIntegration:
    def test_five_flows_emit_events_in_all_categories(self, tmp_path):
        service = ProjectService(data_dir=str(tmp_path))
        project = service.create_project("Integration Project")
        store = service.store

        secret_service = ProjectSecretService(service)
        secret_service.update_provider_config(
            project.project_id,
            "typefully",
            {"api_key": "secret-value"},
        )

        service.save_project_settings(
            project.project_id,
            {"posting_strategy": {"frequency": "daily"}},
        )

        queue = JobQueueService(store)
        job = queue.enqueue(
            "sync_analytics",
            payload={"project_id": project.project_id},
            project_id=project.project_id,
        )
        queue.complete(job["job_id"], result={"ok": True})

        fm = FeedbackManager(data_dir=str(tmp_path))
        project_context = ProjectContextService(service)
        publishing_service = ProjectPublishingService(
            service,
            data_dir=str(tmp_path),
            project_context=project_context,
        )
        review_service = ReviewWorkflowService(fm, project_context, publishing_service)
        record = fm.add_for_review(_make_post(project_id=project.project_id))
        review_service.transition(record["review_id"], "approve", feedback="ok")

        success = PublishResult(success=True, provider="typefully")
        _stub_publish(publishing_service, success)
        publishing_service.publish_record(
            {"post_data": {"content": "x", "project_id": project.project_id}},
            provider_name="typefully",
            platform="twitter",
        )

        events = store.list_events()
        categories = {e["category"] for e in events}
        assert "review" in categories
        assert "publish" in categories
        assert "job" in categories
        assert "credential" in categories
        assert "settings" in categories
