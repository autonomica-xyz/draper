"""Canonical project service per ADR-0001.

This service owns the project domain surface that every entry point (CLI,
dashboard, MCP server, scheduler, automated generator) composes in the v2
refactor. It returns ``data.models.Project`` -- the canonical project shape
selected by ADR-0001 -- and holds a ``SQLiteStore`` reference directly.
Repository extraction is deferred to Phase 5; until then the service delegates
persistence to the existing store methods.

Brand voice and content plan are markdown strings accessed via the KV-backed
accessors (per ADR-0001 'Negative Consequences'). Secrets flow only through
``get_project_secrets`` / ``save_project_secrets`` and are never logged.

The service is purely additive in plan 01-01: no entry point is modified.
Plans 01-02 and 01-03 wire the legacy facade/shim, scheduler, automated
generator, and CLI to delegate to this service.
"""

import json as _json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from data.models import GenerationSchedule, Project
from data.sqlite_store import SQLiteStore, slugify
from services.observability import get_logger


_SETTINGS_LEAK_PATTERN = re.compile(r"secret|token|password", re.IGNORECASE)

_logger = get_logger(__name__)


class ProjectService:
    """Canonical project service backing all v2 entry points.

    Construction accepts the same ``data_dir`` argument the legacy
    ``DashboardProjectManager`` and ``DataProjectManager`` accepted, so the
    service opens the same ``marketing_pipeline.sqlite3`` database the
    fixtures and existing managers share. ``self.store`` is exposed as a
    public attribute so the facade in plan 01-02 can reuse the same store
    reference (preserving the ``dashboard_instance.project_manager.store``
    access pattern at unified_dashboard.py:246).
    """

    def __init__(self, data_dir):
        """Construct the service against ``data_dir`` (str or Path).

        Two services built with the same ``data_dir`` open the same SQLite
        database file.
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(self.data_dir)

    def _project_from_record(self, record: Optional[Dict[str, Any]]) -> Optional[Project]:
        """Project a persisted store record into the canonical dataclass."""
        if not record:
            return None
        project_id = record["project_id"]
        settings = record.get("settings") or self.store.get_project_value(
            project_id, "settings", {}
        )
        return Project.from_dict(
            {
                "project_id": project_id,
                "name": record.get("name", ""),
                "slug": record.get("slug", ""),
                "description": record.get("description", ""),
                "created_at": record.get("created_at", ""),
                "settings": settings or {},
                "generation_schedule": record.get("generation_schedule", {}),
            }
        )

    def get_project(self, project_id: str) -> Optional[Project]:
        """Return the canonical Project for ``project_id`` or None if unknown."""
        return self._project_from_record(self.store.get_project_record(project_id))

    def get_project_by_slug(self, slug: str) -> Optional[Project]:
        """Resolve a project by slug; return None if no project matches."""
        return self._project_from_record(self.store.get_project_record_by_slug(slug))

    def get_project_by_name(self, name: str) -> Optional[Project]:
        """Resolve a project by name (case-insensitive); return None if unknown."""
        return self._project_from_record(self.store.get_project_record_by_name(name))

    def list_projects(self) -> List[Project]:
        """Return every non-deleted project as the canonical dataclass."""
        return [
            self._project_from_record(record)
            for record in self.store.list_project_records()
        ]

    def create_project(
        self,
        name: str,
        slug: Optional[str] = None,
        description: str = "",
        typefully_api_key: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        generation_schedule: Optional[Dict[str, Any]] = None,
        brand_voice_md: Optional[str] = None,
        content_plan_md: Optional[str] = None,
    ) -> Project:
        """Persist a new project, seed all six canonical KV keys, and return it.

        Mirrors the seeding pattern at ``projects/manager.py:244-315`` while
        emitting the richer ``data.models.Project`` shape selected by
        ADR-0001. The default provider mapping routes each enabled platform
        to Typefully -- the historical default publishing provider -- so
        every seeded KV slot is non-empty after construction.
        """
        slug = slug or slugify(name)
        for record in self.store.list_project_records():
            if record.get("name", "").lower() == name.lower():
                raise ValueError(f"Project with name '{name}' already exists")
            if record.get("slug") == slug:
                raise ValueError(f"Project with slug '{slug}' already exists")

        project_id = f"{slug}-{secrets.token_hex(4)}"
        platform_names = list(platforms or ["twitter", "linkedin"])

        provider_mapping = {platform: "typefully" for platform in platform_names}
        settings_data = {
            "brand_voice_path": "",
            "content_plan_path": "",
            "platforms": {
                platform: {
                    "enabled": True,
                    "account_handle": "",
                    "public_key": "",
                }
                for platform in platform_names
            },
            "social_profiles": [],
            "posting_strategy": {
                "frequency": "daily",
                "posts_per_day": 5,
                "times": ["09:00", "14:00", "18:00"],
                "platforms": platform_names,
            },
            "provider_mapping": provider_mapping,
        }
        schedule_data = generation_schedule or {
            "frequency": "daily",
            "times": ["09:00", "14:00"],
            "posts_per_batch": 5,
        }
        secrets_data = {
            "typefully": {
                "api_key": typefully_api_key or "",
                "drafts_enabled": True,
                "auto_schedule": False,
            }
        }
        config_data = {
            "platforms": platform_names,
            "default_platform": platform_names[0] if platform_names else "twitter",
            "posts_per_batch": schedule_data.get("posts_per_batch", 5),
            "schedule_times": schedule_data.get(
                "times", ["09:00", "14:00", "18:00"]
            ),
        }
        brand_voice = brand_voice_md or (
            f"# {name} Brand Voice\n\nAdd your brand voice guidelines here.\n"
        )
        content_plan = content_plan_md or (
            f"# {name} Content Plan\n\nAdd your content strategy here.\n"
        )
        learning_patterns: Dict[str, Any] = {"patterns": {}}

        self.store.save_project_record(
            {
                "project_id": project_id,
                "name": name,
                "slug": slug,
                "description": description,
                "config": config_data,
                "settings": settings_data,
                "generation_schedule": schedule_data,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.store.set_project_value(project_id, "settings", settings_data)
        self.store.set_project_value(project_id, "secrets", secrets_data)
        self.store.set_project_value(project_id, "brand_voice", brand_voice)
        self.store.set_project_value(project_id, "content_plan", content_plan)
        self.store.set_project_value(project_id, "learning_patterns", learning_patterns)
        self.store.set_project_value(project_id, "provider_mapping", provider_mapping)

        project_data_dir = self.data_dir / "projects" / project_id
        project_data_dir.mkdir(parents=True, exist_ok=True)

        return self.get_project(project_id)

    def update_project(self, project_id: str, **updates) -> Optional[Project]:
        """Merge ``updates`` into the persisted record and return the project."""
        record = self.store.get_project_record(project_id)
        if not record:
            return None

        merged = dict(record)
        for key in ("name", "description", "slug", "generation_schedule"):
            if key in updates:
                merged[key] = updates.pop(key)

        # Remaining kwargs are legacy config keys (e.g. platforms as List[str],
        # pillars, tone, schedule_times from `draper project config --set`).
        # Route them to config only; preserve the canonical dict-shaped
        # settings verbatim so a list-shaped `platforms` cannot corrupt
        # ProjectSettings.platforms (Dict[str, PlatformConfig]).
        config = dict(merged.get("config") or {})
        # KV is the authoritative settings source: the dashboard writes settings
        # via save_project_settings (KV-only). Source from the KV-first reader so
        # a record-only write can never clobber a newer KV value, then mirror the
        # same value to both the record column and KV so they never diverge.
        settings = dict(self.get_project_settings(project_id) or {})
        if updates:
            config.update(updates)
        merged["config"] = config
        merged["settings"] = settings

        self.store.save_project_record(
            {
                "project_id": merged["project_id"],
                "name": merged.get("name", ""),
                "slug": merged.get("slug", ""),
                "description": merged.get("description", ""),
                "config": config,
                "settings": settings,
                "generation_schedule": merged.get("generation_schedule", {}),
                "created_at": merged.get("created_at", datetime.now(timezone.utc).isoformat()),
            }
        )
        self.store.set_project_value(project_id, "settings", settings)
        return self.get_project(project_id)

    def delete_project(self, project_id: str, confirm: bool = False) -> bool:
        """Delete a project after explicit confirmation.

        Mirrors ``projects.manager.ProjectManager.delete_project`` lines
        363-389: requires ``confirm=True``, soft-deletes the record (which
        also clears the current-project pointer when it matched), removes
        the per-project data directory, and returns ``True`` on success.
        """
        if not confirm:
            raise ValueError("Must pass confirm=True to delete a project")

        deleted = self.store.delete_project_record(project_id)
        if not deleted:
            return False

        project_data_dir = self.data_dir / "projects" / project_id
        if project_data_dir.exists():
            shutil.rmtree(project_data_dir)

        if self.get_current_project_id() == project_id:
            self.clear_current_project()

        return True

    def set_current_project(self, project_id: str) -> bool:
        """Set the current project pointer; return False if the project is unknown."""
        if not self.store.get_project_record(project_id):
            return False
        self.store.set_current_project_id(project_id)
        return True

    def get_current_project_id(self) -> Optional[str]:
        """Return the current-project id or None when unset."""
        return self.store.get_current_project_id()

    def get_current_project(self) -> Optional[Project]:
        """Return the current project as the canonical dataclass or None."""
        project_id = self.get_current_project_id()
        if not project_id:
            return None
        return self.get_project(project_id)

    def clear_current_project(self) -> None:
        """Clear the current-project pointer."""
        self.store.clear_current_project()

    def require_current_project(self) -> Project:
        """Return the current project or raise an actionable ValueError."""
        project = self.get_current_project()
        if not project:
            raise ValueError(
                "No project selected. Use 'draper project switch <name>' to select one, "
                "or 'draper project add <name>' to create one."
            )
        return project

    def get_project_data_dir(self, project_id: str) -> Path:
        """Return the per-project data directory, creating it if necessary.

        Rejects path-traversal substrings (``/``, ``\\``, ``..``) and empty
        ids with ``ValueError("Invalid project_id")`` -- the cross-project
        safety invariant from ``projects/manager.py:429-437``.
        """
        if not project_id or any(part in project_id for part in ("/", "\\", "..")):
            raise ValueError("Invalid project_id")
        path = self.data_dir / "projects" / project_id
        if not self.store.get_project_record(project_id) and not path.exists():
            raise ValueError(f"Unknown project_id: {project_id}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_project_settings(self, project_id: str) -> Dict[str, Any]:
        """Return settings from KV, falling back to the record-level settings slot."""
        settings = self.store.get_project_value(project_id, "settings", {})
        if settings:
            return settings

        record = self.store.get_project_record(project_id)
        if record and record.get("settings"):
            self.store.set_project_value(project_id, "settings", record["settings"])
            return record["settings"]

        return {}

    def save_project_settings(self, project_id: str, settings: Dict[str, Any]) -> None:
        """Persist project settings to KV."""
        existing = self.get_project_settings(project_id) or {}
        changed_keys = sorted(
            {k for k in set(settings.keys()) | set(existing.keys())
             if settings.get(k) != existing.get(k)
             and not _SETTINGS_LEAK_PATTERN.search(k)}
        )
        self.store.set_project_value(project_id, "settings", settings)
        try:
            self.store.record_event(
                category="settings",
                action="updated",
                project_id=project_id,
                payload={"keys": changed_keys},
            )
        except Exception as exc:
            _logger.warning("system_events.settings.updated failed: %s", exc)

    def get_provider_mapping(self, project_id: str) -> Dict[str, str]:
        """Return per-platform provider routing, falling back to settings."""
        mapping = self.store.get_project_value(project_id, "provider_mapping", {})
        if mapping:
            return mapping

        settings = self.get_project_settings(project_id)
        mapping = settings.get("provider_mapping", {})
        if mapping:
            self.store.set_project_value(project_id, "provider_mapping", mapping)
        return mapping

    def save_provider_mapping(self, project_id: str, mapping: Dict[str, str]) -> None:
        """Persist provider routing in KV and mirror it into settings."""
        self.store.set_project_value(project_id, "provider_mapping", mapping)
        settings = self.get_project_settings(project_id)
        settings["provider_mapping"] = mapping
        self.save_project_settings(project_id, settings)

    def get_project_secrets(self, project_id: str) -> Dict[str, Any]:
        """Return the project's secrets descriptor from KV."""
        return self.store.get_project_value(project_id, "secrets", {})

    def save_project_secrets(self, project_id: str, secrets_data: Dict[str, Any]) -> None:
        """Persist the project's secrets descriptor to KV."""
        self.store.set_project_value(project_id, "secrets", secrets_data)
        providers = sorted(
            k for k in (secrets_data.keys() if isinstance(secrets_data, dict) else [])
        )
        try:
            self.store.record_event(
                category="credential",
                action="rotated",
                project_id=project_id,
                payload={"providers": providers},
            )
        except Exception as exc:
            _logger.warning("system_events.credential.rotated failed: %s", exc)

    def get_brand_voice(self, project_id: str) -> str:
        """Return brand-voice markdown from KV with legacy-file fallback."""
        md = self.store.get_project_value(project_id, "brand_voice", "")
        if md:
            return md

        settings = self.get_project_settings(project_id)
        path = settings.get("brand_voice_path", "")
        if path and Path(path).exists():
            md = Path(path).read_text()
            self.store.set_project_value(project_id, "brand_voice", md)
            return md
        return ""

    def save_brand_voice(self, project_id: str, content: str) -> None:
        """Persist brand-voice markdown to KV."""
        self.store.set_project_value(project_id, "brand_voice", content)

    def get_content_plan(self, project_id: str) -> str:
        """Return content-plan markdown from KV with legacy-file fallback."""
        md = self.store.get_project_value(project_id, "content_plan", "")
        if md:
            return md

        settings = self.get_project_settings(project_id)
        path = settings.get("content_plan_path", "")
        if path and Path(path).exists():
            md = Path(path).read_text()
            self.store.set_project_value(project_id, "content_plan", md)
            return md
        return ""

    def save_content_plan(self, project_id: str, content: str) -> None:
        """Persist content-plan markdown to KV."""
        self.store.set_project_value(project_id, "content_plan", content)

    def load_brand_voice(self, project_id: str) -> str:
        """Return brand-voice markdown; raise ValueError for unknown projects.

        Preserves the ``data.project_manager.ProjectManager.load_brand_voice``
        contract relied on by the automated generator (plan 01-03).
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        return self.get_brand_voice(project_id)

    def load_content_plan(self, project_id: str) -> str:
        """Return content-plan markdown; raise ValueError for unknown projects.

        Preserves the ``data.project_manager.ProjectManager.load_content_plan``
        contract relied on by the automated generator (plan 01-03).
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        return self.get_content_plan(project_id)

    def get_learning_patterns(self, project_id: str) -> Dict[str, Any]:
        """Return learning patterns from KV with legacy-file fallback."""
        patterns = self.store.get_project_value(project_id, "learning_patterns", {})
        if patterns:
            return patterns

        try:
            data_dir = self.get_project_data_dir(project_id)
        except ValueError:
            return {}
        patterns_file = data_dir / "learning_patterns.json"
        if patterns_file.exists():
            try:
                patterns = _json.loads(patterns_file.read_text())
                self.store.set_project_value(project_id, "learning_patterns", patterns)
                return patterns
            except Exception:
                pass
        return {}

    def save_learning_patterns(self, project_id: str, patterns: Dict[str, Any]) -> None:
        """Persist learning patterns to KV."""
        self.store.set_project_value(project_id, "learning_patterns", patterns)

    def get_generation_schedule(self, project_id: str) -> GenerationSchedule:
        """Return the parsed generation schedule or a default schedule when unset."""
        record = self.store.get_project_record(project_id)
        if not record:
            return GenerationSchedule()
        schedule_dict = record.get("generation_schedule") or {}
        if not schedule_dict:
            return GenerationSchedule()
        return GenerationSchedule.from_dict(schedule_dict)

    def verify_project_match(
        self, content_project_id: Optional[str], target_project_id: Optional[str]
    ) -> bool:
        """Raise ValueError if the content and target project ids disagree.

        Cross-project-posting safety invariant from
        ``projects/manager.py:541-553`` -- never weaken the message or the
        condition. The ``SAFETY CHECK FAILED`` marker is pinned by tests so
        it cannot regress silently.
        """
        if not content_project_id or content_project_id != target_project_id:
            raise ValueError(
                f"⚠️  SAFETY CHECK FAILED: Content belongs to project '{content_project_id}' "
                f"but trying to schedule to project '{target_project_id}'. "
                f"This would post to the wrong account!"
            )
        return True
