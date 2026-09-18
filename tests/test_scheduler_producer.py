"""Plan 04-02 Task 1: SchedulerProducer regression contracts (ARCH-05 D-2).

Pins the behavior of ``services.scheduler_producer.SchedulerProducer.tick``:
- enqueues one ``generate_content`` job per due project
- skips projects that already generated today (``last_generation_at`` KV)
- skips projects that already have a queued ``generate_content`` (idempotency)
- writes ``last_generation_at`` KV after enqueueing
- every enqueued payload has a ``project_id`` key

Also pins the ``draper scheduler tick --dry-run`` CLI subcommand.
"""

from __future__ import annotations

from datetime import datetime

from services.scheduler_producer import SchedulerProducer


class _FakeContainer:
    def __init__(self, project_manager, job_queue, store):
        self.project_manager = project_manager
        self.job_queue = job_queue
        self.store = store


def _set_schedule(store, project_id, schedule):
    record = store.get_project_record(project_id) or {"project_id": project_id}
    record = {**record, "generation_schedule": schedule}
    store.save_project_record(record)


def _enqueued_generate_content_jobs(store, project_id):
    return [
        job
        for job in store.list_job_records(project_id=project_id, status="queued")
        if job.get("kind") == "generate_content"
    ]


class TestSchedulerProducerTick:
    """Pin SchedulerProducer.tick due/idempotency semantics."""

    def test_tick_enqueues_one_job_for_due_project(self, seeded_store, fixture_project):
        project_id = fixture_project["project_id"]
        schedule = {"frequency": "daily", "times": ["09:00"], "posts_per_batch": 3}
        _set_schedule(seeded_store, project_id, schedule)

        from projects.manager import ProjectManager

        pm = ProjectManager(data_dir=str(seeded_store.data_dir))
        container = _FakeContainer(pm, _RealJobQueue(seeded_store), seeded_store)
        producer = SchedulerProducer(container)

        result = producer.tick(now=datetime(2026, 7, 5, 9, 5))

        assert result["enqueued"] == [project_id]
        jobs = _enqueued_generate_content_jobs(seeded_store, project_id)
        assert len(jobs) == 1
        assert jobs[0]["payload"].get("project_id") == project_id
        assert jobs[0]["payload"].get("count") == 3
        assert jobs[0]["payload"].get("channel") == "SCHEDULER"

    def test_tick_skips_project_that_already_generated_today(self, seeded_store, fixture_project):
        project_id = fixture_project["project_id"]
        schedule = {"frequency": "daily", "times": ["09:00"], "posts_per_batch": 3}
        _set_schedule(seeded_store, project_id, schedule)
        seeded_store.set_project_value(
            project_id, "last_generation_at", "2026-07-05T09:00:00"
        )

        from projects.manager import ProjectManager

        pm = ProjectManager(data_dir=str(seeded_store.data_dir))
        container = _FakeContainer(pm, _RealJobQueue(seeded_store), seeded_store)
        producer = SchedulerProducer(container)

        result = producer.tick(now=datetime(2026, 7, 5, 14, 0))

        assert result["enqueued"] == []
        assert _enqueued_generate_content_jobs(seeded_store, project_id) == []

    def test_tick_with_two_projects_enqueues_only_due_one(
        self, seeded_store, fixture_project
    ):
        due_id = fixture_project["project_id"]
        _set_schedule(
            seeded_store,
            due_id,
            {"frequency": "daily", "times": ["09:00"], "posts_per_batch": 2},
        )

        not_due_id = "second-project-xyz"
        seeded_store.save_project_record(
            {
                "project_id": not_due_id,
                "name": "Second Project",
                "slug": "second-project",
                "generation_schedule": {
                    "frequency": "daily",
                    "times": ["09:00"],
                    "posts_per_batch": 2,
                },
                "created_at": "2026-07-04T00:00:00+00:00",
            }
        )
        seeded_store.set_project_value(
            not_due_id, "last_generation_at", "2026-07-05T08:00:00"
        )

        from projects.manager import ProjectManager

        pm = ProjectManager(data_dir=str(seeded_store.data_dir))
        container = _FakeContainer(pm, _RealJobQueue(seeded_store), seeded_store)
        producer = SchedulerProducer(container)

        result = producer.tick(now=datetime(2026, 7, 5, 14, 0))

        assert result["enqueued"] == [due_id]
        assert _enqueued_generate_content_jobs(seeded_store, due_id)
        assert not _enqueued_generate_content_jobs(seeded_store, not_due_id)

    def test_tick_is_idempotent_when_called_twice(self, seeded_store, fixture_project):
        project_id = fixture_project["project_id"]
        _set_schedule(
            seeded_store,
            project_id,
            {"frequency": "daily", "times": ["09:00"], "posts_per_batch": 1},
        )

        from projects.manager import ProjectManager

        pm = ProjectManager(data_dir=str(seeded_store.data_dir))
        container = _FakeContainer(pm, _RealJobQueue(seeded_store), seeded_store)
        producer = SchedulerProducer(container)

        first = producer.tick(now=datetime(2026, 7, 5, 9, 5))
        second = producer.tick(now=datetime(2026, 7, 5, 9, 5))

        assert first["enqueued"] == [project_id]
        assert second["enqueued"] == []
        jobs = _enqueued_generate_content_jobs(seeded_store, project_id)
        assert len(jobs) == 1

    def test_tick_updates_last_generation_at_kv(self, seeded_store, fixture_project):
        project_id = fixture_project["project_id"]
        _set_schedule(
            seeded_store,
            project_id,
            {"frequency": "daily", "times": ["09:00"], "posts_per_batch": 3},
        )

        from projects.manager import ProjectManager

        pm = ProjectManager(data_dir=str(seeded_store.data_dir))
        container = _FakeContainer(pm, _RealJobQueue(seeded_store), seeded_store)
        producer = SchedulerProducer(container)

        producer.tick(now=datetime(2026, 7, 5, 9, 5))

        last_gen = seeded_store.get_project_value(project_id, "last_generation_at")
        assert last_gen == "2026-07-05T09:05:00"

    def test_every_enqueued_payload_has_project_id(self, seeded_store, fixture_project):
        project_id = fixture_project["project_id"]
        _set_schedule(
            seeded_store,
            project_id,
            {"frequency": "daily", "times": ["09:00"], "posts_per_batch": 1},
        )

        from projects.manager import ProjectManager

        pm = ProjectManager(data_dir=str(seeded_store.data_dir))
        container = _FakeContainer(pm, _RealJobQueue(seeded_store), seeded_store)
        producer = SchedulerProducer(container)

        producer.tick(now=datetime(2026, 7, 5, 9, 5))

        for job in seeded_store.list_job_records(status="queued"):
            assert job["payload"].get("project_id")


