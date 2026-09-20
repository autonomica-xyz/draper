"""Plan 04-04 Task 3: draper jobs recover --stuck CLI + idempotency contracts."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.sqlite_store import SQLiteStore


@pytest.fixture
def stuck_store(project_data_dir: Path, monkeypatch) -> SQLiteStore:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
    return SQLiteStore(data_dir=str(project_data_dir))


def _make_stuck_job(store: SQLiteStore, *, age_minutes: int = 60, project_id: str = "p1") -> str:
    record = store.enqueue_job(
        "generate_content",
        payload={"project_id": project_id, "count": 1},
        project_id=project_id,
    )
    record["status"] = "running"
    record["started_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    ).isoformat()
    store.save_job_record(record)
    return record["job_id"]


class TestJobsRecoverEmpty:
    def test_returns_zero_and_prints_zero_count_when_no_stuck_jobs(
        self, stuck_store, capsys
    ):
        from cli import cmd_jobs_recover

        args = argparse.Namespace(
            threshold_minutes=30, data_dir=str(stuck_store.data_dir)
        )
        rc = cmd_jobs_recover(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "Recovered 0 stuck job(s)" in captured.out


class TestJobsRecoverStuckJobs:
    def test_recovers_two_stuck_jobs_and_returns_zero(self, stuck_store, capsys):
        from cli import cmd_jobs_recover

        job_a = _make_stuck_job(stuck_store, age_minutes=60)
        job_b = _make_stuck_job(stuck_store, age_minutes=90)

        args = argparse.Namespace(
            threshold_minutes=30, data_dir=str(stuck_store.data_dir)
        )
        rc = cmd_jobs_recover(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "Recovered 2 stuck job(s)" in captured.out
        assert job_a in captured.out
        assert job_b in captured.out


class TestJobsRecoverIdempotency:
    def test_second_invocation_recovers_zero_jobs(self, stuck_store, capsys):
        from cli import cmd_jobs_recover

        _make_stuck_job(stuck_store, age_minutes=60)

        args = argparse.Namespace(
            threshold_minutes=30, data_dir=str(stuck_store.data_dir)
        )
        assert cmd_jobs_recover(args) == 0
        first_out = capsys.readouterr().out
        assert "Recovered 1 stuck job(s)" in first_out

        assert cmd_jobs_recover(args) == 0
        second_out = capsys.readouterr().out
        assert "Recovered 0 stuck job(s)" in second_out


class TestJobsRecoverThresholdFilter:
    def test_job_younger_than_threshold_is_not_recovered(self, stuck_store, capsys):
        from cli import cmd_jobs_recover

        young_job = _make_stuck_job(stuck_store, age_minutes=20)

        args = argparse.Namespace(
            threshold_minutes=30, data_dir=str(stuck_store.data_dir)
        )
        rc = cmd_jobs_recover(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "Recovered 0 stuck job(s)" in captured.out
        record = stuck_store.get_job_record(young_job)
        assert record is not None
        assert record["status"] == "running"


class TestJobsRecoverMarksCategoryUnknown:
    def test_recovered_job_has_unknown_category_and_stuck_error_message(
        self, stuck_store, capsys
    ):
        from cli import cmd_jobs_recover

        job_id = _make_stuck_job(stuck_store, age_minutes=60)

        args = argparse.Namespace(
            threshold_minutes=30, data_dir=str(stuck_store.data_dir)
        )
        assert cmd_jobs_recover(args) == 0
        capsys.readouterr()

        record = stuck_store.get_job_record(job_id)
        assert record is not None
        assert record["status"] == "failed"
        assert record["failure_category"] == "unknown"
        assert record["error"] is not None
        assert "stuck: timed out" in record["error"]


class TestJobsRecoverCliSmoke:
    def test_cli_argv_exits_zero_with_no_stuck_jobs(self, stuck_store, monkeypatch):
        from cli import main

        argv = [
            "draper",
            "jobs",
            "recover",
            "--stuck",
            "--threshold-minutes",
            "60",
            "--data-dir",
            str(stuck_store.data_dir),
        ]
        monkeypatch.setattr("sys.argv", argv)
        rc = main()
        assert rc == 0


class TestJobsRecoverCleansLinkedReviewState:
    """WR-07: recover_stuck_jobs must clean up auto_fix_status on the linked
    review when a fix_content job is recovered. Otherwise the dashboard
    shows a perpetual 'queued' indicator on a needs_work review whose
    auto-fix job is permanently failed."""

    def test_recover_clears_auto_fix_status_on_linked_review(self, stuck_store):
        review_id = "stuck-fix-review-001"
        stuck_store.save_review_record(
            {
                "review_id": review_id,
                "project_id": "p1",
                "status": "needs_work",
                "post_data": {"platform": "twitter", "content": "needs fixing"},
                "auto_fix_status": "queued",
                "auto_fix_job_id": "stuck-fix-job-001",
                "created_at": datetime.now().isoformat(),
            }
        )
        record = stuck_store.enqueue_job(
            "fix_content",
            payload={"review_id": review_id, "feedback": "fix", "project_id": "p1"},
            project_id="p1",
        )
        record["job_id"] = "stuck-fix-job-001"
        record["status"] = "running"
        record["started_at"] = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        stuck_store.save_job_record(record)

        recovered = stuck_store.recover_stuck_jobs(threshold_minutes=30)

        assert len(recovered) == 1
        review = stuck_store.get_review_record(review_id)
        assert review is not None
        assert "auto_fix_status" not in review
        assert "auto_fix_job_id" not in review
        assert review["status"] == "needs_work"

    def test_recover_does_not_touch_review_with_different_job_id(self, stuck_store):
        review_id = "stuck-fix-review-002"
        stuck_store.save_review_record(
            {
                "review_id": review_id,
                "project_id": "p1",
                "status": "needs_work",
                "post_data": {"platform": "twitter", "content": "needs fixing"},
                "auto_fix_status": "queued",
                "auto_fix_job_id": "a-different-job-id",
                "created_at": datetime.now().isoformat(),
            }
        )
        record = stuck_store.enqueue_job(
            "fix_content",
            payload={"review_id": review_id, "feedback": "fix", "project_id": "p1"},
            project_id="p1",
        )
        record["status"] = "running"
        record["started_at"] = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        stuck_store.save_job_record(record)

        stuck_store.recover_stuck_jobs(threshold_minutes=30)

        review = stuck_store.get_review_record(review_id)
        assert review is not None
        assert review.get("auto_fix_status") == "queued"
        assert review.get("auto_fix_job_id") == "a-different-job-id"

    def test_recover_skips_review_cleanup_for_non_fix_content_jobs(self, stuck_store):
        review_id = "stuck-fix-review-003"
        stuck_store.save_review_record(
            {
                "review_id": review_id,
                "project_id": "p1",
                "status": "needs_work",
                "post_data": {"platform": "twitter", "content": "x"},
                "auto_fix_status": "queued",
                "auto_fix_job_id": "other",
                "created_at": datetime.now().isoformat(),
            }
        )
        record = stuck_store.enqueue_job(
            "generate_content",
            payload={"project_id": "p1", "count": 1},
            project_id="p1",
        )
        record["status"] = "running"
        record["started_at"] = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        stuck_store.save_job_record(record)

        stuck_store.recover_stuck_jobs(threshold_minutes=30)

        review = stuck_store.get_review_record(review_id)
        assert review is not None
        assert review.get("auto_fix_status") == "queued"

    def test_recover_handles_missing_linked_review_gracefully(self, stuck_store):
        record = stuck_store.enqueue_job(
            "fix_content",
            payload={
                "review_id": "never-existed-review",
                "feedback": "fix",
                "project_id": "p1",
            },
            project_id="p1",
        )
        record["status"] = "running"
        record["started_at"] = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        stuck_store.save_job_record(record)

        recovered = stuck_store.recover_stuck_jobs(threshold_minutes=30)
        assert len(recovered) == 1
        assert recovered[0]["status"] == "failed"
