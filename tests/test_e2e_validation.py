"""E2E integration tests: migrate legacy JSON → exercise review lifecycle.

Bridges the S02 (SQLite migration) and S03 (compatibility mode) slices.
Sets up realistic legacy JSON fixtures, runs migration, then exercises
FeedbackManager, project managers, and deprecation warnings against
the migrated data.
"""

import json

import pytest

from data.sqlite_store import SQLiteStore
from feedback.manager import FeedbackManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post(platform="twitter", **overrides):
    """Build a minimal post_data dict for add_for_review."""
    post = {
        "platform": platform,
        "content_type": "tweet",
        "pillar": "growth",
        "hook_type": "question",
        "content": "Sample content for testing.",
    }
    post.update(overrides)
    return post


def _project_dir(tmp_path, project_id):
    """Return a path shaped like data/projects/{project_id}/."""
    p = tmp_path / "projects" / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _setup_legacy_data(tmp_path):
    """Create a realistic data directory with legacy JSON fixtures.

    Returns the data_dir Path containing:
    - projects.json (2 projects)
    - reviews.json (global: 1 pending, 1 scheduled)
    - projects/proj-a/settings.json
    - projects/proj-a/reviews.json (1 pending)
    - projects/proj-b/settings.json
    - projects/proj-b/reviews.json (1 approved)
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # --- Global projects.json ---
    (data_dir / "projects.json").write_text(json.dumps({
        "proj-a": {
            "project_id": "proj-a",
            "name": "Project Alpha",
            "slug": "project-alpha",
            "description": "First test project",
            "config": {},
            "settings": {},
            "generation_schedule": {},
        },
        "proj-b": {
            "project_id": "proj-b",
            "name": "Project Beta",
            "slug": "project-beta",
            "description": "Second test project",
            "config": {},
            "settings": {},
            "generation_schedule": {},
        },
    }))

    # --- Global reviews.json (2 reviews) ---
    (data_dir / "reviews.json").write_text(json.dumps({
        "rev-global-pending": {
            "review_id": "rev-global-pending",
            "status": "pending_review",
            "post_data": {"platform": "twitter", "content": "Global pending tweet"},
        },
        "rev-global-scheduled": {
            "review_id": "rev-global-scheduled",
            "status": "scheduled",
            "post_data": {"platform": "linkedin", "content": "Global scheduled post"},
            "scheduled_at": "2026-01-20T10:00:00",
        },
    }))

    # --- Project A directory ---
    proj_a = _project_dir(data_dir, "proj-a")
    (proj_a / "settings.json").write_text(json.dumps({
        "name": "Project Alpha",
        "language": "en",
        "platforms": ["twitter"],
    }))
    (proj_a / "reviews.json").write_text(json.dumps({
        "rev-a-pending": {
            "review_id": "rev-a-pending",
            "status": "pending_review",
            "post_data": {"platform": "twitter", "content": "Project A pending tweet"},
            "project_id": "proj-a",
        },
    }))

    # --- Project B directory ---
    proj_b = _project_dir(data_dir, "proj-b")
    (proj_b / "settings.json").write_text(json.dumps({
        "name": "Project Beta",
        "language": "en",
        "platforms": ["linkedin"],
    }))
    (proj_b / "reviews.json").write_text(json.dumps({
        "rev-b-approved": {
            "review_id": "rev-b-approved",
            "status": "approved",
            "post_data": {"platform": "linkedin", "content": "Project B approved post"},
            "project_id": "proj-b",
        },
    }))

    return data_dir


# ---------------------------------------------------------------------------
# 1. Full migration → review lifecycle
# ---------------------------------------------------------------------------


class TestE2EMigrationReviewLifecycle:
    """Bridge S02→S03: migrate legacy JSON, then exercise FeedbackManager
    lifecycle operations against migrated records."""

    def test_migrated_reviews_appear_in_feedback_manager(self, tmp_path):
        """After migration, FeedbackManager sees all migrated reviews."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)
        assert report.reviews_imported == 4  # 2 global + 1 proj-a + 1 proj-b
        assert not report.has_errors

        # FeedbackManager against the same data_dir (global scope)
        fm = FeedbackManager(data_dir=str(data_dir))

        pending = fm.get_pending_reviews()
        approved = fm.get_approved()
        scheduled = fm.get_scheduled()

        pending_ids = {r["review_id"] for r in pending}
        approved_ids = {r["review_id"] for r in approved}
        scheduled_ids = {r["review_id"] for r in scheduled}

        # Global + proj-a pending
        assert "rev-global-pending" in pending_ids
        assert "rev-a-pending" in pending_ids
        # proj-b approved
        assert "rev-b-approved" in approved_ids
        # Global scheduled
        assert "rev-global-scheduled" in scheduled_ids

    def test_approve_migrated_pending_review(self, tmp_path):
        """Approve a migrated pending review and verify persistence."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        fm = FeedbackManager(data_dir=str(data_dir))

        # Approve a globally-scoped migrated pending review
        ok = fm.approve("rev-global-pending", feedback="Looks great after migration")
        assert ok is True

        loaded = fm._load_review_record("rev-global-pending")
        assert loaded["status"] == "approved"
        assert loaded["feedback"] == "Looks great after migration"
        assert "approved_at" in loaded

        # No longer in pending
        pending_ids = {r["review_id"] for r in fm.get_pending_reviews()}
        assert "rev-global-pending" not in pending_ids

        # Now in approved
        approved_ids = {r["review_id"] for r in fm.get_approved()}
        assert "rev-global-pending" in approved_ids

    def test_reject_migrated_pending_review(self, tmp_path):
        """Reject a migrated pending review."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        fm = FeedbackManager(data_dir=str(data_dir))

        ok = fm.reject("rev-a-pending", feedback="Off brand")
        assert ok is True

        loaded = fm._load_review_record("rev-a-pending")
        assert loaded["status"] == "rejected"
        assert loaded["feedback"] == "Off brand"
        assert "rejected_at" in loaded

    def test_schedule_migrated_approved_review(self, tmp_path):
        """Schedule an already-approved migrated review."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        fm = FeedbackManager(data_dir=str(data_dir))

        # rev-b-approved is already approved after migration
        ok = fm.mark_scheduled("rev-b-approved", schedule_data={"slot": "2026-02-01T12:00:00"})
        assert ok is True

        loaded = fm._load_review_record("rev-b-approved")
        assert loaded["status"] == "scheduled"
        assert loaded["schedule_data"]["slot"] == "2026-02-01T12:00:00"

        scheduled_ids = {r["review_id"] for r in fm.get_scheduled()}
        assert "rev-b-approved" in scheduled_ids

    def test_new_review_after_migration_coexists(self, tmp_path):
        """Create a NEW review after migration — verify coexistence."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        fm = FeedbackManager(data_dir=str(data_dir))

        # Add a brand-new review post-migration
        new_record = fm.add_for_review(_make_post(platform="nostr", content="Fresh post-migration content"))
        new_id = new_record["review_id"]

        assert new_record["status"] == "pending_review"

        # The new review coexists with migrated ones
        pending = fm.get_pending_reviews()
        pending_ids = {r["review_id"] for r in pending}

        # Should have: migrated pending + the new one
        assert "rev-global-pending" in pending_ids
        assert "rev-a-pending" in pending_ids
        assert new_id in pending_ids

        # Approve the new review and verify
        fm.approve(new_id, feedback="Post-migration approval works")
        loaded = fm._load_review_record(new_id)
        assert loaded["status"] == "approved"

        # Stats should reflect all records
        stats = fm.get_stats()
        assert stats["total"] == 5  # 4 migrated + 1 new

    def test_stats_after_all_operations(self, tmp_path):
        """Verify get_stats() counts after lifecycle operations on migrated records."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        fm = FeedbackManager(data_dir=str(data_dir))

        # Starting state: 2 pending, 1 approved, 1 scheduled
        stats = fm.get_stats()
        assert stats["total"] == 4
        assert stats["pending"] == 2
        assert stats["approved"] == 1
        assert stats["scheduled"] == 1

        # Approve one pending
        fm.approve("rev-global-pending")
        # Reject the other pending
        fm.reject("rev-a-pending")
        # Schedule the approved one
        fm.mark_scheduled("rev-b-approved")

        stats = fm.get_stats()
        assert stats["total"] == 4
        assert stats["pending"] == 0
        assert stats["approved"] == 1      # rev-global-pending now approved
        assert stats["rejected"] == 1      # rev-a-pending now rejected
        assert stats["scheduled"] == 2     # rev-global-scheduled + rev-b-approved


# ---------------------------------------------------------------------------
# 2. Deprecation warnings after migration
# ---------------------------------------------------------------------------


class TestE2EDeprecationWarningsPostMigration:
    """Verify deprecation warnings fire when legacy JSON files still exist
    after migration."""

    def test_feedback_manager_warns_for_reviews_json(self, tmp_path):
        """FeedbackManager emits DeprecationWarning for reviews.json."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        # reviews.json still on disk after migration
        assert (data_dir / "reviews.json").exists()

        with pytest.warns(DeprecationWarning, match="reviews.json is deprecated"):
            FeedbackManager(data_dir=str(data_dir))

    def test_projects_manager_warns_for_projects_json(self, tmp_path):
        """projects.manager.ProjectManager emits DeprecationWarning for projects.json."""
        from projects.manager import ProjectManager

        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        # projects.json still on disk
        assert (data_dir / "projects.json").exists()

        with pytest.warns(DeprecationWarning, match="projects.json is deprecated"):
            ProjectManager(data_dir=str(data_dir))

    def test_data_project_manager_warns_for_projects_json(self, tmp_path):
        """data.project_manager.ProjectManager emits DeprecationWarning."""
        from data.project_manager import ProjectManager as DataProjectManager

        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        assert (data_dir / "projects.json").exists()

        with pytest.warns(DeprecationWarning, match="projects.json is deprecated"):
            DataProjectManager(data_dir=str(data_dir))


