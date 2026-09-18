"""Plan 04-04 Task 2: Job failure handling + categorization contracts."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from services.job_queue import JobQueueService
from services.job_runner import JobRunner
from services.retry_policy import FailureCategory


@pytest.fixture
def queue(seeded_store) -> JobQueueService:
    return JobQueueService(seeded_store)


def _seed_running_job(queue: JobQueueService, attempts: int = 1) -> str:
    record = queue.enqueue(
        "sync_analytics",
        payload={"project_id": "fixture-proj-001"},
        project_id="fixture-proj-001",
    )
    record["status"] = "running"
    record["attempts"] = attempts
    record["started_at"] = datetime.now().isoformat()
    queue.store.save_job_record(record)
    return record["job_id"]


class TestFailWithCategoryTransient:
    def test_transient_failure_marks_queued_with_category_and_future_available_at(
        self, queue
    ):
        job_id = _seed_running_job(queue, attempts=1)
        result = queue.fail_with_category(
            job_id, error="timeout", category=FailureCategory.TRANSIENT
        )
        assert result is not None
        assert result["status"] == "queued"
        assert result["failure_category"] == "transient"
        assert result["available_at"] is not None
        assert result["attempts"] == 1


class TestFailWithCategoryPermanent:
    def test_permanent_failure_marks_failed_with_category(
        self, queue
    ):
        job_id = _seed_running_job(queue, attempts=1)
        result = queue.fail_with_category(
            job_id, error="bad payload", category=FailureCategory.PERMANENT
        )
        assert result is not None
        assert result["status"] == "failed"
        assert result["failure_category"] == "permanent"
        assert result["finished_at"] is not None


class TestFailWithCategoryTransientAtCap:
    def test_transient_at_cap_marks_failed(self, queue):
        job_id = _seed_running_job(queue, attempts=4)
        result = queue.fail_with_category(
            job_id, error="still timing out", category=FailureCategory.TRANSIENT
        )
        assert result is not None
        assert result["status"] == "failed"


class TestJobRunnerCategorizationPermanent:
    def test_value_error_during_run_once_records_permanent_category(self, queue):
        record = queue.enqueue(
            "generate_content",
            payload={"project_id": "fixture-proj-001", "count": 1},
            project_id="fixture-proj-001",
        )
        job_id = record["job_id"]

        def _boom(_job):
            raise ValueError("invalid payload")

        runner = JobRunner(queue=queue)
        runner._generate_content = _boom
        result = runner.run_once()
        assert result is not None
        assert result["success"] is False
        assert result["failure_category"] == "permanent"
        record = queue.get(job_id)
        assert record is not None
        assert record["failure_category"] == "permanent"
        assert record["status"] == "failed"


class TestJobRunnerCategorizationTransient:
    def test_connect_error_during_run_once_records_transient_category(self, queue):
        record = queue.enqueue(
            "generate_content",
            payload={"project_id": "fixture-proj-001", "count": 1},
            project_id="fixture-proj-001",
        )
        job_id = record["job_id"]

        class ConnectError(Exception):
            pass

        def _boom(_job):
            raise ConnectError("no connection")

        runner = JobRunner(queue=queue)
        runner._generate_content = _boom
        result = runner.run_once()
        assert result is not None
        assert result["success"] is False
        assert result["failure_category"] == "transient"
        record = queue.get(job_id)
        assert record is not None
        assert record["failure_category"] == "transient"
        assert record["status"] == "queued"


class TestRecoverStuckAuthz:
    def test_recover_stuck_path_is_owner_only(self):
        from dashboard.middleware.auth import infer_project_authz

        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/jobs/recover-stuck"
        request.query_params = {}
        request.headers = {}

        import asyncio

        project_id, role, admin_only = asyncio.run(infer_project_authz(request))
        assert project_id is None
        assert role == "owner"
        assert admin_only is True
