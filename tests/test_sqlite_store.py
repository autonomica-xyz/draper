#!/usr/bin/env python3
"""Comprehensive tests for SQLiteStore CRUD operations.

Covers all public methods on SQLiteStore:
- Projects: save, get, get_by_name, get_by_slug, list, delete
- Reviews: save, get, list (with filters), normalize
- Scheduled posts: save, get, list, delete, normalize
- Jobs: enqueue, save, get, list, claim, complete, fail, cancel, stats
- Project KV: set, get
- Current state: set, get, clear
- Meta: set, get
- Legacy import (basic coverage)

Tests use isolated temp databases (migrate=False) to avoid side effects.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator

import pytest

from data.sqlite_store import SQLiteStore, dumps, loads, new_id, slugify, utc_now


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> Generator[SQLiteStore, None, None]:
    """Provide a fresh SQLiteStore backed by a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        s = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
        yield s


@pytest.fixture
def populated_store(store: SQLiteStore) -> SQLiteStore:
    """Store with a project and a review pre-populated."""
    store.save_project_record(
        {
            "project_id": "proj-1",
            "name": "Test Project",
            "description": "A test project",
            "config": {"theme": "dark"},
            "settings": {"language": "en"},
            "generation_schedule": {"daily": True},
        }
    )
    store.save_review_record(
        {
            "review_id": "rev-1",
            "project_id": "proj-1",
            "status": "pending_review",
            "channel": "CLI",
            "post_data": {"platform": "twitter", "content": "Hello world"},
            "feedback": None,
        }
    )
    return store


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_review(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a minimal review record with optional overrides."""
    base = {
        "review_id": f"rev-{new_id()}",
        "project_id": "proj-1",
        "status": "pending_review",
        "channel": "CLI",
        "post_data": {"platform": "twitter", "content": "Test content"},
        "feedback": None,
    }
    if overrides:
        base.update(overrides)
    return base


def _make_scheduled(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a minimal scheduled post record."""
    base = {
        "post_id": f"sched-{new_id()}",
        "project_id": "proj-1",
        "status": "scheduled",
        "scheduled_at": utc_now(),
        "post_data": {"platform": "twitter", "content": "Scheduled content"},
    }
    if overrides:
        base.update(overrides)
    return base


# ===========================================================================
# Utility functions
# ===========================================================================


class TestUtilities:
    def test_utc_now_returns_iso_string(self):
        result = utc_now()
        assert isinstance(result, str)
        # Should parse as ISO datetime
        datetime.fromisoformat(result)

    def test_slugify_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_slugify_special_chars(self):
        assert slugify("  Foo & Bar!!  ") == "foo-bar"

    def test_slugify_empty(self):
        assert slugify("") == "project"

    def test_new_id_no_prefix(self):
        val = new_id()
        assert isinstance(val, str)
        assert len(val) == 32  # uuid4 hex

    def test_new_id_with_prefix(self):
        val = new_id("job_")
        assert val.startswith("job_")
        assert len(val) == 36  # prefix + 32 hex

    def test_dumps_none(self):
        assert dumps(None) == "{}"

    def test_dumps_dict(self):
        result = dumps({"a": 1})
        assert json.loads(result) == {"a": 1}

    def test_loads_none(self):
        assert loads(None) == {}

    def test_loads_empty_string(self):
        assert loads("") == {}

    def test_loads_valid_json(self):
        assert loads('{"key": "val"}') == {"key": "val"}

    def test_loads_invalid_json(self):
        assert loads("not json") == {}

    def test_loads_with_default(self):
        assert loads(None, default=[]) == []


# ===========================================================================
# Meta table
# ===========================================================================


class TestMeta:
    def test_set_and_get(self, store: SQLiteStore):
        store.set_meta("test_key", "test_value")
        assert store.get_meta("test_key") == "test_value"

    def test_get_nonexistent(self, store: SQLiteStore):
        assert store.get_meta("nonexistent") is None

    def test_set_overwrites(self, store: SQLiteStore):
        store.set_meta("k", "v1")
        store.set_meta("k", "v2")
        assert store.get_meta("k") == "v2"

    def test_set_empty_value(self, store: SQLiteStore):
        store.set_meta("k", "")
        assert store.get_meta("k") == ""

    def test_multiple_keys(self, store: SQLiteStore):
        store.set_meta("a", "1")
        store.set_meta("b", "2")
        assert store.get_meta("a") == "1"
        assert store.get_meta("b") == "2"


# ===========================================================================
# Projects CRUD
# ===========================================================================


class TestProjectsCRUD:
    def test_save_and_get(self, store: SQLiteStore):
        record = {
            "project_id": "p1",
            "name": "My Project",
            "description": "Desc",
            "config": {"key": "value"},
            "settings": {"lang": "en"},
            "generation_schedule": {"daily": True},
        }
        store.save_project_record(record)
        got = store.get_project_record("p1")
        assert got is not None
        assert got["project_id"] == "p1"
        assert got["name"] == "My Project"
        assert got["description"] == "Desc"
        assert got["config"] == {"key": "value"}
        assert got["settings"] == {"lang": "en"}
        assert got["generation_schedule"] == {"daily": True}
        assert got["slug"] == "my-project"
        assert "created_at" in got

    def test_get_nonexistent(self, store: SQLiteStore):
        assert store.get_project_record("nope") is None

    def test_save_with_replace_true_updates(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Old"})
        store.save_project_record({"project_id": "p1", "name": "New", "description": "Updated"})
        got = store.get_project_record("p1")
        assert got["name"] == "New"
        assert got["description"] == "Updated"

    def test_save_with_replace_false_no_overwrite(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "First"})
        store.save_project_record({"project_id": "p1", "name": "Second"}, replace=False)
        got = store.get_project_record("p1")
        assert got["name"] == "First"

    def test_slug_auto_generated(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Hello World!"})
        got = store.get_project_record("p1")
        assert got["slug"] == "hello-world"

    def test_slug_preserved_when_provided(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Name", "slug": "custom-slug"})
        got = store.get_project_record("p1")
        assert got["slug"] == "custom-slug"

    def test_get_by_name(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Alpha"})
        result = store.get_project_record_by_name("Alpha")
        assert result is not None
        assert result["project_id"] == "p1"

    def test_get_by_name_case_insensitive(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Alpha"})
        result = store.get_project_record_by_name("alpha")
        assert result is not None
        assert result["project_id"] == "p1"

    def test_get_by_name_nonexistent(self, store: SQLiteStore):
        assert store.get_project_record_by_name("Nope") is None

    def test_get_by_slug(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Alpha"})
        result = store.get_project_record_by_slug("alpha")
        assert result is not None
        assert result["project_id"] == "p1"

    def test_get_by_slug_nonexistent(self, store: SQLiteStore):
        assert store.get_project_record_by_slug("nope") is None

    def test_list_project_records(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Beta"})
        store.save_project_record({"project_id": "p2", "name": "Alpha"})
        records = store.list_project_records()
        assert len(records) == 2
        # Should be sorted by name case-insensitive
        names = [r["name"] for r in records]
        assert names == sorted(names, key=str.lower)

    def test_list_excludes_deleted(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "A"})
        store.save_project_record({"project_id": "p2", "name": "B"})
        store.delete_project_record("p1")
        records = store.list_project_records()
        assert len(records) == 1
        assert records[0]["project_id"] == "p2"

    def test_delete_project(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "ToDelete"})
        assert store.delete_project_record("p1") is True
        assert store.get_project_record("p1") is None

    def test_delete_nonexistent(self, store: SQLiteStore):
        assert store.delete_project_record("nope") is False

    def test_delete_soft_delete_not_hard(self, store: SQLiteStore):
        """Deleted projects should still exist in DB but not be returned."""
        store.save_project_record({"project_id": "p1", "name": "SoftDel"})
        store.delete_project_record("p1")
        # Direct query shows it still exists with deleted_at set
        with store.connect() as conn:
            row = conn.execute("SELECT deleted_at FROM projects WHERE project_id = 'p1'").fetchone()
            assert row["deleted_at"] is not None

    def test_delete_clears_current_project(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Current"})
        store.set_current_project_id("p1")
        assert store.get_current_project_id() == "p1"
        store.delete_project_record("p1")
        assert store.get_current_project_id() is None

    def test_delete_clears_project_kv(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "KVTest"})
        store.set_project_value("p1", "settings", {"theme": "dark"})
        store.delete_project_record("p1")
        # get_project_value returns {} (its default) when row is missing
        assert store.get_project_value("p1", "settings") == {}

    def test_defaults_for_optional_fields(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Minimal"})
        got = store.get_project_record("p1")
        assert got["description"] == ""
        assert got["config"] == {}
        assert got["settings"] == {}
        assert got["generation_schedule"] == {}

    def test_create_at_auto_filled(self, store: SQLiteStore):
        store.save_project_record({"project_id": "p1", "name": "Test"})
        got = store.get_project_record("p1")
        assert got["created_at"] is not None
        # Should be a valid ISO string
        datetime.fromisoformat(got["created_at"])


# ===========================================================================
# Reviews CRUD
# ===========================================================================


class TestReviewsCRUD:
    def test_save_and_get(self, store: SQLiteStore):
        record = _make_review()
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got is not None
        assert got["review_id"] == record["review_id"]
        assert got["status"] == "pending_review"
        assert got["post_data"]["platform"] == "twitter"

    def test_get_nonexistent(self, store: SQLiteStore):
        assert store.get_review_record("nope") is None

    def test_save_with_replace_false_no_overwrite(self, store: SQLiteStore):
        record = _make_review({"status": "pending_review"})
        store.save_review_record(record, replace=False)
        record["status"] = "approved"
        store.save_review_record(record, replace=False)
        got = store.get_review_record(record["review_id"])
        assert got["status"] == "pending_review"

    def test_save_with_replace_true_updates(self, store: SQLiteStore):
        record = _make_review({"status": "pending_review"})
        store.save_review_record(record)
        record["status"] = "approved"
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["status"] == "approved"

    def test_list_all_reviews(self, store: SQLiteStore):
        store.save_review_record(_make_review())
        store.save_review_record(_make_review())
        records = store.list_review_records()
        assert len(records) == 2

    def test_list_filter_by_status(self, store: SQLiteStore):
        store.save_review_record(_make_review({"status": "pending_review"}))
        store.save_review_record(_make_review({"status": "approved"}))
        records = store.list_review_records(status="pending_review")
        assert len(records) == 1
        assert records[0]["status"] == "pending_review"

    def test_list_filter_by_project_id(self, store: SQLiteStore):
        store.save_review_record(_make_review({"project_id": "proj-a"}))
        store.save_review_record(_make_review({"project_id": "proj-b"}))
        records = store.list_review_records(project_id="proj-a")
        assert len(records) == 1
        assert records[0]["project_id"] == "proj-a"

    def test_list_filter_combined(self, store: SQLiteStore):
        store.save_review_record(
            _make_review({"project_id": "proj-a", "status": "pending_review"})
        )
        store.save_review_record(
            _make_review({"project_id": "proj-a", "status": "approved"})
        )
        store.save_review_record(
            _make_review({"project_id": "proj-b", "status": "pending_review"})
        )
        records = store.list_review_records(status="pending_review", project_id="proj-a")
        assert len(records) == 1

    def test_list_with_limit(self, store: SQLiteStore):
        for _ in range(5):
            store.save_review_record(_make_review())
        records = store.list_review_records(limit=3)
        assert len(records) == 3

    def test_list_ordered_by_created_at_desc(self, store: SQLiteStore):
        r1 = _make_review()
        r2 = _make_review()
        store.save_review_record(r1)
        store.save_review_record(r2)
        records = store.list_review_records()
        # Most recent first
        assert records[0]["review_id"] == r2["review_id"]

    def test_post_data_round_trip(self, store: SQLiteStore):
        """Complex post_data with nested fields should survive save/load."""
        record = _make_review(
            {
                "post_data": {
                    "platform": "linkedin",
                    "content": "Test\nmultiline\ncontent",
                    "project_id": "proj-1",
                    "auto_fix_applied": True,
                    "auto_fix_summary": "Fixed hook",
                    "nested": {"deep": {"value": 42}},
                }
            }
        )
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["post_data"]["auto_fix_applied"] is True
        assert got["post_data"]["auto_fix_summary"] == "Fixed hook"
        assert got["post_data"]["nested"]["deep"]["value"] == 42

    def test_feedback_history_in_blob(self, store: SQLiteStore):
        """feedback_history should survive in the record_json blob even without a dedicated column."""
        record = _make_review(
            {
                "feedback_history": [
                    {
                        "timestamp": utc_now(),
                        "from_status": "pending_review",
                        "to_status": "needs_work",
                        "feedback": "Fix the hook",
                        "learning_tags": "weak_hook",
                        "auto_fix_applied": True,
                    }
                ]
            }
        )
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert "feedback_history" in got
        assert len(got["feedback_history"]) == 1
        assert got["feedback_history"][0]["learning_tags"] == "weak_hook"

    def test_scheduling_error_in_blob(self, store: SQLiteStore):
        """scheduling_error should survive in the record_json blob."""
        record = _make_review({"scheduling_error": "Review is missing project_id"})
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["scheduling_error"] == "Review is missing project_id"

    def test_feedback_history_structured_column(self, store: SQLiteStore):
        """feedback_history should be queryable via the dedicated column."""
        history = [
            {
                "timestamp": utc_now(),
                "from_status": "pending_review",
                "to_status": "needs_work",
                "feedback": "Weak hook",
                "learning_tags": "weak_hook",
            }
        ]
        record = _make_review({"feedback_history": history})
        store.save_review_record(record)

        # Read back through get_review_record — should merge from structured column
        got = store.get_review_record(record["review_id"])
        assert got["feedback_history"] == history

        # Verify the structured column is populated
        with store.connect() as conn:
            row = conn.execute(
                "SELECT feedback_history_json FROM reviews WHERE review_id = ?",
                (record["review_id"],),
            ).fetchone()
            assert row["feedback_history_json"] is not None
            stored = json.loads(row["feedback_history_json"])
            assert len(stored) == 1
            assert stored[0]["learning_tags"] == "weak_hook"

    def test_scheduling_error_structured_column(self, store: SQLiteStore):
        """scheduling_error should be queryable via the dedicated column."""
        record = _make_review({"scheduling_error": "API rate limit exceeded"})
        store.save_review_record(record)

        got = store.get_review_record(record["review_id"])
        assert got["scheduling_error"] == "API rate limit exceeded"

        with store.connect() as conn:
            row = conn.execute(
                "SELECT scheduling_error FROM reviews WHERE review_id = ?",
                (record["review_id"],),
            ).fetchone()
            assert row["scheduling_error"] == "API rate limit exceeded"

    def test_feedback_history_null_for_records_without_it(self, store: SQLiteStore):
        """Records without feedback_history should have NULL in the structured column."""
        record = _make_review({})
        store.save_review_record(record)

        with store.connect() as conn:
            row = conn.execute(
                "SELECT feedback_history_json FROM reviews WHERE review_id = ?",
                (record["review_id"],),
            ).fetchone()
            assert row["feedback_history_json"] is None

    def test_scheduling_error_null_for_records_without_it(self, store: SQLiteStore):
        """Records without scheduling_error should have NULL in the structured column."""
        record = _make_review({})
        store.save_review_record(record)

        with store.connect() as conn:
            row = conn.execute(
                "SELECT scheduling_error FROM reviews WHERE review_id = ?",
                (record["review_id"],),
            ).fetchone()
            assert row["scheduling_error"] is None

    def test_feedback_history_multiple_entries(self, store: SQLiteStore):
        """Multiple feedback history entries round-trip correctly."""
        history = [
            {
                "timestamp": "2025-01-01T00:00:00+00:00",
                "from_status": "pending_review",
                "to_status": "needs_work",
                "feedback": "Fix hook",
                "learning_tags": "weak_hook",
            },
            {
                "timestamp": "2025-01-02T00:00:00+00:00",
                "from_status": "needs_work",
                "to_status": "pending_review",
                "feedback": "Auto-fixed",
                "learning_tags": "auto_fix_applied",
            },
        ]
        record = _make_review({"feedback_history": history})
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert len(got["feedback_history"]) == 2
        assert got["feedback_history"][0]["learning_tags"] == "weak_hook"
        assert got["feedback_history"][1]["learning_tags"] == "auto_fix_applied"

    def test_feedback_history_and_scheduling_error_together(self, store: SQLiteStore):
        """Both new columns can be populated simultaneously."""
        history = [{"timestamp": utc_now(), "from_status": "approved", "to_status": "scheduled", "feedback": ""}]
        record = _make_review({
            "feedback_history": history,
            "scheduling_error": "Slot conflict",
        })
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["feedback_history"] == history
        assert got["scheduling_error"] == "Slot conflict"

    def test_list_reviews_merges_structured_columns(self, store: SQLiteStore):
        """list_review_records should merge structured columns into results."""
        history = [{"timestamp": utc_now(), "from_status": "pending_review", "to_status": "approved", "feedback": "LGTM"}]
        store.save_review_record(
            _make_review({"review_id": "r1", "feedback_history": history, "scheduling_error": "err-1"})
        )
        store.save_review_record(
            _make_review({"review_id": "r2", "scheduling_error": "err-2"})
        )
        records = store.list_review_records()
        r1 = next(r for r in records if r["review_id"] == "r1")
        r2 = next(r for r in records if r["review_id"] == "r2")
        assert r1["feedback_history"] == history
        assert r1["scheduling_error"] == "err-1"
        assert r2.get("feedback_history") is None
        assert r2["scheduling_error"] == "err-2"

    def test_update_feedback_history_via_save(self, store: SQLiteStore):
        """Updating feedback_history via save_review_record persists to structured column."""
        record = _make_review({"feedback_history": []})
        store.save_review_record(record)

        updated_history = [{"timestamp": utc_now(), "from_status": "pending_review", "to_status": "needs_work", "feedback": "Revise"}]
        record["feedback_history"] = updated_history
        store.save_review_record(record)

        got = store.get_review_record(record["review_id"])
        assert got["feedback_history"] == updated_history

    def test_update_scheduling_error_via_save(self, store: SQLiteStore):
        """Updating scheduling_error via save_review_record persists to structured column."""
        record = _make_review({"scheduling_error": "first error"})
        store.save_review_record(record)

        record["scheduling_error"] = "second error"
        store.save_review_record(record)

        got = store.get_review_record(record["review_id"])
        assert got["scheduling_error"] == "second error"

    def test_normalize_extracts_feedback_history(self, store: SQLiteStore):
        """normalize_review_record preserves feedback_history from input."""
        history = [{"timestamp": utc_now(), "feedback": "test"}]
        normalized = store.normalize_review_record({"post_data": {}, "feedback_history": history})
        assert normalized["feedback_history"] == history

    def test_normalize_extracts_scheduling_error(self, store: SQLiteStore):
        """normalize_review_record preserves scheduling_error from input."""
        normalized = store.normalize_review_record({"post_data": {}, "scheduling_error": "some error"})
        assert normalized["scheduling_error"] == "some error"

    def test_normalize_handles_missing_feedback_history(self, store: SQLiteStore):
        """normalize_review_record returns None for missing feedback_history."""
        normalized = store.normalize_review_record({"post_data": {}})
        assert normalized.get("feedback_history") is None

    def test_normalize_handles_missing_scheduling_error(self, store: SQLiteStore):
        """normalize_review_record returns None for missing scheduling_error."""
        normalized = store.normalize_review_record({"post_data": {}})
        assert normalized.get("scheduling_error") is None

    def test_record_json_blob_includes_feedback_history(self, store: SQLiteStore):
        """record_json blob should still contain feedback_history for completeness."""
        history = [{"timestamp": utc_now(), "feedback": "ok"}]
        record = _make_review({"feedback_history": history})
        store.save_review_record(record)

        with store.connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM reviews WHERE review_id = ?",
                (record["review_id"],),
            ).fetchone()
            blob = json.loads(row["record_json"])
            assert blob["feedback_history"] == history

    def test_record_json_blob_includes_scheduling_error(self, store: SQLiteStore):
        """record_json blob should still contain scheduling_error for completeness."""
        record = _make_review({"scheduling_error": "timeout"})
        store.save_review_record(record)

        with store.connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM reviews WHERE review_id = ?",
                (record["review_id"],),
            ).fetchone()
            blob = json.loads(row["record_json"])
            assert blob["scheduling_error"] == "timeout"

    def test_normalize_review_record_basic(self, store: SQLiteStore):
        """normalize_review_record should fill defaults."""
        normalized = store.normalize_review_record({"post_data": {}})
        assert "review_id" in normalized
        assert normalized["status"] == "pending_review"
        assert normalized["channel"] == "CLI"

    def test_normalize_preserves_project_id_from_record(self, store: SQLiteStore):
        normalized = store.normalize_review_record(
            {"project_id": "proj-x", "post_data": {}}
        )
        assert normalized["project_id"] == "proj-x"

    def test_normalize_takes_project_id_from_post_data(self, store: SQLiteStore):
        normalized = store.normalize_review_record(
            {"post_data": {"project_id": "proj-y"}}
        )
        assert normalized["project_id"] == "proj-y"

    def test_normalize_explicit_project_id_overrides(self, store: SQLiteStore):
        normalized = store.normalize_review_record(
            {"project_id": "a", "post_data": {"project_id": "b"}},
            project_id="c",
        )
        assert normalized["project_id"] == "c"

    def test_status_transitions(self, store: SQLiteStore):
        """Simulate a full status lifecycle."""
        record = _make_review()
        # pending_review -> needs_work
        record["status"] = "needs_work"
        record["feedback"] = "Weak hook"
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["status"] == "needs_work"

        # needs_work -> pending_review (after auto-fix)
        record["status"] = "pending_review"
        record["feedback"] = None
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["status"] == "pending_review"

        # pending_review -> approved
        record["status"] = "approved"
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["status"] == "approved"

        # approved -> scheduled
        record["status"] = "scheduled"
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["status"] == "scheduled"

    def test_none_project_id_review(self, store: SQLiteStore):
        """Reviews can have None project_id."""
        record = _make_review({"project_id": None})
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got is not None
        assert got["project_id"] is None


# ===========================================================================
# Scheduled Posts CRUD
# ===========================================================================


class TestScheduledPostsCRUD:
    def test_save_and_get(self, store: SQLiteStore):
        record = _make_scheduled()
        store.save_scheduled_record(record)
        got = store.get_scheduled_record(record["post_id"])
        assert got is not None
        assert got["post_id"] == record["post_id"]
        assert got["status"] == "scheduled"

    def test_get_nonexistent(self, store: SQLiteStore):
        assert store.get_scheduled_record("nope") is None

    def test_save_with_replace_true_updates(self, store: SQLiteStore):
        record = _make_scheduled({"status": "scheduled"})
        store.save_scheduled_record(record)
        record["status"] = "published"
        store.save_scheduled_record(record)
        got = store.get_scheduled_record(record["post_id"])
        assert got["status"] == "published"

    def test_save_with_replace_false_no_overwrite(self, store: SQLiteStore):
        record = _make_scheduled({"status": "scheduled"})
        store.save_scheduled_record(record, replace=False)
        record["status"] = "published"
        store.save_scheduled_record(record, replace=False)
        got = store.get_scheduled_record(record["post_id"])
        assert got["status"] == "scheduled"

    def test_list_all(self, store: SQLiteStore):
        store.save_scheduled_record(_make_scheduled())
        store.save_scheduled_record(_make_scheduled())
        records = store.list_scheduled_records()
        assert len(records) == 2

    def test_list_filter_by_project_id(self, store: SQLiteStore):
        store.save_scheduled_record(_make_scheduled({"project_id": "pa"}))
        store.save_scheduled_record(_make_scheduled({"project_id": "pb"}))
        records = store.list_scheduled_records(project_id="pa")
        assert len(records) == 1
        assert records[0]["project_id"] == "pa"

    def test_list_filter_by_status(self, store: SQLiteStore):
        store.save_scheduled_record(_make_scheduled({"status": "scheduled"}))
        store.save_scheduled_record(_make_scheduled({"status": "published"}))
        records = store.list_scheduled_records(status="published")
        assert len(records) == 1
        assert records[0]["status"] == "published"

    def test_list_filter_combined(self, store: SQLiteStore):
        store.save_scheduled_record(
            _make_scheduled({"project_id": "pa", "status": "scheduled"})
        )
        store.save_scheduled_record(
            _make_scheduled({"project_id": "pa", "status": "published"})
        )
        store.save_scheduled_record(
            _make_scheduled({"project_id": "pb", "status": "scheduled"})
        )
        records = store.list_scheduled_records(project_id="pa", status="scheduled")
        assert len(records) == 1

    def test_delete(self, store: SQLiteStore):
        record = _make_scheduled()
        store.save_scheduled_record(record)
        assert store.delete_scheduled_record(record["post_id"]) is True
        assert store.get_scheduled_record(record["post_id"]) is None

    def test_delete_nonexistent(self, store: SQLiteStore):
        assert store.delete_scheduled_record("nope") is False

    def test_normalize_scheduled_record(self, store: SQLiteStore):
        normalized = store.normalize_scheduled_record({"post_data": {}})
        assert "post_id" in normalized
        assert normalized["status"] == "scheduled"
        assert "created_at" in normalized

    def test_normalize_preserves_post_id(self, store: SQLiteStore):
        normalized = store.normalize_scheduled_record({"post_id": "custom-id", "post_data": {}})
        assert normalized["post_id"] == "custom-id"

    def test_post_data_round_trip(self, store: SQLiteStore):
        record = _make_scheduled(
            {"post_data": {"platform": "linkedin", "content": "Post", "extra": [1, 2, 3]}}
        )
        store.save_scheduled_record(record)
        got = store.get_scheduled_record(record["post_id"])
        assert got["post_data"]["extra"] == [1, 2, 3]


# ===========================================================================
# Jobs lifecycle
# ===========================================================================


class TestJobsLifecycle:
    def test_enqueue(self, store: SQLiteStore):
        job = store.enqueue_job(kind="generate", payload={"project_id": "p1"})
        assert job["job_id"].startswith("job_")
        assert job["kind"] == "generate"
        assert job["status"] == "queued"
        assert job["priority"] == 100
        assert job["attempts"] == 0
        assert job["max_attempts"] == 3

    def test_enqueue_with_overrides(self, store: SQLiteStore):
        job = store.enqueue_job(
            kind="publish",
            payload={"channel": "twitter"},
            project_id="p1",
            priority=50,
            available_at="2099-01-01T00:00:00+00:00",
            max_attempts=5,
        )
        assert job["project_id"] == "p1"
        assert job["priority"] == 50
        assert job["max_attempts"] == 5

    def test_get_job_record(self, store: SQLiteStore):
        job = store.enqueue_job(kind="generate")
        got = store.get_job_record(job["job_id"])
        assert got is not None
        assert got["kind"] == "generate"

    def test_get_nonexistent_job(self, store: SQLiteStore):
        assert store.get_job_record("nope") is None

    def test_list_job_records(self, store: SQLiteStore):
        store.enqueue_job(kind="generate", project_id="p1")
        store.enqueue_job(kind="publish", project_id="p1")
        jobs = store.list_job_records()
        assert len(jobs) == 2

    def test_list_filter_by_project(self, store: SQLiteStore):
        store.enqueue_job(kind="generate", project_id="pa")
        store.enqueue_job(kind="generate", project_id="pb")
        jobs = store.list_job_records(project_id="pa")
        assert len(jobs) == 1
        assert jobs[0]["project_id"] == "pa"

    def test_list_filter_by_status(self, store: SQLiteStore):
        j1 = store.enqueue_job(kind="generate")
        j2 = store.enqueue_job(kind="publish")
        store.complete_job(j2["job_id"])
        jobs = store.list_job_records(status="completed")
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == j2["job_id"]

    def test_list_respects_limit(self, store: SQLiteStore):
        for _ in range(5):
            store.enqueue_job(kind="generate")
        jobs = store.list_job_records(limit=3)
        assert len(jobs) == 3

    def test_claim_next_job(self, store: SQLiteStore):
        store.enqueue_job(kind="generate", priority=50)
        store.enqueue_job(kind="publish", priority=100)
        job = store.claim_next_job()
        assert job is not None
        assert job["status"] == "running"
        assert job["kind"] == "generate"  # lower priority claimed first
        assert job["attempts"] == 1

    def test_claim_respects_kind_filter(self, store: SQLiteStore):
        store.enqueue_job(kind="generate")
        store.enqueue_job(kind="publish")
        job = store.claim_next_job(kinds=["publish"])
        assert job is not None
        assert job["kind"] == "publish"

    def test_claim_returns_none_when_empty(self, store: SQLiteStore):
        assert store.claim_next_job() is None

    def test_claim_skips_not_available_yet(self, store: SQLiteStore):
        """Jobs with future available_at should not be claimed."""
        store.enqueue_job(kind="generate", available_at="2099-12-31T00:00:00+00:00")
        assert store.claim_next_job() is None

    def test_claim_does_not_filter_by_attempts(self, store: SQLiteStore):
        """RetryPolicy is the sole authority over retry decisions; claim does
        not gate on attempts < max_attempts (CR-01)."""
        job = store.enqueue_job(kind="generate", max_attempts=1)
        job["attempts"] = 1
        job["status"] = "queued"
        store.save_job_record(job)
        claimed = store.claim_next_job()
        assert claimed is not None
        assert claimed["job_id"] == job["job_id"]
        assert claimed["attempts"] == 2

    def test_complete_job(self, store: SQLiteStore):
        job = store.enqueue_job(kind="generate")
        store.claim_next_job()  # move to running
        result = store.complete_job(job["job_id"], result={"content": "generated"})
        assert result is not None
        assert result["status"] == "completed"
        assert result["result"] == {"content": "generated"}
        assert result["error"] is None
        assert result["finished_at"] is not None

    def test_complete_nonexistent(self, store: SQLiteStore):
        assert store.complete_job("nope") is None

    def test_fail_job_no_retry(self, store: SQLiteStore):
        job = store.enqueue_job(kind="generate")
        store.claim_next_job()
        result = store.fail_job(job["job_id"], error="API timeout")
        assert result is not None
        assert result["status"] == "failed"
        assert result["error"] == "API timeout"
        assert result["finished_at"] is not None

    def test_fail_job_with_retry(self, store: SQLiteStore):
        job = store.enqueue_job(kind="generate", max_attempts=3)
        store.claim_next_job()
        result = store.fail_job(job["job_id"], error="Transient error", retry=True)
        assert result is not None
        assert result["status"] == "queued"
        assert result["finished_at"] is None  # not finished, will retry

    def test_fail_job_retry_exhausted(self, store: SQLiteStore):
        job = store.enqueue_job(kind="generate", max_attempts=1)
        store.claim_next_job()  # attempts becomes 1
        result = store.fail_job(job["job_id"], error="Final fail", retry=True)
        assert result is not None
        assert result["status"] == "failed"  # max_attempts reached

    def test_fail_nonexistent(self, store: SQLiteStore):
        assert store.fail_job("nope", error="x") is None

    def test_cancel_job(self, store: SQLiteStore):
        job = store.enqueue_job(kind="generate")
        result = store.cancel_job(job["job_id"])
        assert result is not None
        assert result["status"] == "cancelled"
        assert result["finished_at"] is not None

    def test_cancel_nonexistent(self, store: SQLiteStore):
        assert store.cancel_job("nope") is None

    def test_get_job_stats(self, store: SQLiteStore):
        j1 = store.enqueue_job(kind="generate")
        j2 = store.enqueue_job(kind="generate")
        store.complete_job(j1["job_id"])
        store.cancel_job(j2["job_id"])
        stats = store.get_job_stats()
        assert stats["queued"] == 0
        assert stats["completed"] == 1
        assert stats["cancelled"] == 1
        assert stats["total"] == 2

    def test_get_job_stats_empty(self, store: SQLiteStore):
        stats = store.get_job_stats()
        assert stats["total"] == 0
        for key in ("queued", "running", "completed", "failed", "cancelled"):
            assert stats[key] == 0

    def test_save_job_record_replace_false(self, store: SQLiteStore):
        job = store.enqueue_job(kind="generate")
        original_id = job["job_id"]
        job["status"] = "completed"
        store.save_job_record(job, replace=False)
        # Should not have updated
        got = store.get_job_record(original_id)
        assert got["status"] == "queued"

    def test_normalize_job_record(self, store: SQLiteStore):
        normalized = store.normalize_job_record({"kind": "generate", "payload": {}})
        assert "job_id" in normalized
        assert normalized["kind"] == "generate"
        assert normalized["status"] == "queued"
        assert normalized["priority"] == 100
        assert normalized["attempts"] == 0

    def test_job_priority_ordering(self, store: SQLiteStore):
        """Lower priority number should be claimed first."""
        store.enqueue_job(kind="low", priority=200)
        store.enqueue_job(kind="high", priority=10)
        store.enqueue_job(kind="mid", priority=100)
        job = store.claim_next_job()
        assert job["kind"] == "high"

    def test_full_job_lifecycle(self, store: SQLiteStore):
        """End-to-end: enqueue -> claim -> complete."""
        job = store.enqueue_job(kind="generate", project_id="p1", payload={"count": 5})
        assert job["status"] == "queued"

        claimed = store.claim_next_job()
        assert claimed is not None
        assert claimed["job_id"] == job["job_id"]
        assert claimed["status"] == "running"
        assert claimed["started_at"] is not None

        completed = store.complete_job(job["job_id"], result={"generated": 5})
        assert completed["status"] == "completed"
        assert completed["result"]["generated"] == 5

        # Verify via get_job_record
        final = store.get_job_record(job["job_id"])
        assert final["status"] == "completed"
        assert final["finished_at"] is not None

    def test_job_payload_round_trip(self, store: SQLiteStore):
        """Complex payload should survive save/load."""
        payload = {
            "project_id": "p1",
            "platforms": ["twitter", "linkedin"],
            "config": {"temperature": 0.7, "nested": {"deep": True}},
        }
        job = store.enqueue_job(kind="generate", payload=payload)
        got = store.get_job_record(job["job_id"])
        assert got["payload"]["platforms"] == ["twitter", "linkedin"]
        assert got["payload"]["config"]["nested"]["deep"] is True


# ===========================================================================
# Project KV
# ===========================================================================


class TestProjectKV:
    def test_set_and_get(self, store: SQLiteStore):
        store.set_project_value("p1", "settings", {"theme": "dark"})
        result = store.get_project_value("p1", "settings")
        assert result == {"theme": "dark"}

    def test_get_nonexistent(self, store: SQLiteStore):
        result = store.get_project_value("p1", "nope")
        # Default is {} when default is None
        assert result == {}

    def test_get_with_default(self, store: SQLiteStore):
        # get_project_value returns {} when row not found and default is None
        result = store.get_project_value("p1", "nope", default=None)
        assert result == {}

    def test_get_with_list_default(self, store: SQLiteStore):
        result = store.get_project_value("p1", "nope", default=[])
        assert result == []

    def test_overwrite(self, store: SQLiteStore):
        store.set_project_value("p1", "key", "v1")
        store.set_project_value("p1", "key", "v2")
        assert store.get_project_value("p1", "key") == "v2"

    def test_multiple_keys(self, store: SQLiteStore):
        store.set_project_value("p1", "settings", {"lang": "en"})
        store.set_project_value("p1", "secrets", {"api_key": "abc"})
        assert store.get_project_value("p1", "settings") == {"lang": "en"}
        assert store.get_project_value("p1", "secrets") == {"api_key": "abc"}

    def test_multiple_projects_same_key(self, store: SQLiteStore):
        store.set_project_value("p1", "settings", {"theme": "dark"})
        store.set_project_value("p2", "settings", {"theme": "light"})
        assert store.get_project_value("p1", "settings") == {"theme": "dark"}
        assert store.get_project_value("p2", "settings") == {"theme": "light"}

    def test_complex_value_round_trip(self, store: SQLiteStore):
        value = {"list": [1, 2, 3], "nested": {"deep": True}, "null": None}
        store.set_project_value("p1", "complex", value)
        assert store.get_project_value("p1", "complex") == value


# ===========================================================================
# Current State
# ===========================================================================


class TestCurrentState:
    def test_set_and_get(self, store: SQLiteStore):
        store.set_current_project_id("p1")
        assert store.get_current_project_id() == "p1"

    def test_get_when_none_set(self, store: SQLiteStore):
        assert store.get_current_project_id() is None

    def test_clear(self, store: SQLiteStore):
        store.set_current_project_id("p1")
        store.clear_current_project()
        assert store.get_current_project_id() is None

    def test_clear_when_none_set(self, store: SQLiteStore):
        # Should not error
        store.clear_current_project()
        assert store.get_current_project_id() is None

    def test_overwrite(self, store: SQLiteStore):
        store.set_current_project_id("p1")
        store.set_current_project_id("p2")
        assert store.get_current_project_id() == "p2"


# ===========================================================================
# Normalize helpers (additional edge cases)
# ===========================================================================


class TestNormalizeEdgeCases:
    def test_normalize_project_record_minimal(self, store: SQLiteStore):
        result = store._normalize_project_record("p1", {})
        assert result["project_id"] == "p1"
        assert result["name"] == "p1"
        assert result["slug"] == "p1"
        assert result["description"] == ""
        assert result["config"] == {}

    def test_normalize_project_record_with_name_in_record(self, store: SQLiteStore):
        result = store._normalize_project_record("p1", {"name": "My Project"})
        assert result["name"] == "My Project"
        assert result["slug"] == "my-project"

    def test_normalize_review_auto_generates_id(self, store: SQLiteStore):
        result = store.normalize_review_record({"post_data": {}})
        assert result["review_id"].startswith("review_")

    def test_normalize_review_preserves_existing_id(self, store: SQLiteStore):
        result = store.normalize_review_record({"review_id": "rev-1", "post_data": {}})
        assert result["review_id"] == "rev-1"

    def test_normalize_review_uses_generated_at_as_fallback_id(self, store: SQLiteStore):
        result = store.normalize_review_record(
            {"post_data": {"generated_at": "2026-01-01T00:00:00"}}
        )
        assert result["review_id"] == "2026-01-01T00:00:00"

    def test_normalize_scheduled_auto_generates_id(self, store: SQLiteStore):
        result = store.normalize_scheduled_record({"post_data": {}})
        assert result["post_id"].startswith("scheduled_")

    def test_normalize_scheduled_preserves_existing_id(self, store: SQLiteStore):
        result = store.normalize_scheduled_record({"post_id": "sp-1", "post_data": {}})
        assert result["post_id"] == "sp-1"

    def test_normalize_job_preserves_id(self, store: SQLiteStore):
        result = store.normalize_job_record({"job_id": "j-1", "kind": "generate"})
        assert result["job_id"] == "j-1"

    def test_normalize_job_default_status(self, store: SQLiteStore):
        result = store.normalize_job_record({"kind": "generate"})
        assert result["status"] == "queued"

    def test_normalize_job_project_id_from_payload(self, store: SQLiteStore):
        result = store.normalize_job_record(
            {"kind": "generate", "payload": {"project_id": "from-payload"}}
        )
        assert result["project_id"] == "from-payload"


# ===========================================================================
# Legacy import (basic smoke test)
# ===========================================================================


class TestLegacyImport:
    def test_import_projects_json(self, store: SQLiteStore):
        """Write a projects.json and trigger import."""
        projects_data = {
            "proj-legacy": {
                "name": "Legacy Project",
                "description": "From JSON",
                "settings": {"language": "en"},
            }
        }
        projects_path = store.data_dir / "projects.json"
        projects_path.write_text(json.dumps(projects_data))
        store._import_projects_json()

        got = store.get_project_record("proj-legacy")
        assert got is not None
        assert got["name"] == "Legacy Project"

    def test_import_reviews_file_dict_format(self, store: SQLiteStore):
        """Import reviews from the dict-keyed format used by reviews.json."""
        reviews_data = {
            "2026-01-01T00:00:00": {
                "review_id": "2026-01-01T00:00:00",
                "status": "pending_review",
                "channel": "CLI",
                "post_data": {"platform": "twitter", "content": "Hello"},
            }
        }
        reviews_path = store.data_dir / "reviews.json"
        reviews_path.write_text(json.dumps(reviews_data))
        store._import_reviews_file(reviews_path, "proj-1")

        got = store.get_review_record("2026-01-01T00:00:00")
        assert got is not None
        assert got["project_id"] == "proj-1"

    def test_import_reviews_file_list_format(self, store: SQLiteStore):
        """Import reviews from list format."""
        reviews_data = [
            {
                "review_id": "rev-list-1",
                "status": "approved",
                "channel": "web",
                "post_data": {"platform": "linkedin"},
            }
        ]
        reviews_path = store.data_dir / "reviews.json"
        reviews_path.write_text(json.dumps(reviews_data))
        store._import_reviews_file(reviews_path, "proj-1")

        got = store.get_review_record("rev-list-1")
        assert got is not None

    def test_import_scheduled_posts(self, store: SQLiteStore):
        scheduled_data = [
            {
                "post_id": "sched-legacy-1",
                "project_id": "proj-1",
                "status": "scheduled",
                "scheduled_at": "2026-06-01T12:00:00+00:00",
                "post_data": {"platform": "twitter"},
            }
        ]
        path = store.data_dir / "scheduled_posts.json"
        path.write_text(json.dumps(scheduled_data))
        store._import_scheduled_posts(path)

        got = store.get_scheduled_record("sched-legacy-1")
        assert got is not None

    def test_import_legacy_files_once_idempotent(self, store: SQLiteStore):
        """import_legacy_files_once should only run once."""
        projects_data = {"p1": {"name": "First"}}
        (store.data_dir / "projects.json").write_text(json.dumps(projects_data))
        store.import_legacy_files_once()
        assert store.get_project_record("p1") is not None

        # Update the file and call again — should not re-import
        projects_data["p2"] = {"name": "Second"}
        (store.data_dir / "projects.json").write_text(json.dumps(projects_data))
        store.import_legacy_files_once()
        assert store.get_project_record("p2") is None


# ===========================================================================
# Connection and schema
# ===========================================================================


class TestConnectionAndSchema:
    def test_connect_yields_connection(self, store: SQLiteStore):
        with store.connect() as conn:
            assert conn is not None
            # Should be able to execute a simple query
            result = conn.execute("SELECT 1").fetchone()
            assert result[0] == 1

    def test_connect_auto_commits(self, store: SQLiteStore):
        with store.connect() as conn:
            conn.execute("INSERT INTO meta(key, value, updated_at) VALUES ('k', 'v', '')")
        # After context manager, should be committed
        with store.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'k'").fetchone()
            assert row["value"] == "v"

    def test_connect_rollback_on_error(self, store: SQLiteStore):
        try:
            with store.connect() as conn:
                conn.execute("INSERT INTO meta(key, value, updated_at) VALUES ('k', 'v', '')")
                raise ValueError("force rollback")
        except ValueError:
            pass
        # The insert should have been rolled back
        with store.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'k'").fetchone()
            assert row is None

    def test_schema_tables_exist(self, store: SQLiteStore):
        with store.connect() as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
        expected = [
            "current_state",
            "jobs",
            "meta",
            "project_kv",
            "projects",
            "reviews",
            "scheduled_posts",
        ]
        for t in expected:
            assert t in tables, f"Missing table: {t}"

    def test_schema_indexes_exist(self, store: SQLiteStore):
        with store.connect() as conn:
            indexes = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
                ).fetchall()
            ]
        assert "idx_projects_slug" in indexes
        assert "idx_reviews_project_status" in indexes
        assert "idx_scheduled_project_time" in indexes
        assert "idx_jobs_status_available" in indexes
        assert "idx_jobs_project_status" in indexes

    def test_wal_mode(self, store: SQLiteStore):
        with store.connect() as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0].lower() in ("wal",)


# ===========================================================================
# T03: Round-trip tests for new columns and dashboard-shape records
# ===========================================================================


class TestT03FeedbackHistoryRoundTrip:
    """Targeted round-trip tests for feedback_history_json column."""

    def test_feedback_history_round_trip(self, store: SQLiteStore):
        """Create a review with 2 FeedbackRecord-like dicts, save, load, assert match."""
        history = [
            {
                "timestamp": "2026-01-10T10:00:00+00:00",
                "from_status": "pending_review",
                "to_status": "needs_work",
                "feedback": "Hook is weak, revise",
                "learning_tags": "weak_hook",
            },
            {
                "timestamp": "2026-01-10T11:00:00+00:00",
                "from_status": "needs_work",
                "to_status": "pending_review",
                "feedback": "Auto-fixed content",
                "learning_tags": "auto_fix_applied",
                "auto_fix_applied": True,
            },
        ]
        record = _make_review({"feedback_history": history})
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])

        assert got is not None
        assert "feedback_history" in got
        fh = got["feedback_history"]
        assert len(fh) == 2
        assert fh[0]["from_status"] == "pending_review"
        assert fh[0]["to_status"] == "needs_work"
        assert fh[0]["learning_tags"] == "weak_hook"
        assert fh[1]["auto_fix_applied"] is True
        assert fh[1]["learning_tags"] == "auto_fix_applied"

    def test_scheduling_error_round_trip(self, store: SQLiteStore):
        """Create a review with scheduling_error text, save, load, assert match."""
        record = _make_review({"scheduling_error": "Typefully API returned 429 rate limit"})
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])
        assert got["scheduling_error"] == "Typefully API returned 429 rate limit"

    def test_full_dashboard_record_round_trip(self, store: SQLiteStore):
        """Construct a record matching the dashboard's full mutation shape and verify all fields."""
        history = [
            {
                "timestamp": "2026-02-06T14:45:00+00:00",
                "from_status": "pending_review",
                "to_status": "needs_work",
                "feedback": "Make it more engaging",
                "learning_tags": "too_generic",
                "auto_fix_applied": True,
            },
            {
                "timestamp": "2026-02-06T14:46:00+00:00",
                "from_status": "needs_work",
                "to_status": "pending_review",
                "feedback": "Auto-fixed",
                "learning_tags": "auto_fix_applied",
                "auto_fix_applied": True,
            },
        ]
        post_data = {
            "platform": "linkedin",
            "content_type": "thought_leadership",
            "pillar": "innovation",
            "hook_type": "question",
            "content": "What if the future of AI isn't about replacing humans?",
            "project_id": "proj-1",
            "auto_fix_applied": True,
            "auto_fix_summary": "Strengthened hook and added question format",
            "generated_at": "2026-02-06T14:44:16.074116",
            "tags": ["ai", "future"],
            "metadata": {"word_count": 42, "char_count": 280},
        }
        record = {
            "review_id": "2026-02-06T14:45:16.074116",
            "project_id": "proj-1",
            "status": "pending_review",
            "channel": "web",
            "post_data": post_data,
            "feedback": "Auto-fixed and resubmitted",
            "feedback_history": history,
            "scheduling_error": "No available slot before deadline",
            "created_at": "2026-02-06T14:44:16.074116",
        }
        store.save_review_record(record)
        got = store.get_review_record(record["review_id"])

        assert got is not None
        assert got["review_id"] == "2026-02-06T14:45:16.074116"
        assert got["project_id"] == "proj-1"
        assert got["status"] == "pending_review"
        assert got["channel"] == "web"
        assert got["feedback"] == "Auto-fixed and resubmitted"
        assert got["scheduling_error"] == "No available slot before deadline"
        assert len(got["feedback_history"]) == 2
        assert got["feedback_history"][0]["auto_fix_applied"] is True
        assert got["feedback_history"][1]["auto_fix_applied"] is True

        # Verify all post_data keys round-trip
        pd = got["post_data"]
        assert pd["platform"] == "linkedin"
        assert pd["content_type"] == "thought_leadership"
        assert pd["pillar"] == "innovation"
        assert pd["hook_type"] == "question"
        assert pd["content"] == "What if the future of AI isn't about replacing humans?"
        assert pd["auto_fix_applied"] is True
        assert pd["auto_fix_summary"] == "Strengthened hook and added question format"
        assert pd["tags"] == ["ai", "future"]
        assert pd["metadata"]["word_count"] == 42
        assert pd["metadata"]["char_count"] == 280

    def test_update_preserves_feedback_history(self, store: SQLiteStore):
        """Save without feedback_history, then update to add it; verify only new fields changed."""
        original = _make_review({
            "status": "pending_review",
            "feedback": None,
        })
        store.save_review_record(original)

        # Load and verify no feedback_history
        got = store.get_review_record(original["review_id"])
        assert got.get("feedback_history") is None
        assert got["status"] == "pending_review"

        # Update with feedback_history
        original["feedback_history"] = [
            {
                "timestamp": utc_now(),
                "from_status": "pending_review",
                "to_status": "needs_work",
                "feedback": "Revise tone",
                "learning_tags": "tone_off",
            }
        ]
        original["feedback"] = "Revise tone"
        original["status"] = "needs_work"
        store.save_review_record(original)

        got = store.get_review_record(original["review_id"])
        assert got["status"] == "needs_work"
        assert got["feedback"] == "Revise tone"
        assert len(got["feedback_history"]) == 1
        assert got["feedback_history"][0]["learning_tags"] == "tone_off"
        # post_data should still be intact
        assert got["post_data"]["platform"] == "twitter"
        assert got["post_data"]["content"] == "Test content"

    def test_legacy_import_with_fixture(self, store: SQLiteStore):
        """Create a temporary data directory with reviews.json containing feedback_history and scheduling_error."""
        reviews_data = {
            "2026-03-01T09:00:00": {
                "review_id": "2026-03-01T09:00:00",
                "status": "needs_work",
                "channel": "CLI",
                "project_id": "proj-1",
                "post_data": {
                    "platform": "twitter",
                    "content": "Test tweet",
                    "generated_at": "2026-03-01T09:00:00",
                },
                "feedback": "Too generic",
                "feedback_history": [
                    {
                        "timestamp": "2026-03-01T09:05:00+00:00",
                        "from_status": "pending_review",
                        "to_status": "needs_work",
                        "feedback": "Too generic",
                        "learning_tags": "too_generic",
                    }
                ],
                "scheduling_error": "Account not connected",
            },
            "2026-03-01T10:00:00": {
                "review_id": "2026-03-01T10:00:00",
                "status": "approved",
                "channel": "web",
                "project_id": "proj-1",
                "post_data": {
                    "platform": "linkedin",
                    "content": "Another post",
                },
            },
        }
        reviews_path = store.data_dir / "reviews.json"
        reviews_path.write_text(json.dumps(reviews_data))
        store._import_reviews_file(reviews_path, "proj-1")

        # Verify first record with feedback_history and scheduling_error
        got1 = store.get_review_record("2026-03-01T09:00:00")
        assert got1 is not None
        assert got1["status"] == "needs_work"
        assert got1["scheduling_error"] == "Account not connected"
        assert len(got1["feedback_history"]) == 1
        assert got1["feedback_history"][0]["learning_tags"] == "too_generic"

        # Verify second record (no feedback_history, no scheduling_error)
        got2 = store.get_review_record("2026-03-01T10:00:00")
        assert got2 is not None
        assert got2["status"] == "approved"
        assert got2.get("scheduling_error") is None

    def test_schema_migration_idempotent(self):
        """Instantiate SQLiteStore twice on the same DB — verify no errors and schema version meta is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite3"
            s1 = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
            assert s1.get_meta("schema_reviews_v2") == "1"

            # Second instantiation on same DB should not error
            s2 = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
            assert s2.get_meta("schema_reviews_v2") == "1"

            # Both should be functional
            s1.save_review_record(_make_review({"review_id": "r1"}))
            got = s2.get_review_record("r1")
            assert got is not None
            assert got["review_id"] == "r1"


# ---------------------------------------------------------------------------
# Source Material CRUD
# ---------------------------------------------------------------------------


def _make_source_material(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Create a minimal source material dict with optional overrides."""
    base = {
        "material_id": "sm-test-1",
        "project_id": "proj-1",
        "material_type": "url",
        "title": "Test Source",
        "url": "https://example.com/article",
        "text_content": "",
        "note": "",
        "source_attribution": "Example Blog",
        "tags": ["marketing", "strategy"],
        "metadata_json": {"fetched": True},
    }
    if overrides:
        base.update(overrides)
    return base


