#!/usr/bin/env python3
"""Comprehensive tests for source material data model, store CRUD, service validation, and enrichment.

Covers:
- SourceMaterial dataclass round-trip (to_dict/from_dict, defaults, missing fields)
- SQLiteStore source_material CRUD (save, get, list, delete, persistence)
- IdeaLabService envelope validation (auto type detection, required fields, tag normalization)
- Project isolation (cross-project visibility, scoped listing)
- Edge cases (special chars in IDs, long content, empty tags, unknown update)
- Enrichment: URL fetch + key points + tags, text enrichment, note tagging,
  ZAI Reader failure, LLM failure, empty content, idempotency, re-enrichment,
  batch enrichment, ZAI_API_KEY missing graceful degradation
"""

import os
import tempfile
from pathlib import Path
from typing import Generator

import httpx
import pytest

from data.models import ContentIdea, SourceMaterial
from data.sqlite_store import SQLiteStore
from services.idea_lab import IdeaLabService, _normalize_tags

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
def service(store: SQLiteStore) -> IdeaLabService:
    """Provide a fresh IdeaLabService wrapping a temp-backed store."""
    return IdeaLabService(store)


# ===========================================================================
# 1. SourceMaterial dataclass round-trip
# ===========================================================================


class TestSourceMaterialRoundTrip:
    """Tests for SourceMaterial to_dict / from_dict fidelity."""

    def test_to_dict_from_dict_preserves_all_fields(self):
        """Full round-trip preserves every field value."""
        original = SourceMaterial(
            material_id="mat-1",
            project_id="proj-1",
            material_type="url",
            title="Example",
            url="https://example.com",
            text_content="",
            note="some note",
            source_attribution="Author",
            tags=["tag1", "tag2"],
            metadata_json={"key": "value"},
        )
        result = SourceMaterial.from_dict(original.to_dict())

        assert result.material_id == "mat-1"
        assert result.project_id == "proj-1"
        assert result.material_type == "url"
        assert result.title == "Example"
        assert result.url == "https://example.com"
        assert result.note == "some note"
        assert result.source_attribution == "Author"
        assert result.tags == ["tag1", "tag2"]
        assert result.metadata_json == {"key": "value"}

    def test_defaults_are_empty_collections(self):
        """Default tags and metadata_json are empty list and dict."""
        m = SourceMaterial(project_id="proj-1")
        assert m.tags == []
        assert m.metadata_json == {}
        assert m.material_type == ""
        assert m.title == ""
        assert m.url == ""

    def test_material_id_auto_generated(self):
        """material_id is auto-generated when not provided."""
        m = SourceMaterial()
        assert m.material_id  # non-empty string
        assert len(m.material_id) == 36  # UUID format

    def test_from_dict_missing_optional_fields(self):
        """from_dict uses defaults when optional fields are absent."""
        data = {"material_id": "abc", "project_id": "p1"}
        m = SourceMaterial.from_dict(data)
        assert m.material_id == "abc"
        assert m.project_id == "p1"
        assert m.tags == []
        assert m.metadata_json == {}
        assert m.url == ""
        assert m.text_content == ""
        assert m.note == ""


# ===========================================================================
# 2. SQLiteStore source_material CRUD
# ===========================================================================


