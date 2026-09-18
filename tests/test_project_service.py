"""Tests for services.project_service.ProjectService (the canonical service per ADR-0001).

These tests prove the canonical service round-trips the Phase 0 fixture
data and enforces the cross-project safety invariants the legacy managers
enforced. They reuse the shared pytest fixtures from tests/conftest.py
(``project_data_dir``, ``seeded_store``, ``fixture_project``) and exercise
the service only -- they never import either legacy ProjectManager.

The second half of this module (``TestDashboardFacadeDelegatesToService``
and ``TestDataShimEmitsDeprecationAndDelegates``) was added in plan 01-02
to pin the facade/shim delegation contract: the projects.manager.ProjectManager
facade must project canonical data.models.Project back into the legacy
shape (preserving project.config.platforms / default_platform), and the
data.project_manager.ProjectManager shim must emit DeprecationWarning
naming services.project_service.ProjectService and ADR-0001 on every
construction.

The final class (``TestPhaseOneConsumerMigration``) was added in plan 01-03
to pin the DOMN-02 closeout: zero production files import the legacy
``data.project_manager`` module, the automated generator and MCP server
construct ``ProjectService`` directly, the CLI composes the facade which
delegates to ``ProjectService``, and the Phase 0 characterization suite
still passes after the migration.
"""

import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from data.models import GenerationSchedule, Project, ProjectSettings
from data.models import Project as CanonicalProject
from data.project_manager import ProjectManager as DataProjectManager
from projects.manager import Project as LegacyProject
from projects.manager import ProjectManager as DashboardProjectManager
from services.project_service import ProjectService
from tests.fixtures.project_factory import (
    FIXTURE_NAME,
    FIXTURE_PROJECT_ID,
    FIXTURE_SLUG,
)


@pytest.fixture
def service(project_data_dir: Path) -> ProjectService:
    """Construct the canonical ProjectService against the fixture data_dir."""
    return ProjectService(data_dir=str(project_data_dir))


