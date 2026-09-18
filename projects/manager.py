#!/usr/bin/env python3
"""
Project Manager - Multi-project support with strict isolation.

Each project has:
- Unique ID and name
- Own Typefully API key (for scheduling to correct account)
- Content strategy/pillars
- Brand voice guidelines
- Isolated data storage

Safety: Content is tagged with project_id at generation time.
Scheduling verifies project_id matches before posting.

This module is a thin facade over ``services.project_service.ProjectService``
per ADR-0001. The canonical project shape is ``data.models.Project``; this
facade preserves the legacy ``projects.manager.Project`` return shape that
dashboard, CLI, and MCP callers depend on (per CONTEXT.md 'Facade Behavior').
The facade never writes to the store directly: every state-changing call
goes through ``self.service.*`` which goes through ``self.service.store.*``.
The only ``self.store`` reads happen inside ``_project_to_legacy`` for
projection back to the legacy shape.
"""

import warnings
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Dict, List, Optional

from services.project_service import ProjectService


@dataclass
class BrandVoice:
    """Comprehensive brand voice configuration.

    DEPRECATED per ADR-0001 'Negative Consequences': brand voice is now a
    markdown string accessed via ``ProjectService.get_brand_voice()``. This
    dataclass remains importable for legacy callers but is no longer
    populated by the facade.
    """
    personality: List[str] = field(default_factory=lambda: [
        "knowledgeable",
        "authentic",
        "technical but accessible"
    ])

    voice_attributes: Dict[str, Dict] = field(default_factory=dict)

    tone_by_channel: Dict[str, str] = field(default_factory=lambda: {
        "twitter": "punchy, direct, sometimes witty",
        "linkedin": "professional, thought-provoking, concise",
        "email": "personal, helpful, action-oriented",
        "blog": "informative, conversational, educational"
    })

    messaging_pillars: List[str] = field(default_factory=lambda: [
        "technical excellence",
        "radical transparency",
        "customer success"
    ])

    preferred_terms: Dict[str, str] = field(default_factory=dict)
    avoided_terms: List[str] = field(default_factory=list)

    style_rules: Dict[str, str] = field(default_factory=lambda: {
        "oxford_comma": "yes",
        "contractions": "use",
        "emoji_usage": "minimal",
        "exclamation_marks": "limited use"
    })


@dataclass
class ProjectConfig:
    """Project-specific configuration (legacy shape).

    The canonical project shape is ``data.models.ProjectSettings`` per
    ADR-0001. This dataclass remains importable for legacy callers; the
    facade projects canonical records back into this shape via
    ``_record_to_project_dict`` so dashboard/CLI/MCP callers reading
    ``project.config.platforms`` and ``project.config.default_platform``
    keep working.
    """
    twitter_social_set_id: Optional[str] = None
    linkedin_social_set_id: Optional[str] = None

    pillars: List[str] = field(default_factory=lambda: [
        "educational",
        "behind_the_scenes",
        "industry_insights"
    ])

    platforms: List[str] = field(default_factory=lambda: ["twitter", "linkedin"])
    default_platform: str = "twitter"

    tone: str = "professional"
    brand_keywords: List[str] = field(default_factory=list)
    brand_voice: Optional[BrandVoice] = None

    posts_per_batch: int = 5

    auto_schedule: bool = False
    schedule_times: List[str] = field(default_factory=lambda: ["09:00", "14:00", "18:00"])


