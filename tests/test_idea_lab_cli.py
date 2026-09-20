#!/usr/bin/env python3
"""Tests for idea lab CLI commands.

Uses direct function calls with mock args objects instead of subprocess
invocation to avoid data-dir coupling and ensure test isolation.
Each test creates a temp data dir and constructs an IdeaLabService from it.
"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Generator

import pytest

from data.sqlite_store import SQLiteStore
from services.idea_lab import IdeaLabService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def idea_lab() -> Generator[IdeaLabService, None, None]:
    """Provide a fresh IdeaLabService backed by a temp database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        store = SQLiteStore(data_dir=tmpdir, db_path=db_path, migrate=False)
        yield IdeaLabService(store)


PROJECT_ID = "test-cli-project"


def _parse_json_output(output: str) -> dict:
    """Parse the last JSON object from CLI stdout."""
    return json.loads(output)


# ===========================================================================
# Material CLI Commands
# ===========================================================================


class TestCLIMaterialCommands:
    """Tests for cli.py ideas material {add,list,get,delete} commands."""

    def test_material_add(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_material_add
        args = SimpleNamespace(
            project_id=PROJECT_ID, url="https://example.com/test",
            text=None, note=None, title="Test Material", tags="tag1,tag2",
        )
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_material_add(args)
        output = f.getvalue()
        assert rc == 0
        data = _parse_json_output(output)
        assert data["material_type"] == "url"
        assert data["title"] == "Test Material"

    def test_material_list(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_material_list
        idea_lab.add_source_material(
            project_id=PROJECT_ID, url="https://example.com/list-test",
            title="List Test Material",
        )
        args = SimpleNamespace(project_id=PROJECT_ID, type=None, limit=None)
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_material_list(args)
        output = f.getvalue()
        assert rc == 0
        assert "List Test Material" in output
        assert "Total: 1" in output

    def test_material_get(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_material_get
        result = idea_lab.add_source_material(
            project_id=PROJECT_ID, url="https://example.com/get-test",
            title="Get Test Material",
        )
        material_id = result["material_id"]
        args = SimpleNamespace(material_id=material_id)
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_material_get(args)
        output = f.getvalue()
        assert rc == 0
        data = _parse_json_output(output)
        assert data["material_id"] == material_id

    def test_material_delete(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_material_delete
        result = idea_lab.add_source_material(
            project_id=PROJECT_ID, url="https://example.com/del-test",
        )
        material_id = result["material_id"]
        args = SimpleNamespace(material_id=material_id)
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_material_delete(args)
        output = f.getvalue()
        assert rc == 0
        assert f"Deleted source material '{material_id}'" in output


# ===========================================================================
# Idea CLI Commands
# ===========================================================================


class TestCLIIdeaCommands:
    """Tests for cli.py ideas idea {add,list,get,update,evaluate,delete}."""

    def test_idea_add(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_idea_add
        args = SimpleNamespace(
            project_id=PROJECT_ID, title="CLI Test Idea", hook="Test hook",
            platforms="twitter,linkedin", pillar="growth", tags="test,cli",
        )
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_idea_add(args)
        output = f.getvalue()
        assert rc == 0
        data = _parse_json_output(output)
        assert data["title"] == "CLI Test Idea"
        assert data["status"] == "draft"

    def test_idea_list(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_idea_list
        idea_lab.add_content_idea(project_id=PROJECT_ID, title="List Idea 1", content_pillar="growth")
        idea_lab.add_content_idea(project_id=PROJECT_ID, title="List Idea 2", content_pillar="engagement")
        args = SimpleNamespace(project_id=PROJECT_ID, status=None, pillar=None, limit=None)
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_idea_list(args)
        output = f.getvalue()
        assert rc == 0
        assert "Total: 2" in output

    def test_idea_get(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_idea_get
        result = idea_lab.add_content_idea(project_id=PROJECT_ID, title="Get Idea", hook_angle="Test hook")
        idea_id = result["idea_id"]
        args = SimpleNamespace(idea_id=idea_id)
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_idea_get(args)
        output = f.getvalue()
        assert rc == 0
        data = _parse_json_output(output)
        assert data["idea_id"] == idea_id

    def test_idea_update(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_idea_update
        result = idea_lab.add_content_idea(project_id=PROJECT_ID, title="Original Title")
        idea_id = result["idea_id"]
        args = SimpleNamespace(idea_id=idea_id, title="Updated Title", hook=None, tags="new,tags")
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_idea_update(args)
        output = f.getvalue()
        assert rc == 0
        data = _parse_json_output(output)
        assert data["title"] == "Updated Title"

    def test_idea_evaluate(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_idea_evaluate
        result = idea_lab.add_content_idea(project_id=PROJECT_ID, title="Evaluate Idea")
        idea_id = result["idea_id"]
        args = SimpleNamespace(idea_id=idea_id, status="approved", notes="Looks good")
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_idea_evaluate(args)
        output = f.getvalue()
        assert rc == 0
        data = _parse_json_output(output)
        assert data["status"] == "approved"

    def test_idea_delete(self, idea_lab, monkeypatch):
        from cli import cmd_ideas_idea_delete
        result = idea_lab.add_content_idea(project_id=PROJECT_ID, title="Delete Me")
        idea_id = result["idea_id"]
        args = SimpleNamespace(idea_id=idea_id)
        monkeypatch.setattr("cli._get_idea_lab", lambda: idea_lab)
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_idea_delete(args)
        output = f.getvalue()
        assert rc == 0
        assert f"Deleted content idea '{idea_id}'" in output


# ===========================================================================
# Mining Command
# ===========================================================================


class TestCLIMiningCommand:
    """Tests for cli.py ideas mine command (delegates to idea-mining tick)."""

    def test_mine_delegates_to_idea_mining_tick(self, monkeypatch):
        import io
        from contextlib import redirect_stdout
        from cli import cmd_ideas_mine
        captured = {}

        def _fake_tick(args):
            captured["data_dir"] = args.data_dir
            captured["dry_run"] = args.dry_run
            captured["force_project"] = args.force_project
            print(json.dumps({"enqueued": 1, "skipped": []}))
            return 0

        monkeypatch.setattr("cli.cmd_idea_mining_tick", _fake_tick)
        args = SimpleNamespace(project_id=PROJECT_ID)
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_mine(args)
        assert rc == 0
        assert captured == {
            "data_dir": None, "dry_run": False, "force_project": PROJECT_ID,
        }

    def test_mine_requires_project_id(self):
        import io
        from contextlib import redirect_stdout
        from cli import cmd_ideas_mine
        args = SimpleNamespace(project_id=None)
        f = io.StringIO()
        with redirect_stdout(f):
            rc = cmd_ideas_mine(args)
        assert rc == 1
        assert "--project-id is required" in f.getvalue()