class TestProjectServiceCanonicalContract:
    """Pin every canonical behavior the facade/shim/scheduler/generator rely on."""

    def test_get_project_returns_canonical_shape(self, service, fixture_project):
        """ProjectService.get_project returns data.models.Project for the fixture."""
        project = service.get_project(fixture_project["project_id"])

        assert project is not None
        assert isinstance(project, Project)
        assert project.project_id == FIXTURE_PROJECT_ID
        assert project.name == FIXTURE_NAME
        assert project.slug == FIXTURE_SLUG
        assert isinstance(project.settings, ProjectSettings)
        assert isinstance(project.generation_schedule, GenerationSchedule)

    def test_get_project_by_slug_and_by_name_resolve_fixture(self, service, fixture_project):
        """Both slug and name resolvers return the fixture project."""
        by_slug = service.get_project_by_slug(fixture_project["slug"])
        by_name = service.get_project_by_name(fixture_project["name"])

        assert by_slug is not None and by_slug.project_id == FIXTURE_PROJECT_ID
        assert by_name is not None and by_name.project_id == FIXTURE_PROJECT_ID

    def test_get_project_by_slug_and_by_name_return_none_for_unknown(self, service):
        """Unknown slug and name resolve to None."""
        assert service.get_project_by_slug("does-not-exist") is None
        assert service.get_project_by_name("No Such Project") is None

    def test_list_projects_returns_fixture_only(self, service, fixture_project):
        """list_projects returns exactly one project matching FIXTURE_PROJECT_ID."""
        projects = service.list_projects()

        assert len(projects) == 1
        assert projects[0].project_id == FIXTURE_PROJECT_ID
        assert isinstance(projects[0], Project)

    def test_canonical_kv_readers_return_fixture_values(self, service, fixture_project):
        """get_brand_voice/content_plan/learning_patterns/provider_mapping/settings round-trip."""
        pid = fixture_project["project_id"]

        assert service.get_brand_voice(pid) == fixture_project["brand_voice_md"]
        assert service.get_content_plan(pid) == fixture_project["content_plan_md"]
        assert service.get_learning_patterns(pid) == fixture_project["learning_patterns"]
        assert service.get_provider_mapping(pid) == fixture_project["provider_mapping"]
        assert service.get_project_settings(pid) == fixture_project["settings"]

    def test_load_brand_voice_and_content_plan_match_get_accessors(self, service, fixture_project):
        """load_brand_voice and load_content_plan match get_brand_voice/get_content_plan."""
        pid = fixture_project["project_id"]

        assert service.load_brand_voice(pid) == service.get_brand_voice(pid)
        assert service.load_content_plan(pid) == service.get_content_plan(pid)

    def test_load_brand_voice_raises_for_unknown_project(self, service):
        """load_brand_voice and load_content_plan raise ValueError for unknown projects."""
        with pytest.raises(ValueError, match="not found"):
            service.load_brand_voice("nonexistent-project-id")
        with pytest.raises(ValueError, match="not found"):
            service.load_content_plan("nonexistent-project-id")

    def test_get_project_data_dir_creates_and_returns_path(self, service, fixture_project, project_data_dir):
        """get_project_data_dir returns an existing Path for a real project_id."""
        pid = fixture_project["project_id"]
        result = service.get_project_data_dir(pid)

        assert isinstance(result, Path)
        assert result.exists()
        assert result.is_dir()
        assert result == project_data_dir / "projects" / pid

    @pytest.mark.parametrize("bad_id", ["../../etc", "/x", "", "a/b", "a\\b"])
    def test_get_project_data_dir_rejects_path_traversal(self, service, bad_id):
        """get_project_data_dir rejects path-traversal substrings and empty ids."""
        with pytest.raises(ValueError, match="Invalid project_id"):
            service.get_project_data_dir(bad_id)

    def test_current_project_pointer_round_trips(self, service, fixture_project):
        """set/get/clear current-project pointer round-trips."""
        pid = fixture_project["project_id"]

        assert service.get_current_project_id() == pid
        assert service.get_current_project() is not None
        assert service.get_current_project().project_id == pid

        assert service.clear_current_project() is None
        assert service.get_current_project_id() is None
        assert service.get_current_project() is None

        assert service.set_current_project(pid) is True
        assert service.get_current_project_id() == pid

    def test_require_current_project_raises_when_unset(self, service, fixture_project):
        """require_current_project raises ValueError after clear_current_project."""
        service.clear_current_project()

        with pytest.raises(ValueError, match="No project selected"):
            service.require_current_project()

    def test_verify_project_match_passes_on_match(self, service, fixture_project):
        """verify_project_match returns True when ids agree."""
        pid = fixture_project["project_id"]

        assert service.verify_project_match(pid, pid) is True

    def test_verify_project_match_raises_on_mismatch(self, service, fixture_project):
        """verify_project_match raises ValueError with the SAFETY CHECK FAILED marker."""
        with pytest.raises(ValueError, match="SAFETY CHECK FAILED"):
            service.verify_project_match(FIXTURE_PROJECT_ID, "some-other-project-id")

    def test_create_project_seeds_six_kv_keys_and_returns_canonical_project(self, service):
        """create_project seeds all six KV keys and returns a canonical Project."""
        project = service.create_project(name="Smoke Proj")

        assert isinstance(project, Project)
        assert project.name == "Smoke Proj"
        assert isinstance(project.settings, ProjectSettings)
        assert isinstance(project.generation_schedule, GenerationSchedule)

        looked_up = service.get_project_by_name("Smoke Proj")
        assert looked_up is not None
        assert looked_up.project_id == project.project_id

        pid = project.project_id
        assert service.get_brand_voice(pid)
        assert service.get_content_plan(pid)
        assert service.get_learning_patterns(pid)
        assert service.get_project_settings(pid)
        assert service.get_project_secrets(pid)
        assert service.get_provider_mapping(pid)

    def test_create_project_rejects_duplicate_slug(self, service):
        """Regression (WR-04): create_project must enforce slug uniqueness. Two
        creates with the same explicit slug must raise ValueError rather than
        producing two records sharing a slug (which get_project_by_slug would
        silently resolve to only the most recent).
        """
        service.create_project(name="First", slug="dup-slug")

        with pytest.raises(ValueError, match=r"slug 'dup-slug' already exists"):
            service.create_project(name="Second", slug="dup-slug")

    def test_delete_project_requires_confirm(self, service, fixture_project):
        """delete_project raises without confirm=True and removes the record with it."""
        pid = fixture_project["project_id"]

        with pytest.raises(ValueError, match="confirm=True"):
            service.delete_project(pid)

        assert service.delete_project(pid, confirm=True) is True
        assert service.get_project(pid) is None
        assert service.delete_project(pid, confirm=True) is False

    def test_save_provider_mapping_mirrors_into_settings(self, service, fixture_project):
        """save_provider_mapping writes both KV and settings.provider_mapping (mirror behavior)."""
        pid = fixture_project["project_id"]
        new_mapping = {"twitter": "late", "linkedin": "typefully"}

        service.save_provider_mapping(pid, new_mapping)

        assert service.get_provider_mapping(pid) == new_mapping
        mirrored = service.get_project_settings(pid).get("provider_mapping")
        assert mirrored == new_mapping

    def test_update_project_legacy_platforms_list_does_not_corrupt_settings(
        self, service, fixture_project
    ):
        """Regression (CR-01): ``update_project(platforms=[...])`` -- the legacy
        list shape produced by ``draper project config --set platforms=...`` --
        must route to legacy ``config.platforms`` only and must NOT overwrite the
        canonical ``ProjectSettings.platforms`` dict. The next ``get_project``
        must not raise ``AttributeError: 'list' object has no attribute 'items'``.
        """
        pid = fixture_project["project_id"]

        updated = service.update_project(pid, platforms=["twitter", "linkedin"])
        assert updated is not None

        reloaded = service.get_project(pid)
        assert reloaded is not None
        assert isinstance(reloaded.settings.platforms, dict), (
            "ProjectSettings.platforms corrupted into a list by update_project"
        )
        assert "twitter" in reloaded.settings.platforms
        assert "linkedin" in reloaded.settings.platforms

    def test_update_project_keeps_record_and_kv_settings_consistent(
        self, service, fixture_project
    ):
        """Regression (CR-02): update_project must keep the record settings
        column and the KV settings slot consistent. KV is authoritative (the
        dashboard's save_project_settings writes there), so after a
        save_project_settings update followed by an unrelated update_project,
        both get_project (record-first) and get_project_settings (KV-first)
        must reflect the newer KV value -- update_project must not clobber it
        with a stale record value, nor leave the record pointing at the old one.
        """
        pid = fixture_project["project_id"]

        kv_settings = dict(fixture_project["settings"])
        kv_settings["platforms"] = {
            "mastodon": {
                "enabled": True,
                "account_handle": "@fixture",
                "public_key": "",
            }
        }
        service.save_project_settings(pid, kv_settings)

        service.update_project(pid, name="Renamed")

        record_settings = service.get_project(pid).settings.to_dict()
        kv_returned = service.get_project_settings(pid)

        assert "mastodon" in kv_returned["platforms"]
        assert "mastodon" in record_settings["platforms"], (
            "get_project returned stale record settings after update_project "
            "(record column not synced to KV-authoritative value)"
        )

    def test_update_project_persists_generation_schedule(
        self, service, fixture_project
    ):
        """Regression (WR-03): update_project(generation_schedule={...}) must
        route to the record's generation_schedule column so get_generation_schedule
        returns the new value. Previously it was dropped into config as a junk
        key and the record column was left unchanged.
        """
        pid = fixture_project["project_id"]
        new_schedule = {
            "frequency": "weekly",
            "times": ["07:00"],
            "posts_per_batch": 2,
        }

        service.update_project(pid, generation_schedule=new_schedule)

        schedule = service.get_generation_schedule(pid)
        assert schedule.frequency == "weekly"
        assert schedule.times == ["07:00"]
        assert schedule.posts_per_batch == 2

    def test_secrets_never_logged(self):
        """Static-source assertion: no method body logs or prints secret values.

        Reads services/project_service.py and verifies that any line
        mentioning 'secret' is part of a def, docstring, or a store
        get/set call -- never a print/logger call.
        """
        source = Path("services/project_service.py").read_text()
        offenders = []
        for line in source.splitlines():
            if "secret" not in line.lower():
                continue
            stripped = line.strip()
            is_signature_or_accessor = (
                stripped.startswith("def ")
                or stripped.startswith('"""')
                or stripped.startswith("#")
                or "self.store.get_project_value" in stripped
                or "self.store.set_project_value" in stripped
                or stripped.startswith("@")
            )
            has_log_call = "print(" in stripped or "logger." in stripped
            if has_log_call and not is_signature_or_accessor:
                offenders.append(line)
        assert offenders == [], f"Secret values may be logged: {offenders}"