class TestStoreSourceMaterialCRUD:
    """Tests for SQLiteStore source_material table operations."""

    def test_save_and_get_by_material_id(self, store: SQLiteStore):
        """Save a record and retrieve it by material_id."""
        record = SourceMaterial(
            material_id="mat-save-get",
            project_id="proj-1",
            material_type="url",
            url="https://example.com",
        ).to_dict()
        store.save_source_material_record(record)

        fetched = store.get_source_material_record("mat-save-get")
        assert fetched is not None
        assert fetched["material_id"] == "mat-save-get"
        assert fetched["url"] == "https://example.com"

    def test_save_replace_true_updates_existing(self, store: SQLiteStore):
        """Saving with replace=True updates an existing record."""
        record = SourceMaterial(
            material_id="mat-replace",
            project_id="proj-1",
            material_type="note",
            note="original",
        ).to_dict()
        store.save_source_material_record(record)

        updated = dict(record)
        updated["note"] = "updated"
        store.save_source_material_record(updated)

        fetched = store.get_source_material_record("mat-replace")
        assert fetched is not None
        assert fetched["note"] == "updated"

    def test_get_returns_none_for_unknown_id(self, store: SQLiteStore):
        """get returns None when no record matches the material_id."""
        result = store.get_source_material_record("nonexistent-id")
        assert result is None

    def test_list_all_records(self, store: SQLiteStore):
        """list with no filters returns all records."""
        for i in range(3):
            store.save_source_material_record(
                SourceMaterial(
                    material_id=f"mat-list-{i}",
                    project_id="proj-1",
                    material_type="note",
                    note=f"item {i}",
                ).to_dict()
            )
        results = store.list_source_material_records()
        assert len(results) == 3

    def test_list_filtered_by_project_id(self, store: SQLiteStore):
        """list with project_id filter returns only matching records."""
        store.save_source_material_record(
            SourceMaterial(material_id="mat-a", project_id="proj-a", material_type="note", note="A").to_dict()
        )
        store.save_source_material_record(
            SourceMaterial(material_id="mat-b", project_id="proj-b", material_type="note", note="B").to_dict()
        )

        results = store.list_source_material_records(project_id="proj-a")
        assert len(results) == 1
        assert results[0]["material_id"] == "mat-a"

    def test_list_filtered_by_material_type(self, store: SQLiteStore):
        """list with material_type filter returns only matching records."""
        store.save_source_material_record(
            SourceMaterial(material_id="mat-url", project_id="proj-1", material_type="url", url="https://x.com").to_dict()
        )
        store.save_source_material_record(
            SourceMaterial(material_id="mat-note", project_id="proj-1", material_type="note", note="hello").to_dict()
        )

        results = store.list_source_material_records(material_type="url")
        assert len(results) == 1
        assert results[0]["material_id"] == "mat-url"

    def test_list_with_limit(self, store: SQLiteStore):
        """list with limit caps the returned records."""
        for i in range(5):
            store.save_source_material_record(
                SourceMaterial(material_id=f"mat-lim-{i}", project_id="proj-1", material_type="note", note=str(i)).to_dict()
            )
        results = store.list_source_material_records(limit=2)
        assert len(results) <= 2

    def test_delete_returns_true_for_existing(self, store: SQLiteStore):
        """delete returns True when the record exists."""
        store.save_source_material_record(
            SourceMaterial(material_id="mat-del", project_id="proj-1", material_type="note", note="bye").to_dict()
        )
        assert store.delete_source_material_record("mat-del") is True
        assert store.get_source_material_record("mat-del") is None

    def test_delete_returns_false_for_unknown(self, store: SQLiteStore):
        """delete returns False when no record matches."""
        assert store.delete_source_material_record("no-such-id") is False

    def test_records_survive_store_reopen(self):
        """Records persist across store close and re-open."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "persist.sqlite3"

            # Write with first store instance
            store1 = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
            store1.save_source_material_record(
                SourceMaterial(material_id="mat-persist", project_id="proj-1", material_type="note", note="survives").to_dict()
            )
            # Close by letting it go out of scope

            # Re-open same database
            store2 = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
            fetched = store2.get_source_material_record("mat-persist")
            assert fetched is not None
            assert fetched["note"] == "survives"


# ===========================================================================
# 3. IdeaLabService envelope validation
# ===========================================================================


class TestIdeaLabServiceValidation:
    """Tests for IdeaLabService envelope validation and auto-detection."""

    def test_add_with_url_sets_type_url(self, service: IdeaLabService):
        """Providing a url sets material_type to 'url'."""
        result = service.add_source_material(
            project_id="proj-1", url="https://example.com"
        )
        assert result["material_type"] == "url"
        assert result["url"] == "https://example.com"

    def test_add_with_text_sets_type_text(self, service: IdeaLabService):
        """Providing text_content (no url) sets material_type to 'text'."""
        result = service.add_source_material(
            project_id="proj-1", text_content="Some interesting passage"
        )
        assert result["material_type"] == "text"

    def test_add_with_note_only_sets_type_note(self, service: IdeaLabService):
        """Providing only note sets material_type to 'note'."""
        result = service.add_source_material(
            project_id="proj-1", note="Just a quick idea"
        )
        assert result["material_type"] == "note"

    def test_add_with_url_and_text_prefers_url(self, service: IdeaLabService):
        """When both url and text_content are provided, type is 'url'."""
        result = service.add_source_material(
            project_id="proj-1",
            url="https://example.com",
            text_content="Some text",
        )
        assert result["material_type"] == "url"

    def test_add_raises_when_no_content_fields(self, service: IdeaLabService):
        """Raises ValueError when url, text_content, and note are all empty."""
        with pytest.raises(ValueError, match="At least one of url, text_content, or note is required"):
            service.add_source_material(project_id="proj-1")

    def test_add_raises_when_all_content_fields_empty(self, service: IdeaLabService):
        """Raises ValueError when all content fields are empty strings."""
        with pytest.raises(ValueError, match="At least one of url, text_content, or note is required"):
            service.add_source_material(project_id="proj-1", url="", text_content="", note="   ")

    def test_add_raises_when_project_id_missing(self, service: IdeaLabService):
        """Raises ValueError when project_id is empty."""
        with pytest.raises(ValueError, match="project_id is required"):
            service.add_source_material(project_id="", note="has content")


# ===========================================================================
# Tag normalization
# ===========================================================================


class TestTagNormalization:
    """Tests for tag normalization via service and the _normalize_tags utility."""

    def test_comma_separated_string_becomes_list(self, service: IdeaLabService):
        """Comma-separated tags string is split into a clean list."""
        result = service.add_source_material(
            project_id="proj-1", note="content", tags="ai, marketing,  strategy  "
        )
        assert result["tags"] == ["ai", "marketing", "strategy"]

    def test_list_input_preserved(self, service: IdeaLabService):
        """List of tags is preserved (stripped, not re-split)."""
        result = service.add_source_material(
            project_id="proj-1", note="content", tags=["alpha", "beta"]
        )
        assert result["tags"] == ["alpha", "beta"]

    def test_tags_deduplicated_preserving_order(self):
        """Duplicate tags are removed, first occurrence preserved."""
        result = _normalize_tags(["ai", "marketing", "ai", "strategy", "marketing"])
        assert result == ["ai", "marketing", "strategy"]

    def test_none_tags_returns_empty_list(self):
        """None input returns an empty list."""
        assert _normalize_tags(None) == []

    def test_empty_string_tags_returns_empty_list(self):
        """Empty string input returns empty list."""
        assert _normalize_tags("") == []


# ===========================================================================
# 4. Project isolation
# ===========================================================================


class TestProjectIsolation:
    """Tests for project-scoped source material visibility."""

    def test_list_only_returns_materials_for_given_project(self, service: IdeaLabService):
        """Listing project A does not include project B's materials."""
        service.add_source_material(project_id="proj-a", note="A content")
        service.add_source_material(project_id="proj-b", note="B content")

        results_a = service.list_source_material(project_id="proj-a")
        assert len(results_a) == 1
        assert results_a[0].note == "A content"

    def test_get_material_works_across_projects(self, service: IdeaLabService):
        """get_source_material works by material_id regardless of project scope."""
        added = service.add_source_material(project_id="proj-x", note="cross-project")
        material_id = added["material_id"]

        # Retrieve without any project scoping
        fetched = service.get_source_material(material_id)
        assert fetched is not None
        assert fetched.note == "cross-project"
        assert fetched.project_id == "proj-x"

    def test_delete_only_affects_targeted_material(self, service: IdeaLabService):
        """Deleting a material from project A does not affect project B."""
        added_a = service.add_source_material(project_id="proj-a", note="A")
        added_b = service.add_source_material(project_id="proj-b", note="B")

        service.delete_source_material(added_a["material_id"])

        # A is gone
        assert service.get_source_material(added_a["material_id"]) is None
        # B still exists
        assert service.get_source_material(added_b["material_id"]) is not None


