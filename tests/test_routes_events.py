"""Plan 05-04 Task 2: Events API contract.

Pins the in-job log-line correlation (job_id contextvar) — the
``JobRunner.run_once`` body must set the contextvar to the running job's
id and reset it on exit so subsequent log lines do not leak the id.
"""

from __future__ import annotations

from data.sqlite_store import SQLiteStore
from services.job_queue import JobQueueService
from services.job_runner import JobRunner


def _store(project_data_dir) -> SQLiteStore:
    return SQLiteStore(data_dir=str(project_data_dir), migrate=False)


class TestJobRunnerSetsJobIdContextVar:
    def test_run_once_sets_and_resets_job_id_contextvar(self, project_data_dir):
        store = _store(project_data_dir)
        queue = JobQueueService(store)
        runner = JobRunner(queue=queue)
        enqueued = queue.enqueue("sync_analytics")
        job_id = enqueued["job_id"]

        from services.observability import current_job_id

        captured: dict[str, str] = {}

        def _probe_execute(_self, job):
            captured["during"] = current_job_id()
            return {"ok": True}

        assert current_job_id() == "-"
        original_execute = JobRunner.execute
        JobRunner.execute = _probe_execute
        try:
            result = runner.run_once()
        finally:
            JobRunner.execute = original_execute
        assert result is not None
        assert captured.get("during") == job_id, (
            f"job_id contextvar was {captured.get('during')!r} during execution; "
            f"expected {job_id!r}"
        )
        assert current_job_id() == "-", (
            "job_id contextvar leaked after run_once returned"
        )
