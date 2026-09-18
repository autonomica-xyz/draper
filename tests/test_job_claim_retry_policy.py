"""CR-01 regression: retry-policy vs job-claim max_attempts mismatch.

Pins the contract that ``RetryPolicy`` is the sole authority over retry
decisions. ``claim_next_job`` must NOT filter candidates by
``attempts < max_attempts`` because that filter (combined with the default
job-level ``max_attempts=3``) blocks transiently-failing jobs that the
retry policy would otherwise retry (TRANSIENT cap = 4 attempts).

Before the fix, this test fails because after the 3rd transient failure
the policy says "retry" (3 < 4) and re-queues the job, but the claim
query's ``attempts < max_attempts`` (3 < 3 = false) refuses to claim it
ever again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from services.job_queue import JobQueueService
from services.job_runner import JobRunner


@pytest.fixture
def queue(seeded_store) -> JobQueueService:
    return JobQueueService(seeded_store)


class _TransientConnectError(Exception):
    """A connect-style transient error; categorize_exception maps to TRANSIENT."""


def _force_available_now(queue: JobQueueService, job_id: str) -> None:
    record = queue.get(job_id)
    if record is None or record.get("status") != "queued":
        return
    record["available_at"] = datetime.now(timezone.utc).isoformat()
    queue.store.save_job_record(record)


class TestClaimDoesNotBlockPolicyRetries:
    """A transiently-failing job must remain claimable until the policy gives up."""

    def test_transient_job_drains_through_four_attempts(self, queue):
        job = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "fixture-proj-001"},
            project_id="fixture-proj-001",
        )
        job_id = job["job_id"]

        def _boom(_job: Any) -> Any:
            raise _TransientConnectError("connection reset")

        runner = JobRunner(queue=queue)
        runner._sync_analytics = _boom

        for attempt in range(1, 5):
            _force_available_now(queue, job_id)
            result = runner.run_once()
            assert result is not None, (
                f"attempt {attempt}: run_once returned None -- job is stuck in "
                f"queued. This is the CR-01 bug: the claim filter "
                f"`attempts < max_attempts` blocks policy-driven retries."
            )
            assert result["success"] is False
            assert result["failure_category"] == "transient"
            record = queue.get(job_id)
            assert record["attempts"] == attempt
            if attempt < 4:
                assert record["status"] == "queued", (
                    f"attempt {attempt}: policy should have re-queued"
                )
            else:
                assert record["status"] == "failed", (
                    "attempt 4: policy cap reached, job should be failed"
                )

    def test_failed_job_after_policy_cap_is_not_claimable(self, queue):
        from services.retry_policy import FailureCategory

        job = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "fixture-proj-001"},
            project_id="fixture-proj-001",
        )
        job_id = job["job_id"]

        for _ in range(4):
            _force_available_now(queue, job_id)
            claimed = queue.claim_next()
            assert claimed is not None, (
                "claim_next returned None before the policy cap was reached -- "
                "this is the CR-01 bug"
            )
            queue.fail_with_category(
                job_id,
                error="connection reset",
                category=FailureCategory.TRANSIENT,
            )

        final = queue.get(job_id)
        assert final["status"] == "failed"
        assert final["attempts"] == 4
        _force_available_now(queue, job_id)
        assert queue.claim_next() is None

    def test_available_at_backoff_still_gates_claim(self, queue):
        from services.retry_policy import FailureCategory

        job = queue.enqueue(
            "sync_analytics",
            payload={"project_id": "fixture-proj-001"},
            project_id="fixture-proj-001",
        )
        job_id = job["job_id"]

        claimed = queue.claim_next()
        assert claimed is not None

        queue.fail_with_category(
            job_id,
            error="connection reset",
            category=FailureCategory.TRANSIENT,
        )

        failed_record = queue.get(job_id)
        assert failed_record["status"] == "queued"
        available_at = failed_record["available_at"]
        available_dt = datetime.fromisoformat(available_at)
        if available_dt.tzinfo is None:
            available_dt = available_dt.replace(tzinfo=timezone.utc)
        assert available_dt > datetime.now(timezone.utc) - timedelta(seconds=1)

        immediate = queue.claim_next()
        assert immediate is None, (
            "claim_next must still respect available_at backoff even after the "
            "max_attempts filter is removed"
        )
