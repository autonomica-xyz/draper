"""Plan 04-01 Task 1: Worker class regression contracts.

Pins the long-running ``draper-worker`` polling loop behavior:

1. ``run_once`` returns the JobRunner result and bumps the processed counter.
2. ``run_once`` returns ``None`` for an idle queue.
3. ``run_once`` surfaces failure results from JobRunner.
4. ``run_forever(stop_after=IdleCycles(N))`` exits after N idle cycles.
5. SIGTERM triggers graceful shutdown within ``poll_interval + 1.0`` seconds.
6. ``run_forever`` drains a multi-job queue then exits on idle.
7. ``stats`` returns the documented four-key shape.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import threading
import time
from typing import Any

import pytest


sqlite3_operational_error = sqlite3.OperationalError


@pytest.fixture
def container(project_data_dir: Any, monkeypatch):
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
def fixture_project_id(fixture_project):
    return fixture_project["project_id"]


class TestWorkerRunOnce:
    def test_run_once_returns_success_when_job_queued(
        self, container, fixture_project_id
    ):
        from services.worker import Worker

        job = container.job_queue.enqueue(
            "sync_analytics",
            project_id=fixture_project_id,
            payload={},
        )
        container.analytics.sync_all_platforms = lambda: {"synced": True}

        worker = Worker(container)
        result = worker.run_once()

        assert result is not None
        assert result["success"] is True
        assert result["job"]["job_id"] == job["job_id"]

        stored = container.job_queue.get(job["job_id"])
        assert stored["status"] == "completed"
        assert worker.jobs_processed == 1
        assert worker.jobs_failed == 0

    def test_run_once_returns_none_when_queue_empty(self, container):
        from services.worker import Worker

        worker = Worker(container)
        result = worker.run_once()

        assert result is None
        assert worker.idle_cycles == 1
        assert worker.jobs_processed == 0

    def test_run_once_marks_failed_when_runner_raises(
        self, container, fixture_project_id
    ):
        from services.worker import Worker

        job = container.store.enqueue_job(
            "unknown_kind",
            project_id=fixture_project_id,
            payload={},
        )
        worker = Worker(container)
        result = worker.run_once()

        assert result is not None
        assert result["success"] is False
        assert "error" in result

        stored = container.job_queue.get(job["job_id"])
        assert stored["status"] == "failed"
        assert worker.jobs_failed == 1
        assert worker.jobs_processed == 0


class TestWorkerRunForever:
    def test_run_forever_exits_after_idle_limit(self, container):
        from services.worker import IdleCycles, Worker

        worker = Worker(container, poll_interval=0.01)
        worker.run_forever(stop_after=IdleCycles(3))

        assert worker.idle_cycles == 3
        assert worker.jobs_processed == 0

    def test_run_forever_graceful_shutdown_on_sigterm(self, container):
        from services.worker import IdleCycles, Worker

        def _fire_sigterm_after(delay: float) -> None:
            time.sleep(delay)
            os.kill(os.getpid(), signal.SIGTERM)

        worker = Worker(container, poll_interval=0.05)
        shooter = threading.Thread(target=_fire_sigterm_after, args=(0.1,), daemon=True)
        shooter.start()

        start = time.monotonic()
        worker.run_forever(stop_after=IdleCycles(100))
        elapsed = time.monotonic() - start

        assert elapsed < 2.0
        assert worker._stop is True

    def test_run_forever_drains_two_jobs_then_exits_on_idle(
        self, container, fixture_project_id
    ):
        from services.worker import IdleCycles, Worker

        class _StubGenerator:
            def generate_batch(self, count=1, platforms=None):
                return {"posts": [{"platform": "twitter", "content": "x"}]}

        stub = _StubGenerator()
        container.generator = stub
        container.job_runner.generator = stub

        job1 = container.job_queue.enqueue(
            "generate_content",
            project_id=fixture_project_id,
            payload={"project_id": fixture_project_id, "count": 1},
        )
        job2 = container.job_queue.enqueue(
            "generate_content",
            project_id=fixture_project_id,
            payload={"project_id": fixture_project_id, "count": 1},
        )

        worker = Worker(container, poll_interval=0.01)
        worker.run_forever(stop_after=IdleCycles(1))

        rec1 = container.job_queue.get(job1["job_id"])
        rec2 = container.job_queue.get(job2["job_id"])
        assert rec1["status"] == "completed"
        assert rec2["status"] == "completed"
        assert worker.jobs_processed == 2
        assert worker.idle_cycles == 1


class TestWorkerStats:
    def test_stats_returns_documented_shape(self, container):
        from services.worker import Worker

        worker = Worker(container)
        stats = worker.stats()

        assert set(stats.keys()) == {
            "jobs_processed",
            "jobs_failed",
            "idle_cycles",
            "uptime_seconds",
        }
        assert isinstance(stats["uptime_seconds"], float)


class TestWorkerRunForeverResilience:
    """WR-03: run_forever must survive transient errors inside run_once
    (SQLite 'database is locked', OSError, etc.) and keep polling."""

    def test_run_forever_continues_after_run_once_raises(self, container):
        from services.worker import IdleCycles, Worker

        worker = Worker(container, poll_interval=0.01)

        call_count = {"n": 0}
        original_run_once = worker.run_once

        def _flaky_run_once(kinds=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise sqlite3_operational_error("database is locked")
            return original_run_once(kinds=kinds)

        worker.run_once = _flaky_run_once

        worker.run_forever(stop_after=IdleCycles(2))

        assert worker._stop is False
        assert call_count["n"] >= 2

    def test_run_forever_keeps_polling_on_repeated_errors(self, container):
        from services.worker import IdleCycles, Worker

        worker = Worker(container, poll_interval=0.01)

        call_count = {"n": 0}

        def _always_raise(kinds=None):
            call_count["n"] += 1
            raise RuntimeError("transient OS error")

        worker.run_once = _always_raise

        def _fire_sigterm_after(delay: float) -> None:
            time.sleep(delay)
            os.kill(os.getpid(), signal.SIGTERM)

        shooter = threading.Thread(target=_fire_sigterm_after, args=(0.2,), daemon=True)
        shooter.start()

        start = time.monotonic()
        worker.run_forever(stop_after=IdleCycles(100))
        elapsed = time.monotonic() - start

        assert worker._stop is True
        assert call_count["n"] >= 2
        assert elapsed < 2.0


class TestAsyncGenerateWorkerDrain:
    """Phase 4 criteria #1 + #2: worker drains jobs without /api/jobs/run-next."""

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

        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture
    def fixture_project_id(self, fixture_project):
        return fixture_project["project_id"]

    def test_async_generate_job_drains_via_worker_not_runnext(
        self, container, client, fixture_project_id
    ):
        from services.worker import IdleCycles, Worker

        token = container.csrf.current_token()
        resp = client.post(
            "/api/generate",
            json={
                "async": True,
                "count": 1,
                "project_id": fixture_project_id,
            },
            headers={"x-csrf-token": token},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["async"] is True
        assert "job_id" in body
        assert "job" in body
        job_id = body["job_id"]

        class _StubGenerator:
            def generate_batch(self, count=1, platforms=None):
                return {"posts": [{"platform": "twitter", "content": "test post"}]}

        stub = _StubGenerator()
        container.generator = stub
        container.job_runner.generator = stub

        worker = Worker(container, poll_interval=0.01)
        worker.run_forever(stop_after=IdleCycles(1))

        record = container.job_queue.get(job_id)
        assert record["status"] == "completed"
        result = record.get("result_json") or record.get("result") or {}
        if isinstance(result, str):
            import json as _json

            result = _json.loads(result)
        assert result.get("count") == 1
        assert len(result.get("review_ids", [])) == 1

    def test_publish_scheduled_post_drains_at_due_time(
        self, container, fixture_project_id
    ):
        from datetime import datetime, timezone

        from services.worker import IdleCycles, Worker

        post_id = "test-scheduled-post-001"
        review_id = "test-review-001"
        container.store.save_scheduled_record(
            {
                "post_id": post_id,
                "project_id": fixture_project_id,
                "status": "scheduled",
                "scheduled_at": datetime.now(timezone.utc).isoformat(),
                "review_id": review_id,
                "post_data": {"platform": "twitter", "content": "scheduled"},
            }
        )

        container.content_workflow.publish_review = lambda *a, **kw: {
            "success": True,
            "provider": "typefully",
            "draft_id": "d1",
            "url": "https://example.com/d1",
            "review_id": review_id,
        }

        job = container.job_queue.enqueue(
            "publish_scheduled_post",
            project_id=fixture_project_id,
            available_at=datetime.now(timezone.utc).isoformat(),
            payload={
                "post_id": post_id,
                "review_id": review_id,
                "project_id": fixture_project_id,
                "platform": "twitter",
            },
        )

        worker = Worker(container, poll_interval=0.01)
        worker.run_forever(stop_after=IdleCycles(1))

        record = container.job_queue.get(job["job_id"])
        assert record["status"] == "completed"