@dataclass
class Project:
    """A project with isolated configuration and data (legacy shape)."""
    project_id: str
    name: str
    description: str = ""
    slug: str = ""
    config: ProjectConfig = field(default_factory=ProjectConfig)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "slug": self.slug,
            "config": asdict(self.config),
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Project":
        config_data = data.get("config", {})

        config_data.pop("typefully_api_key", None)

        brand_voice_data = config_data.pop("brand_voice", None)
        if brand_voice_data and isinstance(brand_voice_data, dict):
            brand_voice = BrandVoice(**brand_voice_data)
        else:
            brand_voice = None

        valid_fields = {
            k: v for k, v in config_data.items()
            if k in ProjectConfig.__dataclass_fields__
        }
        config = ProjectConfig(**valid_fields, brand_voice=brand_voice)

        return cls(
            project_id=data["project_id"],
            name=data["name"],
            description=data.get("description", ""),
            slug=data.get("slug", ""),
            config=config,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat())
        )

    def has_typefully_configured(self) -> bool:
        """Check if Typefully social sets are configured for this project."""
        return bool(self.config.twitter_social_set_id or self.config.linkedin_social_set_id)

    def get_social_set_id(self, platform: str) -> Optional[str]:
        """Get the Typefully social set ID for a platform."""
        if platform == "twitter":
            return self.config.twitter_social_set_id
        elif platform == "linkedin":
            return self.config.linkedin_social_set_id
        return None


