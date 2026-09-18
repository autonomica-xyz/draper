#!/usr/bin/env python3
"""Tests for MigrationReport and SQLiteStore.run_migration_report().

Covers:
- MigrationReport dataclass construction and summary()
- Dry-run import (in-memory, no DB file written)
- Actual import (populates SQLite)
- Idempotency (running twice yields same counts)
- Malformed JSON handling (error logged, no crash)
- Empty data directory (zero counts, no errors)
"""

import json
import argparse
from pathlib import Path

import pytest

from data.sqlite_store import MigrationReport, SQLiteStore

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_data_dir(tmp_path: Path) -> Path:
    """Create a temp data directory with sample legacy JSON files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # projects.json
    (data_dir / "projects.json").write_text(json.dumps({
        "proj-1": {
            "project_id": "proj-1",
            "name": "Test Project",
            "slug": "test-project",
            "description": "A test project",
            "config": {},
            "settings": {},
            "generation_schedule": {},
        },
        "proj-2": {
            "project_id": "proj-2",
            "name": "Second Project",
            "slug": "second-project",
        },
    }))

    # Project data directories
    proj_dir = data_dir / "projects" / "proj-1"
    proj_dir.mkdir(parents=True)
    (proj_dir / "settings.json").write_text(json.dumps({
        "name": "Test Project",
        "language": "en",
        "platforms": ["twitter", "linkedin"],
    }))
    (proj_dir / "secrets.json").write_text(json.dumps({
        "api_key": "test-key-123",
    }))
    (proj_dir / "reviews.json").write_text(json.dumps({
        "rev-100": {
            "review_id": "rev-100",
            "status": "pending_review",
            "post_data": {"platform": "twitter", "content": "Hello world"},
        },
        "rev-101": {
            "review_id": "rev-101",
            "status": "approved",
            "post_data": {"platform": "linkedin", "content": "Professional post"},
        },
    }))

    # Global reviews.json
    (data_dir / "reviews.json").write_text(json.dumps({
        "rev-200": {
            "review_id": "rev-200",
            "status": "pending_review",
            "post_data": {"platform": "twitter", "content": "Global review"},
        },
    }))

    # scheduled_posts.json
    (data_dir / "scheduled_posts.json").write_text(json.dumps([
        {
            "post_id": "sched-1",
            "project_id": "proj-1",
            "status": "scheduled",
            "scheduled_at": "2026-01-15T10:00:00",
            "post_data": {"platform": "twitter", "content": "Scheduled tweet"},
        },
        {
            "post_id": "sched-2",
            "project_id": "proj-2",
            "status": "scheduled",
            "scheduled_at": "2026-01-16T14:00:00",
            "post_data": {"platform": "linkedin", "content": "Scheduled post"},
        },
    ]))

    return data_dir


@pytest.fixture
def store_with_sample_data(sample_data_dir: Path) -> SQLiteStore:
    """SQLiteStore pointing at the sample data directory (no auto-migrate)."""
    db_path = sample_data_dir / "test.sqlite3"
    return SQLiteStore(data_dir=sample_data_dir, db_path=db_path, migrate=False)


# ---------------------------------------------------------------------------
# MigrationReport unit tests
# ---------------------------------------------------------------------------


class TestMigrationReport:
    def test_initial_counts_are_zero(self):
        report = MigrationReport()
        assert report.projects_imported == 0
        assert report.reviews_imported == 0
        assert report.scheduled_posts_imported == 0
        assert report.settings_imported == 0
        assert report.secrets_imported == 0
        assert report.errors == []
        assert not report.has_errors

    def test_add_error(self):
        report = MigrationReport()
        report.add_error("reviews.json", "Malformed JSON: trailing comma")
        assert len(report.errors) == 1
        assert report.errors[0]["file"] == "reviews.json"
        assert "Malformed" in report.errors[0]["error"]
        assert report.has_errors

    def test_summary_with_counts_and_errors(self):
        report = MigrationReport(
            projects_imported=2,
            reviews_imported=5,
            scheduled_posts_imported=3,
            settings_imported=1,
            secrets_imported=1,
        )
        report.add_error("bad.json", "Parse error")
        text = report.summary()
        assert "Projects imported:       2" in text
        assert "Reviews imported:         5" in text
        assert "Scheduled posts imported: 3" in text
        assert "Settings imported:        1" in text
        assert "Secrets imported:         1" in text
        assert "Errors (1)" in text
        assert "bad.json" in text
        assert "Parse error" in text

    def test_summary_no_errors(self):
        report = MigrationReport()
        text = report.summary()
        assert "No errors" in text
        assert "Errors" not in text


def test_migration_imports_analytics_json_files(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "typefully_metrics.json").write_text(
        json.dumps([{"post_id": "p1", "likes": 12}])
    )
    (data_dir / "content_recommendations.json").write_text(
        json.dumps({"recommendations": ["shorter hooks"]})
    )

    store = SQLiteStore(data_dir=data_dir, db_path=data_dir / "test.sqlite3", migrate=False)
    report = store.run_migration_report(dry_run=False)

    assert report.analytics_imported == 2
    snapshots = {item["source_path"]: item["data"] for item in store.list_analytics_snapshots()}
    assert snapshots["typefully_metrics.json"] == [{"post_id": "p1", "likes": 12}]
    assert snapshots["content_recommendations.json"] == {
        "recommendations": ["shorter hooks"]
    }


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_returns_correct_counts(self, store_with_sample_data, sample_data_dir):
        report = store_with_sample_data.run_migration_report(dry_run=True)
        # 2 from projects.json
        assert report.projects_imported == 2
        # 2 from project reviews + 1 from global reviews = 3
        assert report.reviews_imported == 3
        # 2 from scheduled_posts.json
        assert report.scheduled_posts_imported == 2
        # 1 from proj-1/settings.json
        assert report.settings_imported == 1
        # 1 from proj-1/secrets.json
        assert report.secrets_imported == 1
        assert not report.has_errors

    def test_dry_run_does_not_modify_real_store_db(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "projects.json").write_text(json.dumps({
            "p1": {"project_id": "p1", "name": "P1"},
        }))
        db_path = tmp_path / "real.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)

        # Precondition: no records in the real store
        assert store.list_project_records() == []

        # Dry-run should import into a throwaway temp DB, not self
        store.run_migration_report(dry_run=True)

        # Real store should still be empty
        assert store.list_project_records() == []

    def test_dry_run_does_not_mark_legacy_imported(self, store_with_sample_data):
        store_with_sample_data.run_migration_report(dry_run=True)
        # The real store should still not have legacy_imported set
        assert store_with_sample_data.get_meta("legacy_imported") is None


# ---------------------------------------------------------------------------
# Actual import tests
# ---------------------------------------------------------------------------


class TestActualImport:
    def test_actual_import_populates_sqlite(self, store_with_sample_data, sample_data_dir):
        report = store_with_sample_data.run_migration_report(dry_run=False)
        assert report.projects_imported == 2
        assert report.reviews_imported == 3
        assert report.scheduled_posts_imported == 2
        assert not report.has_errors

        # Verify records are actually in the database
        projects = store_with_sample_data.list_project_records()
        assert len(projects) == 2

        reviews = store_with_sample_data.list_review_records()
        assert len(reviews) == 3

        scheduled = store_with_sample_data.list_scheduled_records()
        assert len(scheduled) == 2

    def test_actual_import_sets_legacy_flag(self, store_with_sample_data):
        store_with_sample_data.run_migration_report(dry_run=False)
        assert store_with_sample_data.get_meta("legacy_imported") == "1"


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_running_twice_yields_same_counts(self, store_with_sample_data):
        report1 = store_with_sample_data.run_migration_report(dry_run=False)
        report2 = store_with_sample_data.run_migration_report(dry_run=False)

        # Second run should find same counts because INSERT OR IGNORE skips dupes
        assert report2.projects_imported == report1.projects_imported
        assert report2.reviews_imported == report1.reviews_imported
        assert report2.scheduled_posts_imported == report1.scheduled_posts_imported

        # Verify database still has same counts
        assert len(store_with_sample_data.list_project_records()) == report1.projects_imported
        assert len(store_with_sample_data.list_review_records()) == report1.reviews_imported
        assert len(store_with_sample_data.list_scheduled_records()) == report1.scheduled_posts_imported


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------


class TestMalformedInputs:
    def test_malformed_reviews_json_logs_error(self, store_with_sample_data, sample_data_dir):
        # Overwrite reviews.json with malformed content
        (sample_data_dir / "reviews.json").write_text("{invalid json,,,}")

        report = store_with_sample_data.run_migration_report(dry_run=True)
        assert report.has_errors
        assert any("reviews.json" in e["file"] for e in report.errors)
        assert any("Malformed JSON" in e["error"] for e in report.errors)

    def test_malformed_scheduled_posts_json_logs_error(self, store_with_sample_data, sample_data_dir):
        (sample_data_dir / "scheduled_posts.json").write_text("not json at all")

        report = store_with_sample_data.run_migration_report(dry_run=True)
        assert report.has_errors
        assert any("scheduled_posts.json" in e["file"] for e in report.errors)

    def test_malformed_project_settings_logs_error(self, store_with_sample_data, sample_data_dir):
        proj_dir = sample_data_dir / "projects" / "proj-1"
        (proj_dir / "settings.json").write_text("{{bad}}")

        report = store_with_sample_data.run_migration_report(dry_run=True)
        assert report.has_errors
        assert any("settings.json" in e["file"] for e in report.errors)


class TestEmptyDataDirectory:
    def test_empty_directory_returns_zero_counts(self, tmp_path):
        data_dir = tmp_path / "empty_data"
        data_dir.mkdir()
        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)

        report = store.run_migration_report(dry_run=True)
        assert report.projects_imported == 0
        assert report.reviews_imported == 0
        assert report.scheduled_posts_imported == 0
        assert report.settings_imported == 0
        assert report.secrets_imported == 0
        assert not report.has_errors

    def test_empty_directory_actual_import(self, tmp_path):
        data_dir = tmp_path / "empty_data"
        data_dir.mkdir()
        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)

        report = store.run_migration_report(dry_run=False)
        assert report.projects_imported == 0
        assert report.reviews_imported == 0
        assert not report.has_errors
        assert store.get_meta("legacy_imported") == "1"


# ---------------------------------------------------------------------------
# cmd_migrate CLI-level tests (argparse Namespace invocation)
# ---------------------------------------------------------------------------


def _namespace(dry_run: bool = False, data_dir: str | None = None) -> argparse.Namespace:
    """Build an argparse.Namespace matching the migrate subparser output."""
    return argparse.Namespace(dry_run=dry_run, data_dir=data_dir)


class TestCmdMigrateDryRun:
    """Exercises cmd_migrate() directly via argparse Namespace objects."""

    def test_dry_run_empty_directory(self, tmp_path, capsys):
        from cli import cmd_migrate

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        exit_code = cmd_migrate(_namespace(dry_run=True, data_dir=str(empty_dir)))
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "Projects imported:       0" in output
        assert "Reviews imported:         0" in output
        assert "No errors" in output

    def test_dry_run_with_data(self, tmp_path, capsys):
        from cli import cmd_migrate

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # projects.json
        (data_dir / "projects.json").write_text(json.dumps({
            "p1": {"project_id": "p1", "name": "Alpha"},
            "p2": {"project_id": "p2", "name": "Beta"},
        }))

        # Global reviews.json
        (data_dir / "reviews.json").write_text(json.dumps({
            "r1": {"review_id": "r1", "status": "pending_review", "post_data": {"content": "hi"}},
        }))

        exit_code = cmd_migrate(_namespace(dry_run=True, data_dir=str(data_dir)))
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "Projects imported:       2" in output
        assert "Reviews imported:         1" in output
        assert "No errors" in output

    def test_dry_run_leaves_real_store_empty(self, tmp_path):
        from cli import cmd_migrate
        from data.sqlite_store import SQLiteStore

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "projects.json").write_text(json.dumps({
            "p1": {"project_id": "p1", "name": "Alpha"},
        }))

        exit_code = cmd_migrate(_namespace(dry_run=True, data_dir=str(data_dir)))
        assert exit_code == 0

        # The real DB created by cmd_migrate's store should have no records
        # because dry-run imports into a throwaway temp DB, not the store's DB.
        db_path = data_dir / "marketing_pipeline.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        assert store.list_project_records() == []
        assert store.list_review_records() == []


class TestCmdMigrateActual:
    """Actual migration via cmd_migrate (writes to SQLite)."""

    def test_actual_migration_records_queryable(self, tmp_path, capsys):
        from cli import cmd_migrate
        from data.sqlite_store import SQLiteStore

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        (data_dir / "projects.json").write_text(json.dumps({
            "proj-x": {"project_id": "proj-x", "name": "Project X", "slug": "project-x"},
        }))

        # Project-scoped reviews
        proj_dir = data_dir / "projects" / "proj-x"
        proj_dir.mkdir(parents=True)
        (proj_dir / "reviews.json").write_text(json.dumps({
            "rev-1": {
                "review_id": "rev-1",
                "status": "approved",
                "post_data": {"platform": "twitter", "content": "Hello"},
            },
        }))
        (proj_dir / "settings.json").write_text(json.dumps({"name": "Project X", "language": "en"}))

        exit_code = cmd_migrate(_namespace(dry_run=False, data_dir=str(data_dir)))
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "Migration complete" in output

        # Verify records via a fresh store reading the same DB
        db_path = data_dir / "marketing_pipeline.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)

        projects = store.list_project_records()
        assert len(projects) == 1
        assert projects[0]["project_id"] == "proj-x"
        assert projects[0]["name"] == "Project X"

        reviews = store.list_review_records(project_id="proj-x")
        assert len(reviews) == 1
        assert reviews[0]["review_id"] == "rev-1"
        assert reviews[0]["status"] == "approved"

        settings = store.get_project_value("proj-x", "settings")
        assert settings["name"] == "Project X"
        assert settings["language"] == "en"

    def test_idempotency_via_cli(self, tmp_path, capsys):
        from cli import cmd_migrate
        from data.sqlite_store import SQLiteStore

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        (data_dir / "projects.json").write_text(json.dumps({
            "p1": {"project_id": "p1", "name": "One"},
        }))
        (data_dir / "reviews.json").write_text(json.dumps({
            "r1": {"review_id": "r1", "status": "pending_review", "post_data": {"content": "x"}},
        }))

        # First run
        exit1 = cmd_migrate(_namespace(dry_run=False, data_dir=str(data_dir)))
        assert exit1 == 0

        # Second run — should succeed, records unchanged
        exit2 = cmd_migrate(_namespace(dry_run=False, data_dir=str(data_dir)))
        assert exit2 == 0

        db_path = data_dir / "marketing_pipeline.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        assert len(store.list_project_records()) == 1
        assert len(store.list_review_records()) == 1

    def test_data_dir_override(self, tmp_path, capsys):
        from cli import cmd_migrate

        custom_dir = tmp_path / "custom_location"
        custom_dir.mkdir()

        (custom_dir / "projects.json").write_text(json.dumps({
            "p-override": {"project_id": "p-override", "name": "Override"},
        }))

        exit_code = cmd_migrate(_namespace(dry_run=True, data_dir=str(custom_dir)))
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "Projects imported:       1" in output
        assert "Override" in output or "custom_location" in output

    def test_nonexistent_data_dir_exits_1(self, tmp_path, capsys):
        from cli import cmd_migrate

        exit_code = cmd_migrate(
            _namespace(dry_run=True, data_dir=str(tmp_path / "nope"))
        )
        assert exit_code == 1

        output = capsys.readouterr().out
        assert "not found" in output

    def test_malformed_json_via_cli_exits_1(self, tmp_path, capsys):
        from cli import cmd_migrate

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "reviews.json").write_text("{broken json!!!")

        exit_code = cmd_migrate(_namespace(dry_run=True, data_dir=str(data_dir)))
        assert exit_code == 1

        output = capsys.readouterr().out
        assert "error" in output.lower()


# ---------------------------------------------------------------------------
# Subprocess end-to-end test
# ---------------------------------------------------------------------------


class TestSubprocessCLI:
    """Prove the CLI entry point works end-to-end via subprocess."""

    def test_cli_migrate_dry_run_subprocess(self, tmp_path):
        import subprocess
        import sys

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        (data_dir / "projects.json").write_text(json.dumps({
            "sp1": {"project_id": "sp1", "name": "SubProject"},
        }))
        (data_dir / "reviews.json").write_text(json.dumps({
            "sr1": {
                "review_id": "sr1",
                "status": "pending_review",
                "post_data": {"platform": "twitter", "content": "Subprocess test"},
            },
        }))
        (data_dir / "scheduled_posts.json").write_text(json.dumps([
            {"post_id": "ss1", "project_id": "sp1", "status": "scheduled",
             "scheduled_at": "2026-02-01T10:00:00", "post_data": {"content": "sched"}},
        ]))

        result = subprocess.run(
            [sys.executable, "cli.py", "migrate", "--dry-run", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=30,
        )

        assert result.returncode == 0
        assert "Projects imported:       1" in result.stdout
        assert "Reviews imported:         1" in result.stdout
        assert "Scheduled posts imported: 1" in result.stdout
        assert "No errors" in result.stdout

    def test_cli_migrate_actual_subprocess(self, tmp_path):
        import subprocess
        import sys

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        (data_dir / "projects.json").write_text(json.dumps({
            "sp2": {"project_id": "sp2", "name": "LiveProject", "slug": "live-project"},
        }))

        result = subprocess.run(
            [sys.executable, "cli.py", "migrate", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=30,
        )

        assert result.returncode == 0
        assert "Migration complete" in result.stdout

        # Verify DB exists and has the record
        db_path = data_dir / "marketing_pipeline.sqlite3"
        assert db_path.exists()

        from data.sqlite_store import SQLiteStore

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        projects = store.list_project_records()
        assert len(projects) == 1
        assert projects[0]["name"] == "LiveProject"

    def test_cli_help_flag(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "cli.py", "migrate", "--help"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=15,
        )
        assert result.returncode == 0
        assert "--dry-run" in result.stdout
        assert "--data-dir" in result.stdout


# ---------------------------------------------------------------------------
# Field-by-field fidelity checks
# ---------------------------------------------------------------------------


class TestFieldFidelity:
    """After migration, verify specific field values match source JSON."""

    def test_review_field_fidelity(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        source_review = {
            "review_id": "fidelity-001",
            "status": "pending_review",
            "post_data": {
                "platform": "linkedin",
                "content": "Fidelity test post",
                "pillar": "thought-leadership",
                "hook_type": "question",
                "project_id": "fidelity-proj",
            },
            "feedback": "Great content",
            "project_id": "fidelity-proj",
        }
        (data_dir / "reviews.json").write_text(json.dumps({"fidelity-001": source_review}))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.reviews_imported == 1
        assert not report.has_errors

        record = store.get_review_record("fidelity-001")
        assert record is not None
        assert record["review_id"] == "fidelity-001"
        assert record["status"] == "pending_review"
        assert record["post_data"]["platform"] == "linkedin"
        assert record["post_data"]["content"] == "Fidelity test post"
        assert record["post_data"]["pillar"] == "thought-leadership"
        assert record["post_data"]["hook_type"] == "question"
        assert record["feedback"] == "Great content"
        assert record["project_id"] == "fidelity-proj"

    def test_project_field_fidelity(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        source_project = {
            "project_id": "fidelity-p1",
            "name": "Fidelity Corp",
            "slug": "fidelity-corp",
            "description": "A fidelity test project",
            "config": {"timezone": "UTC"},
            "settings": {"language": "en", "platforms": ["twitter", "linkedin"]},
            "generation_schedule": {"frequency": "daily"},
        }
        (data_dir / "projects.json").write_text(
            json.dumps({"fidelity-p1": source_project})
        )

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.projects_imported == 1
        assert not report.has_errors

        record = store.get_project_record("fidelity-p1")
        assert record is not None
        assert record["project_id"] == "fidelity-p1"
        assert record["name"] == "Fidelity Corp"
        assert record["slug"] == "fidelity-corp"
        assert record["description"] == "A fidelity test project"
        assert record["config"] == {"timezone": "UTC"}
        assert record["settings"] == {"language": "en", "platforms": ["twitter", "linkedin"]}
        assert record["generation_schedule"] == {"frequency": "daily"}

    def test_scheduled_post_field_fidelity(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        source_post = {
            "post_id": "sched-fid-1",
            "project_id": "fidelity-p1",
            "status": "scheduled",
            "scheduled_at": "2026-03-15T09:00:00",
            "post_data": {
                "platform": "twitter",
                "content": "Scheduled fidelity test",
            },
        }
        (data_dir / "scheduled_posts.json").write_text(json.dumps([source_post]))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.scheduled_posts_imported == 1
        assert not report.has_errors

        record = store.get_scheduled_record("sched-fid-1")
        assert record is not None
        assert record["post_id"] == "sched-fid-1"
        assert record["project_id"] == "fidelity-p1"
        assert record["status"] == "scheduled"
        assert record["scheduled_at"] == "2026-03-15T09:00:00"
        assert record["post_data"]["platform"] == "twitter"
        assert record["post_data"]["content"] == "Scheduled fidelity test"

    def test_project_settings_and_secrets_fidelity(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        proj_dir = data_dir / "projects" / "fid-secrets"
        proj_dir.mkdir(parents=True)

        source_settings = {
            "name": "Secrets Test",
            "language": "de",
            "platforms": ["nostr"],
            "provider_mapping": {"twitter": "typefully"},
        }
        source_secrets = {
            "typefully_api_key": "tfk_test123",
            "nostr_private_key": "nsec_test",
        }
        (proj_dir / "settings.json").write_text(json.dumps(source_settings))
        (proj_dir / "secrets.json").write_text(json.dumps(source_secrets))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.settings_imported == 1
        assert report.secrets_imported == 1

        settings = store.get_project_value("fid-secrets", "settings")
        assert settings["name"] == "Secrets Test"
        assert settings["language"] == "de"
        assert settings["platforms"] == ["nostr"]

        secrets = store.get_project_value("fid-secrets", "secrets")
        assert secrets["typefully_api_key"] == "tfk_test123"
        assert secrets["nostr_private_key"] == "nsec_test"

        provider_mapping = store.get_project_value("fid-secrets", "provider_mapping")
        assert provider_mapping == {"twitter": "typefully"}


# ---------------------------------------------------------------------------
# Additional negative / edge-case tests
# ---------------------------------------------------------------------------


class TestReviewsEdgeCases:
    """Edge cases for review import: list format, non-dict entries, empty objects."""

    def test_reviews_as_list_format(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        reviews_list = [
            {"review_id": "list-1", "status": "approved", "post_data": {"content": "a"}},
            {"review_id": "list-2", "status": "pending_review", "post_data": {"content": "b"}},
        ]
        (data_dir / "reviews.json").write_text(json.dumps(reviews_list))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.reviews_imported == 2
        assert not report.has_errors

        reviews = store.list_review_records()
        ids = {r["review_id"] for r in reviews}
        assert "list-1" in ids
        assert "list-2" in ids

    def test_reviews_with_non_dict_entries_skipped(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        mixed_data = {
            "good-1": {"review_id": "good-1", "status": "approved", "post_data": {"content": "ok"}},
            "bad-string": "not a dict",
            "bad-number": 42,
            "bad-null": None,
            "bad-list": [1, 2, 3],
            "good-2": {"review_id": "good-2", "status": "pending_review", "post_data": {"content": "ok2"}},
        }
        (data_dir / "reviews.json").write_text(json.dumps(mixed_data))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.reviews_imported == 2
        assert not report.has_errors  # Non-dict entries are silently skipped

    def test_empty_reviews_dict(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        (data_dir / "reviews.json").write_text(json.dumps({}))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.reviews_imported == 0
        assert not report.has_errors

    def test_scheduled_posts_non_dict_entries_skipped(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        (data_dir / "scheduled_posts.json").write_text(json.dumps([
            {"post_id": "s1", "status": "scheduled", "scheduled_at": "2026-01-01T00:00:00",
             "post_data": {"content": "ok"}},
            "not a dict",
            42,
            {"post_id": "s2", "status": "scheduled", "scheduled_at": "2026-01-02T00:00:00",
             "post_data": {"content": "ok2"}},
        ]))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.scheduled_posts_imported == 2
        assert not report.has_errors

    def test_scheduled_posts_as_dict_is_rejected(self, tmp_path):
        """scheduled_posts.json is expected to be a list. A dict should produce an error."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        (data_dir / "scheduled_posts.json").write_text(json.dumps({"s1": {"post_id": "s1"}}))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.scheduled_posts_imported == 0
        assert report.has_errors
        assert any("scheduled_posts.json" in e["file"] for e in report.errors)

    def test_projects_json_non_dict_entries_skipped(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        mixed_projects = {
            "p1": {"project_id": "p1", "name": "Valid"},
            "bad": "not a dict",
            "p2": {"project_id": "p2", "name": "Also Valid"},
        }
        (data_dir / "projects.json").write_text(json.dumps(mixed_projects))

        db_path = tmp_path / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)

        assert report.projects_imported == 2
        assert not report.has_errors