class _RealJobQueue:
    def __init__(self, store):
        from services.job_queue import JobQueueService

        self._service = JobQueueService(store)

    def enqueue(self, *args, **kwargs):
        return self._service.enqueue(*args, **kwargs)

    def list(self, *args, **kwargs):
        return self._service.list(*args, **kwargs)


class TestSchedulerDryRunCli:
    """Pin the ``draper scheduler tick --dry-run`` subcommand."""

    def test_dry_run_does_not_enqueue(self, tmp_path, monkeypatch, capsys):
        from cli import cmd_scheduler_tick

        record = {
            "project_id": "cli-dry-run-proj",
            "name": "CLI Dry Run Project",
            "slug": "cli-dry-run",
            "generation_schedule": {
                "frequency": "daily",
                "times": ["09:00"],
                "posts_per_batch": 2,
            },
            "created_at": "2026-07-04T00:00:00+00:00",
        }
        from data.sqlite_store import SQLiteStore

        store = SQLiteStore(data_dir=str(tmp_path), migrate=True)
        store.save_project_record(record)
        store.set_current_project_id(record["project_id"])

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")

        class Args:
            data_dir = str(tmp_path)
            dry_run = True

        exit_code = cmd_scheduler_tick(Args())
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Would enqueue" in captured.out
        assert not store.list_job_records(status="queued")

    def test_dry_run_does_not_advance_last_generation_at(self, tmp_path, monkeypatch, capsys):
        from cli import cmd_scheduler_tick

        record = {
            "project_id": "cli-dry-run-proj-2",
            "name": "CLI Dry Run Project 2",
            "slug": "cli-dry-run-2",
            "generation_schedule": {
                "frequency": "daily",
                "times": ["09:00"],
                "posts_per_batch": 2,
            },
            "created_at": "2026-07-04T00:00:00+00:00",
        }
        from data.sqlite_store import SQLiteStore

        store = SQLiteStore(data_dir=str(tmp_path), migrate=True)
        store.save_project_record(record)
        store.set_current_project_id(record["project_id"])

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")

        class Args:
            data_dir = str(tmp_path)
            dry_run = True

        assert cmd_scheduler_tick(Args()) == 0
        capsys.readouterr()

        last_gen = store.get_project_value(
            record["project_id"], "last_generation_at", default="__not_set__"
        )
        assert last_gen == "__not_set__", (
            "dry-run must not advance last_generation_at -- WR-06 leaves the "
            "next real tick skipping projects that were never actually generated"
        )

    def test_real_run_advances_last_generation_at(self, tmp_path, monkeypatch, capsys):
        from cli import cmd_scheduler_tick

        record = {
            "project_id": "cli-real-run-proj",
            "name": "CLI Real Run Project",
            "slug": "cli-real-run",
            "generation_schedule": {
                "frequency": "daily",
                "times": ["09:00"],
                "posts_per_batch": 2,
            },
            "created_at": "2026-07-04T00:00:00+00:00",
        }
        from data.sqlite_store import SQLiteStore

        store = SQLiteStore(data_dir=str(tmp_path), migrate=True)
        store.save_project_record(record)
        store.set_current_project_id(record["project_id"])

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")

        class Args:
            data_dir = str(tmp_path)
            dry_run = False

        assert cmd_scheduler_tick(Args()) == 0
        capsys.readouterr()

        last_gen = store.get_project_value(record["project_id"], "last_generation_at")
        assert last_gen is not None, (
            "real tick must persist last_generation_at (regression guard for WR-06)"
        )


class TestSchedulerProducerDryRunFlag:
    """Pin SchedulerProducer(dry_run=True) does not persist last_generation_at."""

    def test_dry_run_producer_does_not_write_last_generation_at(
        self, seeded_store, fixture_project
    ):
        project_id = fixture_project["project_id"]
        schedule = {"frequency": "daily", "times": ["09:00"], "posts_per_batch": 3}
        _set_schedule(seeded_store, project_id, schedule)

        from projects.manager import ProjectManager

        pm = ProjectManager(data_dir=str(seeded_store.data_dir))
        container = _FakeContainer(pm, _RealJobQueue(seeded_store), seeded_store)
        producer = SchedulerProducer(container, dry_run=True)

        producer.tick(now=datetime(2026, 7, 5, 9, 5))

        last_gen = seeded_store.get_project_value(
            project_id, "last_generation_at", default="__not_set__"
        )
        assert last_gen == "__not_set__"