# ===========================================================================
# 5. Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge-case tests for special characters, long content, and error paths."""

    def test_material_id_with_special_characters(self, store: SQLiteStore):
        """material_id containing colons and periods (common in URLs) works."""
        record = SourceMaterial(
            material_id="https://example.com/path:segment.dots",
            project_id="proj-1",
            material_type="url",
            url="https://example.com/path:segment.dots",
        ).to_dict()
        store.save_source_material_record(record)

        fetched = store.get_source_material_record("https://example.com/path:segment.dots")
        assert fetched is not None
        assert fetched["url"] == "https://example.com/path:segment.dots"

    def test_very_long_text_content(self, service: IdeaLabService):
        """Very long text_content (10k+ chars) is stored and retrieved correctly."""
        long_text = "x" * 15_000
        result = service.add_source_material(
            project_id="proj-1", text_content=long_text
        )
        material_id = result["material_id"]

        fetched = service.get_source_material(material_id)
        assert fetched is not None
        assert fetched.text_content == long_text
        assert len(fetched.text_content) == 15_000

    def test_empty_tags_handled_correctly(self, service: IdeaLabService):
        """Empty list tags result in an empty tags list."""
        result = service.add_source_material(
            project_id="proj-1", note="tagless", tags=[]
        )
        assert result["tags"] == []

    def test_update_raises_for_unknown_material_id(self, service: IdeaLabService):
        """update_source_material raises ValueError for nonexistent material_id."""
        with pytest.raises(ValueError, match="not found"):
            service.update_source_material("nonexistent-id", note="updated")

    def test_update_revalidates_envelope_clearing_content(self, service: IdeaLabService):
        """Updating to clear all content fields raises ValueError."""
        added = service.add_source_material(
            project_id="proj-1", note="original content"
        )
        with pytest.raises(ValueError, match="At least one of url, text_content, or note is required"):
            service.update_source_material(added["material_id"], note="")

    def test_update_auto_redetects_material_type(self, service: IdeaLabService):
        """Update changes material_type when content fields change."""
        added = service.add_source_material(
            project_id="proj-1", note="note only"
        )
        assert added["material_type"] == "note"

        updated = service.update_source_material(
            added["material_id"], url="https://example.com"
        )
        assert updated["material_type"] == "url"


# ===========================================================================
# ContentIdea dataclass round-trip
# ===========================================================================


