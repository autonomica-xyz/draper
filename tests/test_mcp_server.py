"""Tests for the Draper MCP server tool registration and basic execution."""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="draper-mcp-test-"))
os.environ["DRAPER_DATA_DIR"] = str(TEST_DATA_DIR)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _set_project():
    """Ensure a valid project is current for every test."""
    from projects.manager import ProjectManager

    pm = ProjectManager(data_dir=str(TEST_DATA_DIR))
    projects = pm.list_projects()
    project = projects[0] if projects else pm.create_project(
        "MCP Test Project",
        description="Isolated project for MCP tests",
    )
    pm.set_current_project(project.project_id)
    yield


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all expected tools are registered with the MCP server."""

    def test_server_loads(self):
        from mcp_server.server import mcp

        assert mcp is not None

    def test_tool_count(self):
        from mcp_server.server import mcp

        tools = mcp._tool_manager._tools
        # We expect at least 35 tools (39 as of initial build)
        assert len(tools) >= 35, f"Expected >= 35 tools, got {len(tools)}"

    @pytest.mark.parametrize(
        "tool_name",
        [
            "list_projects",
            "get_current_project",
            "set_current_project",
            "create_project",
            "generate_content",
            "generate_long_form",
            "list_content",
            "get_content",
            "approve_content",
            "decline_content",
            "request_fix",
            "add_source_material",
            "list_source_materials",
            "enrich_source_material",
            "delete_source_material",
            "generate_ideas",
            "add_content_idea",
            "list_content_ideas",
            "get_content_idea",
            "evaluate_idea",
            "approve_and_generate_from_idea",
            "delete_content_idea",
            "run_mining",
            "publish_content",
            "list_scheduled_posts",
            "get_analytics",
            "sync_analytics",
            "list_jobs",
            "get_job_status",
            "cancel_job",
            "get_content_plan",
            "update_content_plan",
            "get_brand_voice",
            "update_brand_voice",
            "get_system_status",
        ],
    )
    def test_tool_registered(self, tool_name):
        from mcp_server.server import mcp

        tools = mcp._tool_manager._tools
        assert tool_name in tools, f"Tool '{tool_name}' not registered"


# ---------------------------------------------------------------------------
# Tool execution — project tools
# ---------------------------------------------------------------------------


class TestProjectTools:
    def test_list_projects_returns_list(self):
        from mcp_server.server import list_projects

        result = list_projects()
        assert isinstance(result, dict)
        assert "items" in result
        assert "count" in result
        if result["items"]:
            assert "project_id" in result["items"][0]
            assert "name" in result["items"][0]

    def test_get_current_project_returns_dict(self):
        from mcp_server.server import get_current_project

        result = get_current_project()
        assert isinstance(result, dict)
        assert "project_id" in result

    def test_set_current_project_valid(self):
        from mcp_server.server import set_current_project, list_projects

        projects = list_projects()
        if not projects["items"]:
            pytest.skip("No projects available")
        result = set_current_project(projects["items"][0]["project_id"])
        assert result["success"] is True

    def test_set_current_project_invalid(self):
        from mcp_server.server import set_current_project

        with pytest.raises(ValueError, match="Project not found"):
            set_current_project("nonexistent-00000000")


# ---------------------------------------------------------------------------
# Tool execution — content pipeline tools
# ---------------------------------------------------------------------------


class TestContentPipelineTools:
    def test_list_content_returns_dict(self):
        from mcp_server.server import list_content

        result = list_content(limit=5)
        assert isinstance(result, dict)
        assert "count" in result
        assert "items" in result

    def test_get_content_invalid_raises(self):
        from mcp_server.server import get_content

        with pytest.raises(ValueError, match="Content not found"):
            get_content("nonexistent-review-id")

    def test_decline_content_invalid_raises(self):
        from mcp_server.server import decline_content

        with pytest.raises(ValueError, match="Content not found"):
            decline_content("nonexistent-review-id")


class TestApproveContentPublishResolution:
    def _fake_transition(self):
        calls = []

        def _transition(review_id, action, **kwargs):
            calls.append((review_id, action, kwargs))
            if len(calls) == 1:
                return SimpleNamespace(status=SimpleNamespace(value="approved"), raw={})
            return SimpleNamespace(
                status=SimpleNamespace(value="scheduled"),
                raw={"published_via": "typefully", "draft_url": "https://example.test/draft", "draft_id": "d1"},
            )

        return calls, _transition

    def _patch_review_access(self, monkeypatch, server_module, project_id="mcp-test-project"):
        monkeypatch.setattr(
            server_module,
            "_check_review_access",
            lambda _review_id, _role, _tool: {
                "review_id": _review_id,
                "project_id": project_id,
                "post_data": {"project_id": project_id},
            },
        )

    def test_approve_content_honors_explicit_publish_true(self, monkeypatch):
        from data.review_models import ReviewAction
        from mcp_server import server as mcp_server

        self._patch_review_access(monkeypatch, mcp_server)
        calls, transition = self._fake_transition()
        monkeypatch.setattr(mcp_server.REVIEW_WORKFLOW, "transition", transition)

        result = mcp_server.approve_content("review-1", publish=True)

        assert result["success"] is True
        assert result["scheduling"]["scheduled"] is True
        assert [call[1] for call in calls] == [ReviewAction.APPROVE, ReviewAction.SCHEDULE]

    def test_approve_content_honors_explicit_publish_false(self, monkeypatch):
        from data.review_models import ReviewAction
        from mcp_server import server as mcp_server

        self._patch_review_access(monkeypatch, mcp_server)
        calls, transition = self._fake_transition()
        monkeypatch.setattr(mcp_server.REVIEW_WORKFLOW, "transition", transition)

        result = mcp_server.approve_content("review-2", publish=False)

        assert result["success"] is True
        assert result["scheduling"]["scheduled"] is False
        assert result["scheduling"]["skipped"] == "publish=false"
        assert [call[1] for call in calls] == [ReviewAction.APPROVE]

    def test_approve_content_omitted_publish_uses_auto_schedule_false(self, monkeypatch):
        from data.review_models import ReviewAction
        from mcp_server import server as mcp_server

        self._patch_review_access(monkeypatch, mcp_server, project_id="proj-auto-false")
        monkeypatch.setattr(
            mcp_server.PROJECT_MANAGER,
            "get_project_secrets",
            lambda _project_id: {"typefully": {"auto_schedule": False}},
        )
        calls, transition = self._fake_transition()
        monkeypatch.setattr(mcp_server.REVIEW_WORKFLOW, "transition", transition)

        result = mcp_server.approve_content("review-3")

        assert result["success"] is True
        assert result["scheduling"]["scheduled"] is False
        assert result["scheduling"]["skipped"] == "publish=false"
        assert [call[1] for call in calls] == [ReviewAction.APPROVE]

    def test_approve_content_omitted_publish_uses_auto_schedule_true(self, monkeypatch):
        from data.review_models import ReviewAction
        from mcp_server import server as mcp_server

        self._patch_review_access(monkeypatch, mcp_server, project_id="proj-auto-true")
        monkeypatch.setattr(
            mcp_server.PROJECT_MANAGER,
            "get_project_secrets",
            lambda _project_id: {"typefully": {"auto_schedule": True}},
        )
        calls, transition = self._fake_transition()
        monkeypatch.setattr(mcp_server.REVIEW_WORKFLOW, "transition", transition)

        result = mcp_server.approve_content("review-4")

        assert result["success"] is True
        assert result["scheduling"]["scheduled"] is True
        assert [call[1] for call in calls] == [ReviewAction.APPROVE, ReviewAction.SCHEDULE]


# ---------------------------------------------------------------------------
# Tool execution — source material tools
# ---------------------------------------------------------------------------


class TestSourceMaterialTools:
    def test_list_source_materials(self):
        from mcp_server.server import list_source_materials

        result = list_source_materials(limit=5)
        assert isinstance(result, dict)
        assert "count" in result
        assert "items" in result

    def test_get_source_material_invalid_raises(self):
        from mcp_server.server import get_source_material

        with pytest.raises(ValueError, match="Source material not found"):
            get_source_material("sm_nonexistent")

    def test_add_source_material_note(self):
        from mcp_server.server import add_source_material

        result = add_source_material(
            title="Test material from MCP test",
            note="This is a test material added by MCP tests",
            tags=["test"],
        )
        assert isinstance(result, dict)

        # Clean up
        if isinstance(result, dict) and result.get("material_id"):
            from mcp_server.server import delete_source_material

            delete_source_material(result["material_id"])


# ---------------------------------------------------------------------------
# Tool execution — content ideas tools
# ---------------------------------------------------------------------------


class TestContentIdeaTools:
    def test_list_content_ideas(self):
        from mcp_server.server import list_content_ideas

        result = list_content_ideas(limit=5)
        assert isinstance(result, dict)
        assert "count" in result

    def test_add_content_idea(self):
        from mcp_server.server import add_content_idea

        result = add_content_idea(
            title="Test idea from MCP test",
            hook="Test hook",
            platforms=["twitter"],
            content_pillar="test",
        )
        assert isinstance(result, dict)

        # Clean up
        idea_id = result.get("idea_id") if isinstance(result, dict) else None
        if idea_id:
            from mcp_server.server import delete_content_idea

            delete_content_idea(idea_id)

    def test_get_content_idea_invalid_raises(self):
        from mcp_server.server import get_content_idea

        with pytest.raises(ValueError, match="Content idea not found"):
            get_content_idea("ci_nonexistent")


# ---------------------------------------------------------------------------
# Tool execution — config tools
# ---------------------------------------------------------------------------


class TestConfigTools:
    def test_get_content_plan(self):
        from mcp_server.server import get_content_plan

        result = get_content_plan()
        assert "content_plan" in result

    def test_update_content_plan_uses_canonical_storage_and_mirrors_file(self):
        from mcp_server import server as mcp_server

        project_id = mcp_server.get_current_project()["project_id"]
        content = "# Canonical MCP Plan\n\nUpdated through MCP."

        result = mcp_server.update_content_plan(project_id=project_id, content=content)

        assert result == {"success": True, "project_id": project_id}
        assert mcp_server.PROJECT_MANAGER.get_content_plan(project_id) == content
        assert mcp_server.get_content_plan(project_id)["content_plan"] == content
        assert (
            mcp_server.DATA_DIR / "projects" / project_id / "content_plan.md"
        ).read_text() == content

    def test_get_brand_voice(self):
        from mcp_server.server import get_brand_voice

        result = get_brand_voice()
        assert "brand_voice" in result

    def test_get_project_settings(self):
        from mcp_server.server import get_project_settings

        result = get_project_settings()
        assert "settings" in result


# ---------------------------------------------------------------------------
# Tool execution — system tools
# ---------------------------------------------------------------------------


class TestSystemTools:
    def test_get_system_status(self):
        from mcp_server.server import get_system_status

        result = get_system_status()
        assert result["status"] == "ok"
        assert "project_count" in result
        assert "pipeline" in result
        assert "job_queue" in result

    def test_list_jobs(self):
        from mcp_server.server import list_jobs

        result = list_jobs()
        assert "count" in result
        assert "items" in result
