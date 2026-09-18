#!/usr/bin/env python3
"""
Project management system for multi-project marketing pipeline.

DEPRECATED per ADR-0001: this module is a deprecation shim that emits a
``DeprecationWarning`` on construction and delegates every public method
to ``services.project_service.ProjectService`` (the canonical project
service). The canonical project shape is ``data.models.Project``.

No production code imports this shim: plan 01-03 migrated
``generator/automated_content_generator.py`` and ``mcp_server/server.py``
to compose ``ProjectService`` directly, and ``scheduler/content_scheduler.py``
was removed (it was unreachable once those consumers migrated).
``tests/test_import_boundaries.py`` enforces this with an empty ALLOW_LIST.
The shim is retained solely for external scripts and the Phase 0
characterization test suite that construct ``ProjectManager`` from here;
ADR-0001 governs its eventual removal.
"""

import warnings
from pathlib import Path
from typing import Dict, List, Optional

from data.models import Project
from services.project_service import ProjectService


class ProjectManager:
    """DEPRECATED: thin shim over ``services.project_service.ProjectService``.

    Construction emits a ``DeprecationWarning`` naming the canonical
    replacement (``services.project_service.ProjectService``) and ADR-0001.
    Every public method delegates to the canonical service and returns
    exactly what the service returns (``data.models.Project`` for
    project-returning methods; ``str`` for ``load_brand_voice`` /
    ``load_content_plan``; ``bool`` for ``delete_project``).

    The shim never writes to the store directly; all writes flow through
    ``self.service.store.*``. The ``projects.json`` legacy deprecation
    warning site is preserved so the Phase 0 / e2e validation contract
    (``pytest.warns(DeprecationWarning, match="projects.json is deprecated")``)
    keeps passing.
    """

    def __init__(self, data_dir: str = None):
        deprecation_msg = (
            "data.project_manager.ProjectManager is deprecated; use "
            "services.project_service.ProjectService instead (ADR-0001)."
        )
        warnings.warn(deprecation_msg, DeprecationWarning, stacklevel=2)
        if data_dir is None:
            data_dir = str(Path(__file__).resolve().parent)
        self.service = ProjectService(data_dir=data_dir)
        self.data_dir = self.service.data_dir
        self.store = self.service.store
        self.projects_file = self.data_dir / "projects.json"
        if self.projects_file.exists():
            legacy_msg = (
                "projects.json is deprecated; SQLiteStore is now the backing store."
            )
            warnings.warn(legacy_msg, DeprecationWarning, stacklevel=2)
        self.projects_base_dir = self.data_dir.parent / "projects"
        self.projects_base_dir.mkdir(parents=True, exist_ok=True)

    def create_project(
        self,
        name: str,
        slug: str,
        description: str = "",
        brand_voice_content: str = "",
        content_plan_content: str = "",
        platforms: Dict[str, dict] = None,
        generation_schedule: Dict[str, any] = None,
    ) -> Project:
        """Create a new project via the canonical service.

        Translates the legacy ``platforms: Dict[str, dict]`` shape to the
        canonical ``List[str]`` shape the service accepts, and remaps
        ``brand_voice_content`` / ``content_plan_content`` to the service's
        ``brand_voice_md`` / ``content_plan_md`` parameters.
        """
        platform_names: Optional[List[str]] = None
        if platforms:
            platform_names = list(platforms.keys())
        return self.service.create_project(
            name=name,
            slug=slug,
            description=description,
            platforms=platform_names,
            generation_schedule=generation_schedule,
            brand_voice_md=brand_voice_content,
            content_plan_md=content_plan_content,
        )

    def get_project(self, project_id: str) -> Optional[Project]:
        """Get project by ID via the canonical service."""
        return self.service.get_project(project_id)

    def get_project_by_slug(self, slug: str) -> Optional[Project]:
        """Get project by slug via the canonical service."""
        return self.service.get_project_by_slug(slug)

    def list_projects(self) -> List[Project]:
        """List all projects via the canonical service."""
        return self.service.list_projects()

    def update_project(self, project_id: str, **updates) -> Optional[Project]:
        """Update project fields via the canonical service."""
        return self.service.update_project(project_id, **updates)

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and its directory via the canonical service."""
        project = self.service.get_project(project_id)
        if not project:
            return False
        return self.service.delete_project(project_id, confirm=True)

    def load_brand_voice(self, project_id: str) -> str:
        """Load brand voice content via the canonical service."""
        return self.service.load_brand_voice(project_id)

    def load_content_plan(self, project_id: str) -> str:
        """Load content plan via the canonical service."""
        return self.service.load_content_plan(project_id)