class TestContentIdeaRoundTrip:
    """Tests for ContentIdea dataclass to_dict / from_dict fidelity."""

    def test_to_dict_from_dict_preserves_all_fields(self):
        idea = ContentIdea(
            idea_id="ci-1",
            project_id="proj-1",
            title="Test Idea",
            hook_angle="Contrarian take",
            target_platforms=["twitter", "linkedin"],
            content_pillar="thought-leadership",
            rationale="Timely topic",
            suggested_format="thread",
            source_material_ids=["sm-1", "sm-2"],
            status="draft",
            evaluation_notes="Looks good",
            tags=["ai", "marketing"],
            metadata_json={"score": 0.85},
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        d = idea.to_dict()
        restored = ContentIdea.from_dict(d)

        assert restored.idea_id == "ci-1"
        assert restored.project_id == "proj-1"
        assert restored.title == "Test Idea"
        assert restored.hook_angle == "Contrarian take"
        assert restored.target_platforms == ["twitter", "linkedin"]
        assert restored.content_pillar == "thought-leadership"
        assert restored.rationale == "Timely topic"
        assert restored.suggested_format == "thread"
        assert restored.source_material_ids == ["sm-1", "sm-2"]
        assert restored.status == "draft"
        assert restored.evaluation_notes == "Looks good"
        assert restored.tags == ["ai", "marketing"]
        assert restored.metadata_json == {"score": 0.85}
        assert restored.created_at == "2025-01-01T00:00:00"
        assert restored.updated_at == "2025-01-01T00:00:00"

    def test_defaults_are_empty_collections(self):
        idea = ContentIdea()
        assert idea.target_platforms == []
        assert idea.source_material_ids == []
        assert idea.tags == []
        assert idea.metadata_json == {}
        assert idea.status == "draft"

    def test_idea_id_auto_generated(self):
        idea = ContentIdea()
        assert len(idea.idea_id) > 0

    def test_from_dict_missing_optional_fields(self):
        minimal = ContentIdea.from_dict({"idea_id": "ci-min"})
        assert minimal.project_id == ""
        assert minimal.title == ""
        assert minimal.hook_angle == ""
        assert minimal.target_platforms == []
        assert minimal.content_pillar == ""
        assert minimal.rationale == ""
        assert minimal.suggested_format == ""
        assert minimal.source_material_ids == []
        assert minimal.status == "draft"
        assert minimal.evaluation_notes == ""
        assert minimal.tags == []
        assert minimal.metadata_json == {}


# ===========================================================================
# SQLiteStore content_ideas CRUD
# ===========================================================================


class TestStoreContentIdeaCRUD:
    """Tests for SQLiteStore content_ideas table operations."""

    def test_save_and_get_by_idea_id(self, store: SQLiteStore):
        record = {
            "idea_id": "ci-save-get",
            "project_id": "proj-1",
            "title": "My Idea",
            "status": "draft",
        }
        store.save_content_idea_record(record)

        fetched = store.get_content_idea_record("ci-save-get")
        assert fetched is not None
        assert fetched["idea_id"] == "ci-save-get"
        assert fetched["title"] == "My Idea"

    def test_save_replace_true_updates_existing(self, store: SQLiteStore):
        record = {
            "idea_id": "ci-replace",
            "project_id": "proj-1",
            "title": "Original",
            "status": "draft",
        }
        store.save_content_idea_record(record)

        updated = dict(record, title="Updated", status="approved")
        store.save_content_idea_record(updated)

        fetched = store.get_content_idea_record("ci-replace")
        assert fetched["title"] == "Updated"
        assert fetched["status"] == "approved"

    def test_get_returns_none_for_unknown_id(self, store: SQLiteStore):
        result = store.get_content_idea_record("nonexistent-id")
        assert result is None

    def test_list_all_records(self, store: SQLiteStore):
        for i in range(3):
            store.save_content_idea_record(
                {"idea_id": f"ci-list-{i}", "project_id": "proj-1", "title": f"Idea {i}"}
            )
        results = store.list_content_idea_records()
        assert len(results) == 3

    def test_list_filtered_by_project_id(self, store: SQLiteStore):
        store.save_content_idea_record(
            {"idea_id": "ci-pa", "project_id": "proj-a", "title": "A"}
        )
        store.save_content_idea_record(
            {"idea_id": "ci-pb", "project_id": "proj-b", "title": "B"}
        )
        results = store.list_content_idea_records(project_id="proj-a")
        assert len(results) == 1
        assert results[0]["idea_id"] == "ci-pa"

    def test_list_filtered_by_status(self, store: SQLiteStore):
        store.save_content_idea_record(
            {"idea_id": "ci-draft", "project_id": "proj-1", "status": "draft"}
        )
        store.save_content_idea_record(
            {"idea_id": "ci-approved", "project_id": "proj-1", "status": "approved"}
        )
        results = store.list_content_idea_records(status="approved")
        assert len(results) == 1
        assert results[0]["idea_id"] == "ci-approved"

    def test_list_filtered_by_content_pillar(self, store: SQLiteStore):
        store.save_content_idea_record(
            {"idea_id": "ci-pillar-1", "project_id": "proj-1", "content_pillar": "growth"}
        )
        store.save_content_idea_record(
            {"idea_id": "ci-pillar-2", "project_id": "proj-1", "content_pillar": "brand"}
        )
        results = store.list_content_idea_records(content_pillar="growth")
        assert len(results) == 1
        assert results[0]["idea_id"] == "ci-pillar-1"

    def test_list_with_limit(self, store: SQLiteStore):
        for i in range(5):
            store.save_content_idea_record(
                {"idea_id": f"ci-lim-{i}", "project_id": "proj-1", "title": f"Idea {i}"}
            )
        results = store.list_content_idea_records(limit=3)
        assert len(results) == 3

    def test_delete_returns_true_for_existing(self, store: SQLiteStore):
        store.save_content_idea_record(
            {"idea_id": "ci-del", "project_id": "proj-1", "title": "Delete me"}
        )
        assert store.delete_content_idea_record("ci-del") is True
        assert store.get_content_idea_record("ci-del") is None

    def test_delete_returns_false_for_unknown(self, store: SQLiteStore):
        assert store.delete_content_idea_record("nonexistent") is False

    def test_records_survive_store_reopen(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite3"
            s1 = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
            s1.save_content_idea_record(
                {"idea_id": "ci-persist", "project_id": "proj-1", "title": "Persist"}
            )

            s2 = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
            fetched = s2.get_content_idea_record("ci-persist")
            assert fetched is not None
            assert fetched["title"] == "Persist"

    def test_normalize_generates_ci_prefix_id(self, store: SQLiteStore):
        normalized = store.normalize_content_idea_record({"project_id": "proj-1"})
        assert normalized["idea_id"].startswith("ci_")

    def test_normalize_defaults_status_to_draft(self, store: SQLiteStore):
        normalized = store.normalize_content_idea_record(
            {"idea_id": "ci-nd", "project_id": "proj-1"}
        )
        assert normalized["status"] == "draft"

    def test_project_isolation_across_ideas(self, store: SQLiteStore):
        store.save_content_idea_record(
            {"idea_id": "ci-x1", "project_id": "proj-x", "title": "X Idea"}
        )
        store.save_content_idea_record(
            {"idea_id": "ci-y1", "project_id": "proj-y", "title": "Y Idea"}
        )
        results_x = store.list_content_idea_records(project_id="proj-x")
        results_y = store.list_content_idea_records(project_id="proj-y")
        assert len(results_x) == 1
        assert len(results_y) == 1
        assert results_x[0]["idea_id"] == "ci-x1"
        assert results_y[0]["idea_id"] == "ci-y1"

    def test_list_combined_filters(self, store: SQLiteStore):
        store.save_content_idea_record(
            {"idea_id": "ci-cf1", "project_id": "proj-1", "status": "draft", "content_pillar": "growth"}
        )
        store.save_content_idea_record(
            {"idea_id": "ci-cf2", "project_id": "proj-1", "status": "approved", "content_pillar": "growth"}
        )
        store.save_content_idea_record(
            {"idea_id": "ci-cf3", "project_id": "proj-2", "status": "draft", "content_pillar": "growth"}
        )
        results = store.list_content_idea_records(
            project_id="proj-1", status="draft", content_pillar="growth"
        )
        assert len(results) == 1
        assert results[0]["idea_id"] == "ci-cf1"


# ===========================================================================
# IdeaLabService content idea methods + evaluation lifecycle
# ===========================================================================


class TestIdeaLabServiceContentIdeaCRUD:
    """Tests for IdeaLabService content idea CRUD methods."""

    def test_add_content_idea_persists_and_returns(self, service: IdeaLabService):
        """add_content_idea creates a draft idea and returns the persisted record."""
        result = service.add_content_idea(
            project_id="proj-1",
            title="AI Marketing Trend",
            hook_angle="Contrarian take on AI hype",
            target_platforms=["twitter", "linkedin"],
            content_pillar="thought-leadership",
            rationale="Timely and differentiated",
            suggested_format="thread",
            source_material_ids=["sm-1"],
            tags=["ai", "marketing"],
            metadata={"score": 0.9},
        )
        assert result["project_id"] == "proj-1"
        assert result["title"] == "AI Marketing Trend"
        assert result["hook_angle"] == "Contrarian take on AI hype"
        assert result["target_platforms"] == ["twitter", "linkedin"]
        assert result["content_pillar"] == "thought-leadership"
        assert result["status"] == "draft"
        assert result["tags"] == ["ai", "marketing"]
        assert result["metadata_json"] == {"score": 0.9}
        assert result["source_material_ids"] == ["sm-1"]

        # Verify persisted
        fetched = service.get_content_idea(result["idea_id"])
        assert fetched is not None
        assert fetched.title == "AI Marketing Trend"

    def test_add_content_idea_auto_generates_id(self, service: IdeaLabService):
        """add_content_idea generates an idea_id automatically."""
        result = service.add_content_idea(project_id="proj-1", title="Test")
        assert result["idea_id"]
        assert result["idea_id"].startswith("ci_")

    def test_add_content_idea_sets_status_draft(self, service: IdeaLabService):
        """New ideas always start as draft regardless of input."""
        result = service.add_content_idea(project_id="proj-1", title="Test")
        assert result["status"] == "draft"

    def test_add_content_idea_normalizes_tags(self, service: IdeaLabService):
        """Tags are normalized (stripped, deduplicated) on add."""
        result = service.add_content_idea(
            project_id="proj-1",
            title="Test",
            tags="  ai,  marketing, ai  ",
        )
        assert result["tags"] == ["ai", "marketing"]

    def test_add_content_idea_raises_without_project_id(self, service: IdeaLabService):
        """Raises ValueError when project_id is empty."""
        with pytest.raises(ValueError, match="project_id is required"):
            service.add_content_idea(project_id="", title="Test")

    def test_add_content_idea_minimal_fields(self, service: IdeaLabService):
        """add_content_idea works with only required fields."""
        result = service.add_content_idea(project_id="proj-1", title="Minimal")
        assert result["project_id"] == "proj-1"
        assert result["title"] == "Minimal"
        assert result["hook_angle"] == ""
        assert result["target_platforms"] == []
        assert result["tags"] == []

    def test_get_content_idea_returns_none_for_unknown(self, service: IdeaLabService):
        """get_content_idea returns None for nonexistent ID."""
        assert service.get_content_idea("nonexistent") is None

    def test_get_content_idea_returns_dataclass(self, service: IdeaLabService):
        """get_content_idea returns a ContentIdea instance."""
        added = service.add_content_idea(project_id="proj-1", title="Fetch me")
        fetched = service.get_content_idea(added["idea_id"])
        assert isinstance(fetched, ContentIdea)
        assert fetched.title == "Fetch me"

    def test_list_content_ideas_returns_dataclass_instances(self, service: IdeaLabService):
        """list_content_ideas returns ContentIdea instances."""
        service.add_content_idea(project_id="proj-1", title="Idea 1")
        service.add_content_idea(project_id="proj-1", title="Idea 2")
        results = service.list_content_ideas(project_id="proj-1")
        assert len(results) == 2
        assert all(isinstance(r, ContentIdea) for r in results)

    def test_list_content_ideas_filtered_by_status(self, service: IdeaLabService):
        """list_content_ideas filters by status."""
        service.add_content_idea(project_id="proj-1", title="Draft idea")
        approved = service.add_content_idea(project_id="proj-1", title="To approve")
        service.evaluate_content_idea(approved["idea_id"], "approved")

        results = service.list_content_ideas(project_id="proj-1", status="approved")
        assert len(results) == 1
        assert results[0].title == "To approve"

    def test_list_content_ideas_filtered_by_pillar(self, service: IdeaLabService):
        """list_content_ideas filters by content_pillar."""
        service.add_content_idea(
            project_id="proj-1", title="Growth", content_pillar="growth"
        )
        service.add_content_idea(
            project_id="proj-1", title="Brand", content_pillar="brand"
        )
        results = service.list_content_ideas(
            project_id="proj-1", content_pillar="growth"
        )
        assert len(results) == 1
        assert results[0].title == "Growth"

    def test_list_content_ideas_with_limit(self, service: IdeaLabService):
        """list_content_ideas respects limit parameter."""
        for i in range(5):
            service.add_content_idea(project_id="proj-1", title=f"Idea {i}")
        results = service.list_content_ideas(project_id="proj-1", limit=2)
        assert len(results) == 2

    def test_update_content_idea_merges_fields(self, service: IdeaLabService):
        """update_content_idea merges provided fields into existing record."""
        added = service.add_content_idea(
            project_id="proj-1", title="Original", rationale="First rationale"
        )
        updated = service.update_content_idea(
            added["idea_id"], title="Updated Title", rationale="New rationale"
        )
        assert updated["title"] == "Updated Title"
        assert updated["rationale"] == "New rationale"
        assert updated["project_id"] == "proj-1"  # unchanged

    def test_update_content_idea_updates_timestamp(self, service: IdeaLabService):
        """update_content_idea updates the updated_at field."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        original_updated_at = added["updated_at"]

        updated = service.update_content_idea(
            added["idea_id"], title="Changed"
        )
        assert updated["updated_at"] >= original_updated_at

    def test_update_content_idea_normalizes_tags(self, service: IdeaLabService):
        """update_content_idea re-normalizes tags when provided."""
        added = service.add_content_idea(
            project_id="proj-1", title="Test", tags=["a", "b"]
        )
        updated = service.update_content_idea(
            added["idea_id"], tags="  c, d  "
        )
        assert updated["tags"] == ["c", "d"]

    def test_update_content_idea_raises_for_unknown(self, service: IdeaLabService):
        """update_content_idea raises ValueError for nonexistent ID."""
        with pytest.raises(ValueError, match="not found"):
            service.update_content_idea("nonexistent", title="X")

    def test_update_content_idea_blocks_status_change(self, service: IdeaLabService):
        """update_content_idea raises ValueError if status is in kwargs."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        with pytest.raises(ValueError, match="evaluate_content_idea"):
            service.update_content_idea(added["idea_id"], status="approved")

    def test_delete_content_idea_removes_record(self, service: IdeaLabService):
        """delete_content_idea removes the idea from the store."""
        added = service.add_content_idea(project_id="proj-1", title="Delete me")
        assert service.delete_content_idea(added["idea_id"]) is True
        assert service.get_content_idea(added["idea_id"]) is None

    def test_delete_content_idea_returns_false_for_unknown(self, service: IdeaLabService):
        """delete_content_idea returns False for nonexistent ID."""
        assert service.delete_content_idea("nonexistent") is False


# ===========================================================================
# Content idea evaluation lifecycle
# ===========================================================================


class TestContentIdeaEvaluationLifecycle:
    """Tests for evaluate_content_idea status transition validation."""

    def test_draft_to_approved(self, service: IdeaLabService):
        """Valid transition: draft → approved."""
        added = service.add_content_idea(project_id="proj-1", title="Good idea")
        result = service.evaluate_content_idea(
            added["idea_id"], "approved", evaluation_notes="Strong hook"
        )
        assert result["status"] == "approved"
        assert result["evaluation_notes"] == "Strong hook"

    def test_draft_to_rejected(self, service: IdeaLabService):
        """Valid transition: draft → rejected."""
        added = service.add_content_idea(project_id="proj-1", title="Weak idea")
        result = service.evaluate_content_idea(
            added["idea_id"], "rejected", evaluation_notes="Too generic"
        )
        assert result["status"] == "rejected"
        assert result["evaluation_notes"] == "Too generic"

    def test_approved_to_draft(self, service: IdeaLabService):
        """Valid transition: approved → draft (reconsideration)."""
        added = service.add_content_idea(project_id="proj-1", title="Reconsider")
        service.evaluate_content_idea(added["idea_id"], "approved")
        result = service.evaluate_content_idea(added["idea_id"], "draft")
        assert result["status"] == "draft"

    def test_rejected_to_draft(self, service: IdeaLabService):
        """Valid transition: rejected → draft (reconsideration)."""
        added = service.add_content_idea(project_id="proj-1", title="Revive")
        service.evaluate_content_idea(added["idea_id"], "rejected")
        result = service.evaluate_content_idea(added["idea_id"], "draft")
        assert result["status"] == "draft"

    def test_approved_to_approved_is_invalid(self, service: IdeaLabService):
        """Invalid transition: approved → approved raises ValueError."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        service.evaluate_content_idea(added["idea_id"], "approved")
        with pytest.raises(ValueError, match="Invalid status transition"):
            service.evaluate_content_idea(added["idea_id"], "approved")

    def test_approved_to_rejected_is_invalid(self, service: IdeaLabService):
        """Invalid transition: approved → rejected raises ValueError."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        service.evaluate_content_idea(added["idea_id"], "approved")
        with pytest.raises(ValueError, match="Invalid status transition"):
            service.evaluate_content_idea(added["idea_id"], "rejected")

    def test_rejected_to_approved_is_invalid(self, service: IdeaLabService):
        """Invalid transition: rejected → approved raises ValueError."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        service.evaluate_content_idea(added["idea_id"], "rejected")
        with pytest.raises(ValueError, match="Invalid status transition"):
            service.evaluate_content_idea(added["idea_id"], "approved")

    def test_rejected_to_rejected_is_invalid(self, service: IdeaLabService):
        """Invalid transition: rejected → rejected raises ValueError."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        service.evaluate_content_idea(added["idea_id"], "rejected")
        with pytest.raises(ValueError, match="Invalid status transition"):
            service.evaluate_content_idea(added["idea_id"], "rejected")

    def test_draft_to_draft_is_invalid(self, service: IdeaLabService):
        """Invalid transition: draft → draft raises ValueError."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        with pytest.raises(ValueError, match="Invalid status transition"):
            service.evaluate_content_idea(added["idea_id"], "draft")

    def test_evaluate_raises_for_unknown_idea(self, service: IdeaLabService):
        """evaluate_content_idea raises ValueError for nonexistent ID."""
        with pytest.raises(ValueError, match="not found"):
            service.evaluate_content_idea("nonexistent", "approved")

    def test_evaluate_updates_timestamp(self, service: IdeaLabService):
        """evaluate_content_idea updates the updated_at field."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        original_updated_at = added["updated_at"]
        result = service.evaluate_content_idea(added["idea_id"], "approved")
        assert result["updated_at"] >= original_updated_at

    def test_evaluate_without_notes_preserves_existing(self, service: IdeaLabService):
        """Passing evaluation_notes=None preserves existing notes."""
        added = service.add_content_idea(
            project_id="proj-1",
            title="Test",
            metadata={"notes": "initial"},  # no evaluation_notes set on add
        )
        # First evaluate with notes
        service.evaluate_content_idea(
            added["idea_id"], "approved", evaluation_notes="Good"
        )
        # Revert to draft without notes
        result = service.evaluate_content_idea(
            added["idea_id"], "draft", evaluation_notes=None
        )
        # evaluation_notes should remain "Good" since None means "don't change"
        assert result["evaluation_notes"] == "Good"

    def test_evaluate_with_empty_notes_overwrites(self, service: IdeaLabService):
        """Passing empty string for evaluation_notes overwrites existing notes."""
        added = service.add_content_idea(project_id="proj-1", title="Test")
        service.evaluate_content_idea(
            added["idea_id"], "approved", evaluation_notes="Initial"
        )
        result = service.evaluate_content_idea(
            added["idea_id"], "draft", evaluation_notes=""
        )
        assert result["evaluation_notes"] == ""

    def test_full_lifecycle_round_trip(self, service: IdeaLabService):
        """Exercise a complete lifecycle: draft → approved → draft → rejected → draft."""
        added = service.add_content_idea(
            project_id="proj-1",
            title="Lifecycle test",
            hook_angle="Data-driven",
        )

        r1 = service.evaluate_content_idea(added["idea_id"], "approved", evaluation_notes="Approved v1")
        assert r1["status"] == "approved"

        r2 = service.evaluate_content_idea(added["idea_id"], "draft", evaluation_notes="Reconsidering")
        assert r2["status"] == "draft"

        r3 = service.evaluate_content_idea(added["idea_id"], "rejected", evaluation_notes="Not aligned")
        assert r3["status"] == "rejected"

        r4 = service.evaluate_content_idea(added["idea_id"], "draft", evaluation_notes="Back to drafting")
        assert r4["status"] == "draft"

        # Verify all fields intact through transitions
        fetched = service.get_content_idea(added["idea_id"])
        assert fetched.title == "Lifecycle test"
        assert fetched.hook_angle == "Data-driven"
        assert fetched.evaluation_notes == "Back to drafting"


# ===========================================================================
# Content idea project isolation
# ===========================================================================


class TestContentIdeaProjectIsolation:
    """Tests for content idea project-scoped visibility and isolation."""

    def test_list_returns_only_matching_project(self, service: IdeaLabService):
        """list_content_ideas only returns ideas for the specified project."""
        service.add_content_idea(project_id="proj-alpha", title="Alpha Idea 1")
        service.add_content_idea(project_id="proj-alpha", title="Alpha Idea 2")
        service.add_content_idea(project_id="proj-beta", title="Beta Idea 1")

        alpha = service.list_content_ideas(project_id="proj-alpha")
        beta = service.list_content_ideas(project_id="proj-beta")

        assert len(alpha) == 2
        assert len(beta) == 1
        assert all(i.project_id == "proj-alpha" for i in alpha)
        assert all(i.project_id == "proj-beta" for i in beta)

    def test_cross_project_ideas_invisible_in_list(self, service: IdeaLabService):
        """Ideas from project A never appear in project B's listing."""
        service.add_content_idea(
            project_id="proj-x", title="X Secret", tags=["confidential"]
        )
        service.add_content_idea(
            project_id="proj-y", title="Y Public", tags=["public"]
        )

        y_ideas = service.list_content_ideas(project_id="proj-y")
        titles = [i.title for i in y_ideas]
        assert "X Secret" not in titles
        assert "Y Public" in titles

    def test_get_works_across_projects_by_id(self, service: IdeaLabService):
        """get_content_idea can retrieve any idea by ID regardless of project scope."""
        added = service.add_content_idea(
            project_id="proj-remote", title="Cross-project fetch"
        )
        # No project scope needed for direct ID lookup
        fetched = service.get_content_idea(added["idea_id"])
        assert fetched is not None
        assert fetched.project_id == "proj-remote"
        assert fetched.title == "Cross-project fetch"

    def test_delete_scoped_to_single_idea_across_projects(self, service: IdeaLabService):
        """Deleting an idea from one project does not affect another project's ideas."""
        a = service.add_content_idea(project_id="proj-a", title="A Idea")
        b = service.add_content_idea(project_id="proj-b", title="B Idea")

        service.delete_content_idea(a["idea_id"])

        assert service.get_content_idea(a["idea_id"]) is None
        assert service.get_content_idea(b["idea_id"]) is not None

    def test_evaluate_does_not_leak_across_projects(self, service: IdeaLabService):
        """Evaluating an idea in one project has no side effects on another."""
        a = service.add_content_idea(project_id="proj-a", title="A Eval")
        b = service.add_content_idea(project_id="proj-b", title="B Draft")

        service.evaluate_content_idea(a["idea_id"], "approved", evaluation_notes="Great")

        # B should still be draft
        fetched_b = service.get_content_idea(b["idea_id"])
        assert fetched_b.status == "draft"
        assert fetched_b.evaluation_notes == ""

    def test_status_filter_is_project_scoped(self, service: IdeaLabService):
        """Listing approved ideas for one project excludes another's approved ideas."""
        service.add_content_idea(project_id="proj-a", title="A Draft")
        a2 = service.add_content_idea(project_id="proj-a", title="A Approved")
        b1 = service.add_content_idea(project_id="proj-b", title="B Approved")

        service.evaluate_content_idea(a2["idea_id"], "approved")
        service.evaluate_content_idea(b1["idea_id"], "approved")

        a_approved = service.list_content_ideas(project_id="proj-a", status="approved")
        assert len(a_approved) == 1
        assert a_approved[0].title == "A Approved"

        b_approved = service.list_content_ideas(project_id="proj-b", status="approved")
        assert len(b_approved) == 1
        assert b_approved[0].title == "B Approved"


# ===========================================================================
# Enrichment unit tests (mocked LLM + ZAI Reader)
# ===========================================================================

# Helper: build a fake litellm response
def _fake_llm_response(content: str):
    """Create a mock litellm.completion() return value."""
    return type("Resp", (), {"choices": [type("Choice", (), {"message": type("Msg", (), {"content": content})()})()]})()


def _fake_zai_response(text: str, status_code: int = 200):
    """Create a mock httpx.Response for ZAI Reader."""
    resp = type("Resp", (), {
        "status_code": status_code,
        "json": lambda self: {
            "jsonrpc": "2.0",
            "result": {"content": [{"type": "text", "text": text}]},
            "id": 1,
        },
        "raise_for_status": lambda self: None,
    })()
    return resp


class TestURLEnrichmentHappyPath:
    """URL enrichment: mocked httpx.post returns ZAI content, mocked litellm returns key points + tags."""

    def test_url_enrichment_stores_key_points_and_tags(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", url="https://example.com/article", title="Test URL"
        )
        mid = mat["material_id"]

        llm_call_count = 0
        def mock_completion(**kwargs):
            nonlocal llm_call_count
            llm_call_count += 1
            if llm_call_count == 1:
                # _extract_key_points call
                return _fake_llm_response('["Key point 1", "Key point 2", "Key point 3"]')
            else:
                # _generate_auto_tags call
                return _fake_llm_response('["ai", "marketing", "strategy"]')

        import unittest.mock
        with unittest.mock.patch.dict(os.environ, {"ZAI_API_KEY": "test-key"}):
            with unittest.mock.patch("services.idea_lab.litellm.completion", side_effect=mock_completion):
                with unittest.mock.patch("services.idea_lab.httpx.Client") as MockClient:
                    cm = MockClient.return_value
                    client_instance = cm.__enter__.return_value
                    client_instance.post.return_value = _fake_zai_response("Fetched article content about AI marketing.")
                    result = service.enrich_source_material(mid)

        meta = result["metadata_json"]
        assert meta["enrichment_status"] == "enriched"
        assert len(meta["key_points"]) == 3
        assert meta["key_points"][0] == "Key point 1"
        assert meta["auto_tags"] == ["ai", "marketing", "strategy"]
        assert meta["fetched_content_length"] > 0
        assert "enriched_at" in meta


class TestTextEnrichment:
    """Text enrichment: no URL fetch, LLM extracts key points + generates tags."""

    def test_text_enrichment_key_points_and_tags(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", text_content="A long article about AI trends in marketing."
        )
        mid = mat["material_id"]

        import unittest.mock
        llm_call_count = 0
        def mock_completion(**kwargs):
            nonlocal llm_call_count
            llm_call_count += 1
            if llm_call_count == 1:
                return _fake_llm_response('["AI is growing", "Marketing is evolving"]')
            else:
                return _fake_llm_response('["ai", "trends"]')

        with unittest.mock.patch("services.idea_lab.litellm.completion", side_effect=mock_completion):
            result = service.enrich_source_material(mid)

        meta = result["metadata_json"]
        assert meta["enrichment_status"] == "enriched"
        assert len(meta["key_points"]) == 2
        assert "auto_tags" in meta
        assert "fetched_content_length" not in meta  # no URL fetch for text


class TestNoteEnrichment:
    """Note enrichment: only auto-tags, no key points, no URL fetch."""

    def test_note_enrichment_auto_tags_only(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", note="Quick idea about content repurposing"
        )
        mid = mat["material_id"]

        import unittest.mock
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_response('["content", "repurposing", "idea"]')):
            result = service.enrich_source_material(mid)

        meta = result["metadata_json"]
        assert meta["enrichment_status"] == "enriched"
        assert "key_points" not in meta
        assert len(meta["auto_tags"]) == 3


class TestZAIReaderFailure:
    """ZAI Reader failure: httpx raises timeout → enrichment_status="failed"."""

    def test_url_enrichment_timeout_sets_failed(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", url="https://slow.example.com"
        )
        mid = mat["material_id"]

        import unittest.mock
        with unittest.mock.patch.dict(os.environ, {"ZAI_API_KEY": "test-key"}):
            with unittest.mock.patch("services.idea_lab.httpx.Client") as MockClient:
                cm = MockClient.return_value
                client_instance = cm.__enter__.return_value
                client_instance.post.side_effect = httpx.TimeoutException("timeout")
                result = service.enrich_source_material(mid)

        meta = result["metadata_json"]
        assert meta["enrichment_status"] == "failed"
        assert "enrichment_error" in meta
        assert "timeout" in meta["enrichment_error"].lower() or "URL fetch failed" in meta["enrichment_error"]


class TestLLMFailure:
    """LLM failure: litellm raises exception → enrichment_status="failed"."""

    def test_llm_failure_sets_failed_status(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", text_content="Some content here"
        )
        mid = mat["material_id"]

        import unittest.mock
        with unittest.mock.patch("services.idea_lab.litellm.completion", side_effect=Exception("LLM unavailable")):
            result = service.enrich_source_material(mid)

        meta = result["metadata_json"]
        assert meta["enrichment_status"] == "failed"
        assert "enrichment_error" in meta
        # The retry decorator wraps the error in RetryError
        assert "Key point extraction failed" in meta["enrichment_error"]


class TestEmptyContent:
    """Empty/short content: ZAI Reader returns minimal content → enrichment_status="partial"."""

    def test_empty_zai_content_yields_partial(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", url="https://empty.example.com"
        )
        mid = mat["material_id"]

        import unittest.mock
        # ZAI returns empty → _fetch_url_content raises ValueError
        with unittest.mock.patch.dict(os.environ, {"ZAI_API_KEY": "test-key"}):
            with unittest.mock.patch("services.idea_lab.httpx.Client") as MockClient:
                cm = MockClient.return_value
                client_instance = cm.__enter__.return_value
                # Return empty content so ZAI reader raises
                resp = type("Resp", (), {
                    "status_code": 200,
                    "json": lambda self: {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": ""}]}, "id": 1},
                    "raise_for_status": lambda self: None,
                })()
                client_instance.post.return_value = resp
                # LLM still called for tags from empty content_for_tagging
                with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_response('["generic"]')):
                    result = service.enrich_source_material(mid)

        meta = result["metadata_json"]
        # URL fetch fails with empty content, key_points skipped, auto_tags may still work
        assert meta["enrichment_status"] in ("partial", "failed")


class TestEnrichmentIdempotency:
    """Idempotency: calling enrich on already-enriched material skips processing."""

    def test_enriched_material_is_skipped(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", note="Already done"
        )
        mid = mat["material_id"]

        import unittest.mock
        # First enrichment
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_response('["tag1"]')):
            result1 = service.enrich_source_material(mid)
        assert result1["metadata_json"]["enrichment_status"] == "enriched"

        # Second call should be no-op — litellm should NOT be called
        call_count = 0
        def counting_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            return _fake_llm_response('["should-not-happen"]')

        with unittest.mock.patch("services.idea_lab.litellm.completion", side_effect=counting_completion):
            result2 = service.enrich_source_material(mid)

        assert call_count == 0  # no LLM calls on already-enriched
        assert result2["metadata_json"]["auto_tags"] == ["tag1"]  # preserved