class TestDashboardFacadeDelegatesToService:
    """Pin the projects.manager.ProjectManager facade delegation contract.

    Per plan 01-02 / ADR-0001 'Neutral' consequences: the facade must
    delegate every public method to ``ProjectService`` and project the
    canonical ``data.models.Project`` back into the legacy
    ``projects.manager.Project`` shape so dashboard/CLI/MCP callers
    reading ``project.config.platforms`` / ``project.config.default_platform``
    keep working.
    """

    def test_facade_get_project_returns_legacy_shape(
        self, project_data_dir, fixture_project
    ):
        """facade.get_project returns LegacyProject with config fields populated."""
        facade = DashboardProjectManager(data_dir=str(project_data_dir))
        project = facade.get_project(fixture_project["project_id"])

        assert isinstance(project, LegacyProject)
        assert project.project_id == FIXTURE_PROJECT_ID
        assert "twitter" in project.config.platforms
        assert project.config.default_platform == "twitter"

    def test_facade_get_current_project_returns_legacy_shape(
        self, project_data_dir, fixture_project
    ):
        """facade.get_current_project returns LegacyProject for the fixture."""
        facade = DashboardProjectManager(data_dir=str(project_data_dir))
        project = facade.get_current_project()

        assert isinstance(project, LegacyProject)
        assert project.project_id == FIXTURE_PROJECT_ID

    def test_facade_list_projects_returns_legacy_shape(
        self, project_data_dir, fixture_project
    ):
        """facade.list_projects returns a list of LegacyProject instances."""
        facade = DashboardProjectManager(data_dir=str(project_data_dir))
        projects = facade.list_projects()

        assert len(projects) == 1
        assert isinstance(projects[0], LegacyProject)
        assert projects[0].project_id == FIXTURE_PROJECT_ID

    def test_facade_kv_readers_delegate(
        self, project_data_dir, fixture_project
    ):
        """KV readers forward to ProjectService and return fixture values."""
        facade = DashboardProjectManager(data_dir=str(project_data_dir))
        pid = fixture_project["project_id"]

        assert facade.get_brand_voice(pid) == fixture_project["brand_voice_md"]
        assert facade.get_content_plan(pid) == fixture_project["content_plan_md"]
        assert facade.get_learning_patterns(pid) == fixture_project["learning_patterns"]
        assert facade.get_provider_mapping(pid) == fixture_project["provider_mapping"]
        assert facade.get_project_settings(pid) == fixture_project["settings"]

    def test_facade_store_passthrough(self, project_data_dir):
        """facade.store IS facade.service.store (unified_dashboard.py:246 access)."""
        facade = DashboardProjectManager(data_dir=str(project_data_dir))

        assert facade.store is facade.service.store

    def test_facade_verify_project_match_preserves_safety_message(
        self, project_data_dir
    ):
        """verify_project_match raises ValueError with the SAFETY CHECK FAILED marker."""
        facade = DashboardProjectManager(data_dir=str(project_data_dir))

        with pytest.raises(ValueError, match="SAFETY CHECK FAILED"):
            facade.verify_project_match("a", "b")

    def test_facade_get_project_data_dir_rejects_traversal(
        self, project_data_dir
    ):
        """get_project_data_dir rejects path-traversal substrings."""
        facade = DashboardProjectManager(data_dir=str(project_data_dir))

        with pytest.raises(ValueError, match="Invalid project_id"):
            facade.get_project_data_dir("../../etc")


