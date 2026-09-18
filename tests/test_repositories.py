"""Delegation contract tests for data/repositories/ wrapper layer.

Each repository must delegate one-to-one to the corresponding SQLiteStore
method without altering arguments or return values. The repository layer
is the surface new application services target (ARCH-07, criterion #4);
these tests pin the delegation contract so future backends (Postgres)
can swap in without touching services.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from data.repositories import (
    AnalyticsRepository,
    BaseRepository,
    EventRepository,
    JobRepository,
    ProjectRepository,
    ReviewRepository,
    ScheduledPostRepository,
)
from data.sqlite_store import SQLiteStore


@pytest.fixture
def store() -> Generator[SQLiteStore, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        s = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
        yield s


class TestBaseRepositoryStoreAttribute:
    def test_base_repository_exposes_store_as_public_attribute(self, store):
        repo = BaseRepository(store)
        assert repo.store is store


class TestProjectRepositoryDelegation:
    def _seed_project(self, store, project_id="proj-1"):
        record = {
            "project_id": project_id,
            "name": "Test Project",
            "slug": "test-project",
            "description": "desc",
            "config": {"theme": "dark"},
            "settings": {"foo": "bar"},
            "generation_schedule": {"frequency": "daily"},
        }
        store.save_project_record(record)
        return record

    def test_get_delegates_to_store(self, store):
        self._seed_project(store)
        repo = ProjectRepository(store)
        assert repo.get("proj-1") == store.get_project_record("proj-1")

    def test_get_by_slug_delegates_to_store(self, store):
        self._seed_project(store)
        repo = ProjectRepository(store)
        assert repo.get_by_slug("test-project") == store.get_project_record_by_slug(
            "test-project"
        )

    def test_get_by_name_delegates_to_store(self, store):
        self._seed_project(store)
        repo = ProjectRepository(store)
        assert repo.get_by_name("Test Project") == store.get_project_record_by_name(
            "Test Project"
        )

    def test_list_delegates_to_store(self, store):
        self._seed_project(store)
        repo = ProjectRepository(store)
        assert repo.list() == store.list_project_records()

    def test_save_delegates_to_store(self, store):
        repo = ProjectRepository(store)
        record = {
            "project_id": "proj-save",
            "name": "Save Project",
            "slug": "save-project",
        }
        repo.save(record)
        assert store.get_project_record("proj-save") is not None

    def test_get_value_delegates_to_store(self, store):
        self._seed_project(store)
        store.set_project_value("proj-1", "k", "v")
        repo = ProjectRepository(store)
        assert repo.get_value("proj-1", "k") == store.get_project_value("proj-1", "k")

    def test_set_value_delegates_to_store(self, store):
        self._seed_project(store)
        repo = ProjectRepository(store)
        repo.set_value("proj-1", "kk", "vv")
        assert store.get_project_value("proj-1", "kk") == "vv"

    def test_normalize_delegates_to_store(self, store):
        repo = ProjectRepository(store)
        raw = {"project_id": "p", "name": "n", "created_at": "2026-07-04T00:00:00+00:00"}
        assert repo.normalize("p", raw) == store._normalize_project_record("p", raw)


class TestReviewRepositoryDelegation:
    def _seed_review(self, store, review_id="r1"):
        record = {
            "review_id": review_id,
            "project_id": "proj-1",
            "status": "pending_review",
            "post_data": {"body": "hello"},
        }
        store.save_review_record(record)
        return record

    def test_get_delegates_to_store(self, store):
        self._seed_review(store)
        repo = ReviewRepository(store)
        assert repo.get("r1") == store.get_review_record("r1")

    def test_list_delegates_to_store(self, store):
        self._seed_review(store)
        repo = ReviewRepository(store)
        assert repo.list() == store.list_review_records()

    def test_save_delegates_to_store(self, store):
        repo = ReviewRepository(store)
        repo.save({"review_id": "r2", "post_data": {"body": "x"}})
        assert store.get_review_record("r2") is not None


class TestJobRepositoryDelegation:
    def test_enqueue_delegates_to_store(self, store):
        repo = JobRepository(store)
        result = repo.enqueue(
            kind="generate_content",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        direct = store.enqueue_job(
            kind="generate_content",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        assert result["kind"] == direct["kind"]
        assert result["project_id"] == direct["project_id"]
        assert result["status"] == direct["status"]
        assert store.get_job_record(result["job_id"]) is not None

    def test_get_delegates_to_store(self, store):
        repo = JobRepository(store)
        enqueued = repo.enqueue(kind="generic", payload={})
        assert repo.get(enqueued["job_id"]) == store.get_job_record(enqueued["job_id"])

    def test_list_delegates_to_store(self, store):
        repo = JobRepository(store)
        repo.enqueue(kind="generic", payload={})
        assert repo.list() == store.list_job_records()

    def test_claim_next_delegates_to_store(self, store):
        repo = JobRepository(store)
        enqueued = repo.enqueue(kind="generic", payload={})
        claimed = repo.claim_next()
        assert claimed is not None
        assert claimed["job_id"] == enqueued["job_id"]

    def test_complete_delegates_to_store(self, store):
        repo = JobRepository(store)
        enqueued = repo.enqueue(kind="generic", payload={})
        repo.claim_next()
        result = repo.complete(enqueued["job_id"], result={"ok": True})
        direct = store.get_job_record(enqueued["job_id"])
        assert result["status"] == direct["status"] == "completed"

    def test_fail_delegates_to_store(self, store):
        repo = JobRepository(store)
        enqueued = repo.enqueue(kind="generic", payload={})
        repo.claim_next()
        result = repo.fail(enqueued["job_id"], error="boom", retry=False)
        direct = store.get_job_record(enqueued["job_id"])
        assert result["status"] == direct["status"] == "failed"

    def test_fail_passes_failure_category_through(self, store):
        repo = JobRepository(store)
        enqueued = repo.enqueue(kind="generic", payload={})
        repo.claim_next()
        repo.fail(enqueued["job_id"], error="boom", retry=False, failure_category="transient")
        direct = store.get_job_record(enqueued["job_id"])
        assert direct["failure_category"] == "transient"

    def test_save_delegates_to_store(self, store):
        repo = JobRepository(store)
        record = {
            "job_id": "job-custom",
            "kind": "generic",
            "payload": {"a": 1},
            "status": "queued",
        }
        repo.save(record)
        assert store.get_job_record("job-custom") is not None

    def test_cancel_delegates_to_store(self, store):
        repo = JobRepository(store)
        enqueued = repo.enqueue(kind="generic", payload={})
        cancelled = repo.cancel(enqueued["job_id"])
        direct = store.get_job_record(enqueued["job_id"])
        assert cancelled["status"] == direct["status"] == "cancelled"

    def test_stats_delegates_to_store(self, store):
        repo = JobRepository(store)
        repo.enqueue(kind="generic", payload={})
        assert repo.stats() == store.get_job_stats()

    def test_recover_stuck_delegates_to_store(self, store):
        repo = JobRepository(store)
        assert repo.recover_stuck(threshold_minutes=30) == store.recover_stuck_jobs(
            threshold_minutes=30
        )


class TestScheduledPostRepositoryDelegation:
    def _seed_post(self, store, post_id="post1"):
        record = {
            "post_id": post_id,
            "project_id": "p1",
            "status": "scheduled",
            "scheduled_at": "2026-07-10T10:00:00+00:00",
            "post_data": {"body": "x"},
        }
        store.save_scheduled_record(record)
        return record

    def test_get_delegates_to_store(self, store):
        self._seed_post(store)
        repo = ScheduledPostRepository(store)
        assert repo.get("post1") == store.get_scheduled_record("post1")

    def test_list_delegates_to_store(self, store):
        self._seed_post(store)
        repo = ScheduledPostRepository(store)
        assert repo.list(project_id="p1") == store.list_scheduled_records(project_id="p1")

    def test_save_delegates_to_store(self, store):
        repo = ScheduledPostRepository(store)
        repo.save(
            {
                "post_id": "post-save",
                "project_id": "p1",
                "scheduled_at": "2026-07-10T10:00:00+00:00",
                "post_data": {"body": "y"},
            }
        )
        assert store.get_scheduled_record("post-save") is not None

    def test_normalize_delegates_to_store(self, store):
        repo = ScheduledPostRepository(store)
        raw = {
            "post_id": "z",
            "scheduled_at": "2026-07-10T10:00:00+00:00",
            "created_at": "2026-07-04T00:00:00+00:00",
        }
        assert repo.normalize(raw) == store.normalize_scheduled_record(raw)


class TestEventRepositoryDelegation:
    def test_record_event_delegates_to_store(self, store):
        repo = EventRepository(store)
        result = repo.record_event(
            category="review",
            action="approved",
            review_id="r1",
            payload={"actor": "alice"},
        )
        direct_lookup = store.list_events(category="review", limit=10)
        assert any(e["event_id"] == result["event_id"] for e in direct_lookup)

    def test_list_delegates_to_store(self, store):
        store.record_event(category="job", action="enqueued", job_id="j1")
        repo = EventRepository(store)
        assert repo.list(category="job", limit=10) == store.list_events(
            category="job", limit=10
        )


class TestAnalyticsRepositoryDelegation:
    def test_save_snapshot_delegates_to_store(self, store):
        repo = AnalyticsRepository(store)
        repo.save_snapshot("typefully_metrics.json", {"k": "v"})
        assert store.get_analytics_snapshot("typefully_metrics.json") == {"k": "v"}

    def test_get_snapshot_delegates_to_store(self, store):
        store.save_analytics_snapshot("unified.json", {"a": 1})
        repo = AnalyticsRepository(store)
        assert repo.get_snapshot("unified.json") == store.get_analytics_snapshot("unified.json")

    def test_list_snapshots_delegates_to_store(self, store):
        store.save_analytics_snapshot("a.json", {"x": 1})
        repo = AnalyticsRepository(store)
        assert repo.list_snapshots() == store.list_analytics_snapshots()
