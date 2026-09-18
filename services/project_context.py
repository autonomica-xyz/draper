"""Project-scoped helpers shared by dashboard and API workflows."""

from typing import Dict, List, Optional


class ProjectContextService:
    """Centralizes project identity, provider mapping, and account lookup."""

    def __init__(self, project_manager):
        self.project_manager = project_manager

    def list_projects(self) -> List:
        return self.project_manager.list_projects()

    def get_current_project(self, project_id: str = None):
        if project_id:
            return self.project_manager.get_project(project_id)
        return self.project_manager.get_current_project()

    def resolve_record_project_id(self, record: Dict) -> Optional[str]:
        """Resolve and normalize the project ID on a review record."""
        post_data = record.setdefault("post_data", {})
        project_id = record.get("project_id") or post_data.get("project_id")
        if project_id:
            record["project_id"] = project_id
            post_data["project_id"] = project_id
        return project_id

    def require_record_project_id(self, record: Dict) -> str:
        """Return a verified project ID, failing closed if missing or mismatched."""
        project_id = self.resolve_record_project_id(record)
        if not project_id:
            raise ValueError("Review is missing project_id; regenerate or assign it before publishing")
        self.project_manager.verify_project_match(
            record.get("post_data", {}).get("project_id"),
            project_id,
        )
        return project_id

    def get_social_profiles(self, project_id: str) -> List[Dict]:
        settings = self.project_manager.get_project_settings(project_id)
        return settings.get("social_profiles", [])

    def get_provider_mapping(self, project_id: str) -> Dict[str, str]:
        return self.project_manager.get_provider_mapping(project_id)

    def get_provider_for_platform(self, project_id: str, platform: str) -> Optional[str]:
        return self.get_provider_mapping(project_id).get(platform)

    def infer_provider_for_platform(self, project_id: str, platform: str) -> Optional[str]:
        """Infer provider from enabled social profiles when no explicit mapping exists."""
        for profile in self.get_social_profiles(project_id):
            if profile.get("platform") != platform or not profile.get("enabled"):
                continue
            if profile.get("provider"):
                return profile["provider"]
            account_id = str(profile.get("account_id", ""))
            if account_id.startswith("late_"):
                return "late"
            if account_id.startswith("typefully_"):
                return "typefully"
            if account_id:
                return "typefully"
        return None

    def normalize_account_id(self, raw_id: str, platform: str, provider_name: str = None) -> str:
        """Normalize stored social profile IDs for the selected provider."""
        if not raw_id:
            return ""
        if raw_id.startswith(("typefully_", "late_")):
            return raw_id
        if provider_name == "late":
            return f"late_{raw_id}"
        return f"typefully_{raw_id}_{platform}"

    def find_enabled_account_id(
        self,
        project_id: str,
        platform: str,
        provider_name: str = None,
    ) -> Optional[str]:
        """Find the enabled project account for a platform/provider pair."""
        for profile in self.get_social_profiles(project_id):
            if profile.get("platform") != platform or not profile.get("enabled"):
                continue
            if provider_name and profile.get("provider") and profile.get("provider") != provider_name:
                continue
            raw_account_id = str(profile.get("account_id", ""))
            if provider_name == "late" and raw_account_id.startswith("typefully_"):
                continue
            if provider_name == "typefully" and raw_account_id.startswith("late_"):
                continue
            return self.normalize_account_id(raw_account_id, platform, provider_name)

        # No enabled social profile matched: fall back to the legacy project
        # config social set IDs (Typefully only) so older projects that only
        # set twitter_social_set_id / linkedin_social_set_id still publish.
        if provider_name in (None, "typefully"):
            set_id = self._project_config_social_set_id(project_id, platform)
            if set_id:
                return self.normalize_account_id(str(set_id), platform, "typefully")
        return None

    def _project_config_social_set_id(self, project_id: str, platform: str) -> Optional[str]:
        """Return the legacy twitter/linkedin social set ID from project config."""
        if platform not in ("twitter", "linkedin"):
            return None
        project = self.project_manager.get_project(project_id)
        config = getattr(project, "config", None)
        if config is None:
            return None
        field = "twitter_social_set_id" if platform == "twitter" else "linkedin_social_set_id"
        value = getattr(config, field, None)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
        return None


# Ensure schedule failures stay Pipeline-visible (MCP + dashboard).
try:
    from services.schedule_fail_visibility import apply as _apply_schedule_fail_visibility
    _apply_schedule_fail_visibility()
except Exception:
    pass