class TestSourceMaterialCRUD:
    """Tests for source_material table CRUD methods."""

    def test_save_and_get_record(self, store: SQLiteStore):
        """Round-trip: save a source material record and retrieve it."""
        record = _make_source_material()
        store.save_source_material_record(record)
        got = store.get_source_material_record("sm-test-1")
        assert got is not None
        assert got["material_id"] == "sm-test-1"
        assert got["project_id"] == "proj-1"
        assert got["material_type"] == "url"
        assert got["url"] == "https://example.com/article"
        assert got["tags"] == ["marketing", "strategy"]
        assert got["metadata_json"] == {"fetched": True}

    def test_get_nonexistent_returns_none(self, store: SQLiteStore):
        assert store.get_source_material_record("does-not-exist") is None

    def test_save_upserts_on_conflict(self, store: SQLiteStore):
        """Saving the same material_id twice updates the record."""
        record = _make_source_material()
        store.save_source_material_record(record)
        record["title"] = "Updated Title"
        record["url"] = "https://example.com/updated"
        store.save_source_material_record(record)
        got = store.get_source_material_record("sm-test-1")
        assert got is not None
        assert got["title"] == "Updated Title"
        assert got["url"] == "https://example.com/updated"

    def test_save_replace_false_no_overwrite(self, store: SQLiteStore):
        """INSERT OR IGNORE should not overwrite an existing record."""
        record = _make_source_material()
        store.save_source_material_record(record)
        record["title"] = "Should Not Appear"
        store.save_source_material_record(record, replace=False)
        got = store.get_source_material_record("sm-test-1")
        assert got is not None
        assert got["title"] == "Test Source"  # original value preserved

    def test_normalize_auto_generates_id(self, store: SQLiteStore):
        """normalize_source_material_record auto-generates material_id if missing."""
        record = {"project_id": "proj-1", "material_type": "note"}
        normalized = store.normalize_source_material_record(record)
        assert normalized["material_id"].startswith("sm_")
        assert normalized["project_id"] == "proj-1"
        assert normalized["material_type"] == "note"
        assert normalized["created_at"] is not None

    def test_normalize_uses_project_id_override(self, store: SQLiteStore):
        """normalize_source_material_record uses the project_id kwarg override."""
        record = {"material_type": "text"}
        normalized = store.normalize_source_material_record(record, project_id="proj-override")
        assert normalized["project_id"] == "proj-override"

    def test_list_all_records(self, store: SQLiteStore):
        """list_source_material_records returns all records when no filters."""
        store.save_source_material_record(_make_source_material({"material_id": "sm-1"}))
        store.save_source_material_record(_make_source_material({"material_id": "sm-2", "material_type": "text"}))
        results = store.list_source_material_records()
        assert len(results) == 2

    def test_list_filter_by_project(self, store: SQLiteStore):
        """list_source_material_records filters by project_id."""
        store.save_source_material_record(_make_source_material({"material_id": "sm-a", "project_id": "proj-a"}))
        store.save_source_material_record(_make_source_material({"material_id": "sm-b", "project_id": "proj-b"}))
        results = store.list_source_material_records(project_id="proj-a")
        assert len(results) == 1
        assert results[0]["project_id"] == "proj-a"

    def test_list_filter_by_material_type(self, store: SQLiteStore):
        """list_source_material_records filters by material_type."""
        store.save_source_material_record(_make_source_material({"material_id": "sm-url", "material_type": "url"}))
        store.save_source_material_record(_make_source_material({"material_id": "sm-note", "material_type": "note"}))
        results = store.list_source_material_records(material_type="note")
        assert len(results) == 1
        assert results[0]["material_type"] == "note"

    def test_list_combined_filters(self, store: SQLiteStore):
        """list_source_material_records supports project_id + material_type filters."""
        store.save_source_material_record(
            _make_source_material({"material_id": "sm-p1-url", "project_id": "p1", "material_type": "url"})
        )
        store.save_source_material_record(
            _make_source_material({"material_id": "sm-p1-note", "project_id": "p1", "material_type": "note"})
        )
        store.save_source_material_record(
            _make_source_material({"material_id": "sm-p2-url", "project_id": "p2", "material_type": "url"})
        )
        results = store.list_source_material_records(project_id="p1", material_type="url")
        assert len(results) == 1
        assert results[0]["material_id"] == "sm-p1-url"

    def test_list_with_limit(self, store: SQLiteStore):
        """list_source_material_records respects limit parameter."""
        for i in range(5):
            store.save_source_material_record(_make_source_material({"material_id": f"sm-limit-{i}"}))
        results = store.list_source_material_records(limit=3)
        assert len(results) == 3

    def test_delete_existing(self, store: SQLiteStore):
        """delete_source_material_record returns True and removes the record."""
        store.save_source_material_record(_make_source_material())
        assert store.delete_source_material_record("sm-test-1") is True
        assert store.get_source_material_record("sm-test-1") is None

    def test_delete_nonexistent(self, store: SQLiteStore):
        """delete_source_material_record returns False for missing records."""
        assert store.delete_source_material_record("does-not-exist") is False

    def test_project_isolation(self, store: SQLiteStore):
        """Source materials from one project don't leak to another."""
        store.save_source_material_record(
            _make_source_material({"material_id": "sm-x", "project_id": "proj-x", "title": "Project X"})
        )
        store.save_source_material_record(
            _make_source_material({"material_id": "sm-y", "project_id": "proj-y", "title": "Project Y"})
        )
        results_x = store.list_source_material_records(project_id="proj-x")
        assert len(results_x) == 1
        assert results_x[0]["title"] == "Project X"

    def test_field_fidelity_all_fields(self, store: SQLiteStore):
        """All fields survive a round-trip through save/get."""
        record = {
            "material_id": "sm-full",
            "project_id": "proj-full",
            "material_type": "text",
            "title": "Full Record",
            "url": "https://example.com",
            "text_content": "Some long text content here",
            "note": "A note about this",
            "source_attribution": "Author Name",
            "tags": ["tag1", "tag2", "tag3"],
            "metadata_json": {"key": "value", "nested": {"a": 1}},
        }
        store.save_source_material_record(record)
        got = store.get_source_material_record("sm-full")
        assert got is not None
        assert got["material_id"] == "sm-full"
        assert got["project_id"] == "proj-full"
        assert got["material_type"] == "text"
        assert got["title"] == "Full Record"
        assert got["url"] == "https://example.com"
        assert got["text_content"] == "Some long text content here"
        assert got["note"] == "A note about this"
        assert got["source_attribution"] == "Author Name"
        assert got["tags"] == ["tag1", "tag2", "tag3"]
        assert got["metadata_json"] == {"key": "value", "nested": {"a": 1}}

    def test_dataclass_round_trip(self, store: SQLiteStore):
        """SourceMaterial dataclass serializes and deserializes correctly via store."""
        from data.models import SourceMaterial

        sm = SourceMaterial(
            material_id="sm-dc",
            project_id="proj-dc",
            material_type="note",
            note="Quick idea from dataclass",
            tags=["idea"],
            metadata_json={"source": "test"},
        )
        store.save_source_material_record(sm.to_dict())
        got = store.get_source_material_record("sm-dc")
        assert got is not None
        restored = SourceMaterial.from_dict(got)
        assert restored.material_id == "sm-dc"
        assert restored.project_id == "proj-dc"
        assert restored.material_type == "note"
        assert restored.note == "Quick idea from dataclass"
        assert restored.tags == ["idea"]
        assert restored.metadata_json == {"source": "test"}

    def test_empty_optional_fields(self, store: SQLiteStore):
        """Records with only required fields save and retrieve correctly."""
        record = {
            "material_id": "sm-minimal",
            "project_id": "proj-min",
            "material_type": "note",
        }
        store.save_source_material_record(record)
        got = store.get_source_material_record("sm-minimal")
        assert got is not None
        assert got["material_id"] == "sm-minimal"
        assert got["material_type"] == "note"
        # Optional fields should be empty/default
        assert got.get("url", "") == ""
        assert got.get("title") in ("", None)