# ---------------------------------------------------------------------------
# 3. Idempotent migration → review operations
# ---------------------------------------------------------------------------


class TestE2EIdempotentMigrationReviewFlow:
    """Run migration twice then verify review operations work correctly."""

    def test_double_migration_no_duplicates(self, tmp_path):
        """Migrating twice produces no duplicate records."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)

        report1 = store.run_migration_report(dry_run=False)
        assert report1.reviews_imported == 4
        assert report1.projects_imported == 2

        report2 = store.run_migration_report(dry_run=False)
        assert report2.reviews_imported == 4  # Same counts
        assert report2.projects_imported == 2

        # No duplicates in the DB
        assert len(store.list_review_records()) == 4
        assert len(store.list_project_records()) == 2

    def test_review_operations_after_double_migration(self, tmp_path):
        """Full lifecycle: double-migrate, then approve/reject/schedule."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)
        store.run_migration_report(dry_run=False)  # Second run

        fm = FeedbackManager(data_dir=str(data_dir))

        # Verify starting state is correct
        pending = fm.get_pending_reviews()
        assert len(pending) == 2  # rev-global-pending, rev-a-pending

        # Approve one
        assert fm.approve("rev-global-pending", feedback="Post-double-migration approve") is True
        loaded = fm._load_review_record("rev-global-pending")
        assert loaded["status"] == "approved"

        # Reject one
        assert fm.reject("rev-a-pending", feedback="Post-double-migration reject") is True
        loaded = fm._load_review_record("rev-a-pending")
        assert loaded["status"] == "rejected"

        # Schedule the pre-approved one
        assert fm.mark_scheduled("rev-b-approved", schedule_data={"slot": "2026-03-01T10:00:00"}) is True
        loaded = fm._load_review_record("rev-b-approved")
        assert loaded["status"] == "scheduled"

        # Stats should be consistent
        stats = fm.get_stats()
        assert stats["total"] == 4
        assert stats["pending"] == 0
        assert stats["approved"] == 1     # rev-global-pending now approved
        assert stats["rejected"] == 1     # rev-a-pending rejected
        assert stats["scheduled"] == 2    # rev-global-scheduled + rev-b-approved

        # Verify no duplicate records via SQLiteStore directly
        assert len(store.list_review_records()) == 4


