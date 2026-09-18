"""Characterization tests pinning project-loading behavior across all entry points.

These tests exercise the CURRENT project-loading behavior at every entry point
that constructs a ProjectManager (dashboard, CLI, MCP, scheduler, automated
generator). They MUST pass before AND after the v2 refactor (Phases 1-5). If
one fails after a code move, the refactor changed observable behavior.

Per AGENTS.md gotcha #1, the two ProjectManager implementations
(``projects.manager.ProjectManager`` and ``data.project_manager.ProjectManager``)
are characterized through their respective entry points without mixing them.
Per AGENTS.md gotcha #10, the fixture seeds a temporary SQLite DB (the source
of truth), not a JSON file.

This is a TEST file and may import both ProjectManager classes for
characterization purposes. Production code must NOT import
``data.project_manager`` directly -- that boundary is frozen by plan 00-02.
"""

import os
from pathlib import Path

from data.project_manager import ProjectManager as DataProjectManager
from projects.manager import ProjectManager as DashboardProjectManager
from tests.fixtures.project_factory import (
    FIXTURE_NAME,
    FIXTURE_PROJECT_ID,
    FIXTURE_SLUG,
)


class TestDashboardPathProjectLoading:
    """Characterizes projects.manager.ProjectManager (dashboard/CLI/MCP path)."""

    def test_dashboard_entry_point_loads_fixture_project(
        self, project_data_dir, fixture_project
    ):
        """dashboard/unified_dashboard.py:245 constructs ProjectManager(data_dir=...)."""
        manager = DashboardProjectManager(data_dir=str(project_data_dir))
        project = manager.get_project(fixture_project["project_id"])

        assert project is not None
        assert project.project_id == FIXTURE_PROJECT_ID
        assert project.name == FIXTURE_NAME
        assert project.slug == FIXTURE_SLUG
        assert project.config is not None
        assert "twitter" in project.config.platforms
        assert project.config.default_platform == "twitter"

    def test_dashboard_path_resolves_canonical_kv_fields(
        self, project_data_dir, fixture_project
    ):
        """projects/manager.py:464-540 KV readers resolve fixture values."""
        manager = DashboardProjectManager(data_dir=str(project_data_dir))
        pid = fixture_project["project_id"]

        assert manager.get_brand_voice(pid) == fixture_project["brand_voice_md"]
        assert manager.get_content_plan(pid) == fixture_project["content_plan_md"]
        assert manager.get_learning_patterns(pid) == fixture_project["learning_patterns"]
        assert manager.get_provider_mapping(pid) == fixture_project["provider_mapping"]

    def test_dashboard_path_resolves_current_project(
        self, project_data_dir, fixture_project
    ):
        """projects/manager.py:404 get_current_project resolves the fixture."""
        manager = DashboardProjectManager(data_dir=str(project_data_dir))
        project = manager.get_current_project()

        assert project is not None
        assert project.project_id == FIXTURE_PROJECT_ID


class TestCLIProjectLoading:
    """Characterizes cli.py:38-41 get_project_manager()."""

    def test_cli_get_project_manager_loads_fixture(
        self, project_data_dir, fixture_project, monkeypatch
    ):
        """cli.py:38-41 get_project_manager constructs ProjectManager via get_data_dir."""
        import cli

        monkeypatch.setattr(cli, "get_data_dir", lambda: project_data_dir)
        manager = cli.get_project_manager()
        project = manager.get_project(fixture_project["project_id"])

        assert project is not None
        assert project.name == FIXTURE_NAME
        assert project.slug == FIXTURE_SLUG


class TestMCPProjectLoading:
    """Characterizes mcp_server/server.py:59-61 DATA_DIR + ProjectManager."""

    def test_mcp_construction_pattern_loads_fixture(
        self, project_data_dir, fixture_project, monkeypatch
    ):
        """mcp_server/server.py:59-61 reads DRAPER_DATA_DIR and constructs ProjectManager."""
        monkeypatch.setenv("DRAPER_DATA_DIR", str(project_data_dir))
        data_dir = Path(os.environ["DRAPER_DATA_DIR"])

        manager = DashboardProjectManager(data_dir=str(data_dir))
        project = manager.get_project(fixture_project["project_id"])

        assert project is not None
        assert project.project_id == FIXTURE_PROJECT_ID
        assert project.name == FIXTURE_NAME


class TestDataPathProjectLoading:
    """Characterizes data.project_manager.ProjectManager (scheduler/generator path)."""

    def test_scheduler_entry_point_loads_fixture_project(
        self, project_data_dir, fixture_project
    ):
        """scheduler/content_scheduler.py:30 constructs data.project_manager.ProjectManager."""
        manager = DataProjectManager(data_dir=str(project_data_dir))
        project = manager.get_project(fixture_project["project_id"])

        assert project is not None
        assert project.project_id == FIXTURE_PROJECT_ID
        assert project.name == FIXTURE_NAME
        assert project.slug == FIXTURE_SLUG
        assert hasattr(project, "settings")
        assert hasattr(project, "generation_schedule")
        assert "twitter" in project.settings.platforms

    def test_scheduler_path_resolves_by_slug(self, project_data_dir, fixture_project):
        """data/project_manager.py:155 get_project_by_slug resolves the fixture."""
        manager = DataProjectManager(data_dir=str(project_data_dir))
        project = manager.get_project_by_slug(fixture_project["slug"])

        assert project is not None
        assert project.project_id == FIXTURE_PROJECT_ID

    def test_automated_generator_loads_brand_voice_and_plan(
        self, project_data_dir, fixture_project
    ):
        """generator/automated_content_generator.py:69-70 calls load_brand_voice/content_plan."""
        manager = DataProjectManager(data_dir=str(project_data_dir))
        pid = fixture_project["project_id"]

        assert manager.load_brand_voice(pid) == fixture_project["brand_voice_md"]
        assert manager.load_content_plan(pid) == fixture_project["content_plan_md"]

    def test_both_managers_see_the_same_project(self, project_data_dir, fixture_project):
        """Both ProjectManager implementations share the same SQLiteStore backing."""
        dashboard_manager = DashboardProjectManager(data_dir=str(project_data_dir))
        data_manager = DataProjectManager(data_dir=str(project_data_dir))

        dashboard_list = dashboard_manager.list_projects()
        data_list = data_manager.list_projects()

        assert len(dashboard_list) == 1
        assert len(data_list) == 1
        assert dashboard_list[0].project_id == FIXTURE_PROJECT_ID
        assert data_list[0].project_id == FIXTURE_PROJECT_ID