class ProjectManager:
    """Facade over ``services.project_service.ProjectService`` per ADR-0001.

    Construction builds a ``ProjectService`` against ``data_dir`` and exposes
    ``self.store = self.service.store`` so existing callers
    (e.g. ``dashboard_instance.project_manager.store`` at
    ``unified_dashboard.py:246``) keep working. Every public method delegates
    to the service; methods that previously returned ``projects.manager.Project``
    project the canonical ``data.models.Project`` back into the legacy shape
    via ``_project_to_legacy`` so dashboard/CLI/MCP callers observing
    ``project.config.platforms`` / ``project.config.default_platform`` /
    ``project.has_typefully_configured()`` keep working unchanged.

    The facade never writes to the store directly. The only ``self.store``
    reads happen inside ``_project_to_legacy`` for projection.
    """

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            env_dir = os.environ.get("DRAPER_DATA_DIR")
            if env_dir:
                self.data_dir = Path(env_dir)
            else:
                self.data_dir = Path(__file__).parent.parent / "data"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_file = self.data_dir / "projects.json"
        if self.projects_file.exists():
            warnings.warn(
                "projects.json is deprecated; SQLiteStore is now the backing store.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.service = ProjectService(data_dir=str(self.data_dir))
        self.store = self.service.store

    def _record_to_project_dict(self, record: Dict) -> Dict:
        return {
            "project_id": record["project_id"],
            "name": record["name"],
            "description": record.get("description", ""),
            "slug": record.get("slug", ""),
            "config": record.get("config", {}),
            "created_at": record.get("created_at", datetime.now(timezone.utc).isoformat()),
        }

    def _project_to_legacy(self, canonical: Optional["Project"]) -> Optional[Project]:
        """Project a canonical ``data.models.Project`` back to legacy shape."""
        if canonical is None:
            return None
        record = self.store.get_project_record(canonical.project_id)
        if not record:
            return None
        return Project.from_dict(self._record_to_project_dict(record))

    def create_project(
        self,
        name: str,
        description: str = "",
        typefully_api_key: Optional[str] = None,
        **config_kwargs
    ) -> Project:
        """Create a new project via the canonical service and return legacy shape."""
        canonical = self.service.create_project(
            name=name,
            description=description,
            typefully_api_key=typefully_api_key,
            **config_kwargs
        )
        print(f"✅ Created project: {name} ({canonical.project_id})")
        return self._project_to_legacy(canonical)

    def get_project(self, project_id: str) -> Optional[Project]:
        """Get project by ID (legacy shape projected from canonical)."""
        return self._project_to_legacy(self.service.get_project(project_id))

    def get_project_by_name(self, name: str) -> Optional[Project]:
        """Get project by name (case-insensitive); returns legacy shape."""
        return self._project_to_legacy(self.service.get_project_by_name(name))

    def list_projects(self) -> List[Project]:
        """List all projects (legacy shape projected from canonical)."""
        return [
            self._project_to_legacy(canonical)
            for canonical in self.service.list_projects()
        ]

    def update_project(self, project_id: str, **updates) -> Optional[Project]:
        """Update project configuration via the canonical service."""
        return self._project_to_legacy(self.service.update_project(project_id, **updates))

    def delete_project(self, project_id: str, confirm: bool = False) -> bool:
        """Delete a project after explicit confirmation."""
        return self.service.delete_project(project_id, confirm=confirm)

    def set_current_project(self, project_id: str) -> bool:
        """Set the current active project."""
        return self.service.set_current_project(project_id)

    def get_current_project_id(self) -> Optional[str]:
        """Get current project ID."""
        return self.service.get_current_project_id()

    def get_current_project(self) -> Optional[Project]:
        """Get current active project (legacy shape projected from canonical)."""
        return self._project_to_legacy(self.service.get_current_project())

    def clear_current_project(self):
        """Clear current project selection."""
        return self.service.clear_current_project()

    def require_current_project(self) -> Project:
        """Get current project or raise an actionable ValueError."""
        canonical = self.service.require_current_project()
        return self._project_to_legacy(canonical)

    def get_project_data_dir(self, project_id: str) -> Path:
        """Return the per-project data directory, creating it if necessary."""
        return self.service.get_project_data_dir(project_id)

    def get_project_settings(self, project_id: str) -> Dict:
        """Get project settings via the canonical service."""
        return self.service.get_project_settings(project_id)

    def save_project_settings(self, project_id: str, settings: Dict) -> None:
        """Persist project settings via the canonical service."""
        return self.service.save_project_settings(project_id, settings)

    def get_project_secrets(self, project_id: str) -> Dict:
        """Get project secrets via the canonical service."""
        return self.service.get_project_secrets(project_id)

    def save_project_secrets(self, project_id: str, secrets_data: Dict) -> None:
        """Persist project secrets via the canonical service."""
        return self.service.save_project_secrets(project_id, secrets_data)

    def get_brand_voice(self, project_id: str) -> str:
        """Get brand voice markdown via the canonical service."""
        return self.service.get_brand_voice(project_id)

    def save_brand_voice(self, project_id: str, content: str) -> None:
        """Save brand voice markdown via the canonical service."""
        return self.service.save_brand_voice(project_id, content)

    def get_content_plan(self, project_id: str) -> str:
        """Get content plan markdown via the canonical service."""
        return self.service.get_content_plan(project_id)

    def save_content_plan(self, project_id: str, content: str) -> None:
        """Save content plan markdown via the canonical service."""
        return self.service.save_content_plan(project_id, content)

    def get_learning_patterns(self, project_id: str) -> Dict:
        """Get learning patterns via the canonical service."""
        return self.service.get_learning_patterns(project_id)

    def save_learning_patterns(self, project_id: str, patterns: Dict) -> None:
        """Save learning patterns via the canonical service."""
        return self.service.save_learning_patterns(project_id, patterns)

    def get_provider_mapping(self, project_id: str) -> Dict:
        """Return per-platform publishing provider routing via the canonical service."""
        return self.service.get_provider_mapping(project_id)

    def save_provider_mapping(self, project_id: str, mapping: Dict) -> None:
        """Save provider routing via the canonical service."""
        return self.service.save_provider_mapping(project_id, mapping)

    def verify_project_match(self, content_project_id: str, target_project_id: str) -> bool:
        """SAFETY: Verify content belongs to target project before scheduling.

        Delegates to the canonical service which raises ValueError with the
        ``SAFETY CHECK FAILED`` marker on any project_id mismatch. This
        prevents accidentally posting content to the wrong account.
        """
        return self.service.verify_project_match(content_project_id, target_project_id)


def get_project_context() -> Optional[Project]:
    """Helper to get current project context. Returns None if no project selected."""
    manager = ProjectManager()
    return manager.get_current_project()


def require_project_context() -> Project:
    """Helper to require project context. Raises error if no project is selected."""
    manager = ProjectManager()
    return manager.require_current_project()