# ---------------------------------------------------------------------------
# 4. Data query validation against migrated data
# ---------------------------------------------------------------------------


class TestE2EDataQueryValidation:
    """Validate SQLiteStore query methods return migrated data with
    correct counts, fields, and fidelity."""

    def test_list_project_records_count_and_fields(self, tmp_path):
        """list_project_records returns 2 projects with expected keys."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        projects = store.list_project_records()
        assert len(projects) == 2

        by_id = {p["project_id"]: p for p in projects}
        assert "proj-a" in by_id
        assert "proj-b" in by_id

        pa = by_id["proj-a"]
        assert pa["name"] == "Project Alpha"
        assert pa["slug"] == "project-alpha"
        assert pa["project_id"] == "proj-a"
        assert "created_at" in pa

        pb = by_id["proj-b"]
        assert pb["name"] == "Project Beta"
        assert pb["slug"] == "project-beta"
        assert pb["project_id"] == "proj-b"

    def test_list_review_records_count_and_statuses(self, tmp_path):
        """list_review_records returns 4 reviews with correct status distribution."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        reviews = store.list_review_records()
        assert len(reviews) == 4

        by_status: dict = {}
        for r in reviews:
            by_status.setdefault(r["status"], []).append(r)

        # 2 pending (global-pending + proj-a-pending), 1 approved, 1 scheduled
        assert len(by_status["pending_review"]) == 2
        assert len(by_status["approved"]) == 1
        assert len(by_status["scheduled"]) == 1

    def test_list_scheduled_records_with_metadata(self, tmp_path):
        """list_scheduled_records returns scheduled_posts.json data with metadata."""
        data_dir = _setup_legacy_data(tmp_path)
        # Add a scheduled_posts.json with a known scheduled post
        (data_dir / "scheduled_posts.json").write_text(json.dumps([
            {
                "post_id": "sched-legacy-1",
                "project_id": "proj-a",
                "status": "scheduled",
                "scheduled_at": "2026-02-15T09:00:00",
                "post_data": {"platform": "twitter", "content": "Scheduled from legacy"},
            },
        ]))

        db_path = data_dir / "test.sqlite3"
        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        report = store.run_migration_report(dry_run=False)
        assert report.scheduled_posts_imported == 1
        assert not report.has_errors

        scheduled = store.list_scheduled_records()
        assert len(scheduled) == 1

        rec = scheduled[0]
        assert rec["scheduled_at"] == "2026-02-15T09:00:00"
        assert rec["status"] == "scheduled"
        assert rec["project_id"] == "proj-a"
        assert rec["post_data"]["content"] == "Scheduled from legacy"
        assert rec["post_data"]["platform"] == "twitter"

    def test_field_level_fidelity_of_migrated_review(self, tmp_path):
        """A specific migrated review's post_data.content matches the legacy JSON source."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        # rev-global-scheduled: content should be "Global scheduled post"
        record = store.get_review_record("rev-global-scheduled")
        assert record is not None
        assert record["post_data"]["content"] == "Global scheduled post"
        assert record["post_data"]["platform"] == "linkedin"
        assert record["status"] == "scheduled"
        assert record["scheduled_at"] == "2026-01-20T10:00:00"

        # rev-b-approved: content from proj-b reviews.json
        record_b = store.get_review_record("rev-b-approved")
        assert record_b is not None
        assert record_b["post_data"]["content"] == "Project B approved post"
        assert record_b["post_data"]["platform"] == "linkedin"
        assert record_b["status"] == "approved"
        assert record_b["project_id"] == "proj-b"

    def test_project_kv_settings_imported_correctly(self, tmp_path):
        """Project KV settings from legacy settings.json are accessible via store."""
        data_dir = _setup_legacy_data(tmp_path)
        db_path = data_dir / "test.sqlite3"

        store = SQLiteStore(data_dir=data_dir, db_path=db_path, migrate=False)
        store.run_migration_report(dry_run=False)

        # proj-a settings had name, language, platforms
        settings_a = store.get_project_value("proj-a", "settings")
        assert settings_a is not None
        assert settings_a["name"] == "Project Alpha"
        assert settings_a["language"] == "en"
        assert settings_a["platforms"] == ["twitter"]

        # proj-b settings
        settings_b = store.get_project_value("proj-b", "settings")
        assert settings_b is not None
        assert settings_b["name"] == "Project Beta"
        assert settings_b["language"] == "en"
        assert settings_b["platforms"] == ["linkedin"]