class TestDataShimEmitsDeprecationAndDelegates:
    """Pin the data.project_manager.ProjectManager shim contract.

    Per plan 01-02 / ADR-0001 'Neutral' consequences: the shim must emit
    DeprecationWarning on construction naming the canonical replacement
    (services.project_service.ProjectService) and ADR-0001, then delegate
    every public method to ProjectService. Project-returning methods
    return the canonical data.models.Project directly (no projection).
    """

    def test_shim_construction_emits_deprecation_warning(
        self, project_data_dir
    ):
        """Constructing the shim emits DeprecationWarning naming ProjectService + ADR-0001."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DataProjectManager(data_dir=str(project_data_dir))

            assert any(issubclass(x.category, DeprecationWarning) for x in w)
            messages = [
                str(x.message)
                for x in w
                if issubclass(x.category, DeprecationWarning)
                and "services.project_service.ProjectService" in str(x.message)
                and "ADR-0001" in str(x.message)
            ]
            assert messages, (
                "DeprecationWarning must mention both "
                "services.project_service.ProjectService and ADR-0001"
            )

    def test_shim_get_project_returns_canonical_shape(
        self, project_data_dir, fixture_project
    ):
        """shim.get_project returns CanonicalProject with .settings.platforms and .generation_schedule."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            shim = DataProjectManager(data_dir=str(project_data_dir))

        project = shim.get_project(fixture_project["project_id"])

        assert isinstance(project, CanonicalProject)
        assert project.project_id == FIXTURE_PROJECT_ID
        assert "twitter" in project.settings.platforms
        assert project.generation_schedule is not None

    def test_shim_load_brand_voice_and_load_content_plan_delegate(
        self, project_data_dir, fixture_project
    ):
        """load_brand_voice / load_content_plan forward to the service and return fixture markdown."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            shim = DataProjectManager(data_dir=str(project_data_dir))

        pid = fixture_project["project_id"]

        assert shim.load_brand_voice(pid) == fixture_project["brand_voice_md"]
        assert shim.load_content_plan(pid) == fixture_project["content_plan_md"]

    def test_shim_get_project_by_slug_resolves_fixture(
        self, project_data_dir, fixture_project
    ):
        """shim.get_project_by_slug resolves the fixture by slug."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            shim = DataProjectManager(data_dir=str(project_data_dir))

        project = shim.get_project_by_slug(fixture_project["slug"])

        assert project is not None
        assert project.project_id == FIXTURE_PROJECT_ID

    def test_shim_store_passthrough(self, project_data_dir):
        """shim.store IS shim.service.store (back-compat with manager.store readers)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            shim = DataProjectManager(data_dir=str(project_data_dir))

        assert shim.store is shim.service.store


class TestPhaseOneConsumerMigration:
    """Pin the DOMN-02 closeout: every legacy consumer is on the services/ layer.

    Plan 01-03 migrated generator/automated_content_generator.py and
    mcp_server/server.py to construct services.project_service.ProjectService
    directly, removed scheduler/content_scheduler.py (dormant per the audit),
    and confirmed cli.py reads project data through the facade which
    delegates to ProjectService (Option B per CONTEXT.md). After plan 01-03
    no production file imports data.project_manager -- this class pins
    that invariant with an in-process boundary scan plus regression
    coverage for the construction patterns.
    """

    REPO_ROOT = Path(__file__).resolve().parent.parent
    EXCLUDE_DIRS = frozenset(
        {
            ".venv",
            ".git",
            "__pycache__",
            ".planning",
            "tests",
            "node_modules",
            ".mypy_cache",
            ".ruff_cache",
            ".eggs",
            "build",
            "dist",
        }
    )
    FORBIDDEN_IMPORT_RE = re.compile(
        r"^[ \t]*(?:"
        r"from data\.project_manager import|"
        r"import data\.project_manager|"
        r"from data import project_manager"
        r")",
        re.MULTILINE,
    )

    def test_no_production_code_imports_legacy_data_project_manager(self):
        """DOMN-02 success criterion #2: zero production files import data.project_manager."""
        violators = []
        for absolute_path in self.REPO_ROOT.rglob("*.py"):
            relative_path = absolute_path.relative_to(self.REPO_ROOT)
            if any(part in self.EXCLUDE_DIRS for part in relative_path.parts):
                continue
            text = absolute_path.read_text(encoding="utf-8")
            if self.FORBIDDEN_IMPORT_RE.search(text):
                violators.append(relative_path.as_posix())

        if violators:
            pytest.fail(
                "Production code imports the legacy data.project_manager "
                "module (DOMN-02 regression):\n"
                + "\n".join(f"  - {path}" for path in sorted(violators))
            )

    def test_automated_generator_constructs_project_service(
        self, project_data_dir, fixture_project, monkeypatch
    ):
        """generator/automated_content_generator.py composes ProjectService directly."""
        from generator.automated_content_generator import AutomatedContentGenerator

        base_dir = str(project_data_dir.parent)
        generator = AutomatedContentGenerator(base_dir=base_dir)

        assert isinstance(generator.project_service, ProjectService)
        assert generator.project_manager is generator.project_service

    def test_automated_generator_loads_learning_patterns_via_service(
        self, project_data_dir, fixture_project
    ):
        """Regression (WR-02): AutomatedContentGenerator._load_learning_patterns
        must read patterns from ProjectService (KV-first with file fallback)
        rather than deriving the path from ``content_plan_path`` (which is ""
        by default, causing a CWD lookup that never finds the file). The fixture
        seeds learning_patterns into the KV store, so the generator must return
        them.
        """
        from generator.automated_content_generator import AutomatedContentGenerator

        generator = AutomatedContentGenerator(base_dir=str(project_data_dir.parent))
        generator.project_service = ProjectService(data_dir=str(project_data_dir))
        generator.project_manager = generator.project_service

        loaded = generator._load_learning_patterns(fixture_project["project_id"])

        assert loaded == fixture_project["learning_patterns"]

    def test_cli_get_project_manager_returns_facade_delegating_to_service(
        self, project_data_dir, fixture_project, monkeypatch
    ):
        """cli.py:get_project_manager returns the facade delegating to ProjectService (Option B)."""
        import cli

        monkeypatch.setattr(cli, "get_data_dir", lambda: project_data_dir)
        manager = cli.get_project_manager()

        assert isinstance(manager, DashboardProjectManager)
        assert isinstance(manager.service, ProjectService)

    def test_phase_zero_characterization_suite_still_passes_regression(self):
        """Re-run the Phase 0 characterization suite in-process; assert exit 0."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_project_loading_characterization.py",
            ],
            cwd=str(self.REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "Phase 0 characterization suite regressed:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