class TestReEnrichment:
    """Re-enrichment: calling enrich on "failed" material retries successfully."""

    def test_failed_material_can_be_re_enriched(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", note="Will fail first"
        )
        mid = mat["material_id"]

        import unittest.mock
        # First call: LLM fails
        with unittest.mock.patch("services.idea_lab.litellm.completion", side_effect=Exception("Transient error")):
            result1 = service.enrich_source_material(mid)
        assert result1["metadata_json"]["enrichment_status"] == "failed"

        # Second call: LLM succeeds — should retry
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_response('["recovered-tag"]')):
            result2 = service.enrich_source_material(mid)
        assert result2["metadata_json"]["enrichment_status"] == "enriched"
        assert result2["metadata_json"]["auto_tags"] == ["recovered-tag"]


class TestBatchEnrichment:
    """Batch enrichment: enrich_all_pending processes multiple un-enriched materials."""

    def test_batch_enriches_all_pending(self, service: IdeaLabService):
        service.add_source_material(project_id="proj-1", note="Note 1")
        service.add_source_material(project_id="proj-1", note="Note 2")
        service.add_source_material(project_id="proj-1", note="Note 3")

        import unittest.mock
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_response('["batch-tag"]')):
            counts = service.enrich_all_pending("proj-1")

        assert counts["total"] == 3
        assert counts["enriched"] == 3
        assert counts["skipped"] == 0

    def test_batch_skips_already_enriched(self, service: IdeaLabService):
        service.add_source_material(project_id="proj-1", note="Note A")
        mat_b = service.add_source_material(project_id="proj-1", note="Note B")

        import unittest.mock
        # Enrich one manually
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_response('["tag"]')):
            service.enrich_source_material(mat_b["material_id"])

        # Batch should skip the enriched one
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_response('["batch-tag"]')):
            counts = service.enrich_all_pending("proj-1")

        assert counts["total"] == 2
        assert counts["enriched"] == 1
        assert counts["skipped"] == 1


class TestZAIKeyMissing:
    """ZAI_API_KEY not set → graceful degradation for URL enrichment."""

    def test_missing_zai_key_graceful_failure(self, service: IdeaLabService):
        mat = service.add_source_material(
            project_id="proj-1", url="https://example.com/no-key"
        )
        mid = mat["material_id"]

        import unittest.mock
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            # Remove ZAI_API_KEY if present
            os.environ.pop("ZAI_API_KEY", None)
            # httpx.Client shouldn't be called since _fetch_url_content returns early
            with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_response('["fallback-tag"]')):
                result = service.enrich_source_material(mid)

        meta = result["metadata_json"]
        assert meta["enrichment_status"] in ("partial", "failed")
        assert "enrichment_error" in meta
