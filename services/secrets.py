"""Project-scoped secret access helpers.

This module centralizes the shape and masking of provider credentials. Callers
still use the existing ProjectManager storage, but route code no longer mutates
secret dictionaries inline.
"""

import os
from typing import Any, Dict, Iterable, Optional

from services.llm_provider_config import LLM_PROVIDERS, resolve_litellm_params
from services.observability import get_logger

_logger = get_logger(__name__)


class ProjectSecretService:
    """Read and update project-scoped provider secrets safely."""

    ENV_KEYS = {
        "typefully": "TYPEFULLY_API_KEY",
        "late": "LATE_API_KEY",
        "nostr": "NOSTR_PRIVATE_KEY",
        "zai": "ZAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }

    def __init__(self, project_manager):
        self.project_manager = project_manager

    def get_all(self, project_id: Optional[str]) -> Dict[str, Any]:
        if not project_id:
            return {}
        data = self.project_manager.get_project_secrets(project_id) or {}
        return data if isinstance(data, dict) else {}

    def get_provider_config(self, project_id: str, provider: str) -> Dict[str, Any]:
        config = self.get_all(project_id).get(provider, {})
        return dict(config) if isinstance(config, dict) else {}

    def get_api_key(self, project_id: Optional[str], provider: str, *, env_fallback: bool = True) -> str:
        key = ""
        if project_id:
            key = str(self.get_provider_config(project_id, provider).get("api_key") or "")
        if not key and env_fallback:
            env_key = self.ENV_KEYS.get(provider)
            key = os.getenv(env_key, "") if env_key else ""
        return key

    def is_configured(self, project_id: Optional[str], provider: str, *, env_fallback: bool = True) -> bool:
        return bool(self.get_api_key(project_id, provider, env_fallback=env_fallback))

    def update_provider_config(
        self,
        project_id: str,
        provider: str,
        updates: Dict[str, Any],
        *,
        allowed_keys: Optional[Iterable[str]] = None,
        ignore_blank_api_key: bool = True,
    ) -> Dict[str, Any]:
        secrets_data = self.get_all(project_id)
        provider_config = dict(secrets_data.get(provider, {}) or {})
        allowed = set(allowed_keys) if allowed_keys is not None else None

        for key, value in updates.items():
            if allowed is not None and key not in allowed:
                continue
            if key == "api_key" and ignore_blank_api_key and not value:
                continue
            provider_config[key] = value

        secrets_data[provider] = provider_config
        self.project_manager.save_project_secrets(project_id, secrets_data)
        return provider_config

    @staticmethod
    def masked_suffix(value: str, suffix_chars: int = 4) -> str:
        if not value:
            return ""
        return value[-suffix_chars:]

    def get_active_llm_provider(self, project_id: str) -> str:
        llm_config = self.get_provider_config(project_id, "llm")
        return str(llm_config.get("active_provider") or "")

    def set_active_llm_provider(self, project_id: str, provider: str) -> None:
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Unknown LLM provider: {provider}")
        self.update_provider_config(
            project_id,
            "llm",
            {"active_provider": provider},
            allowed_keys={"active_provider"},
        )

    def resolve_project_llm(self, project_id: str) -> Optional[Dict[str, str]]:
        active = self.get_active_llm_provider(project_id)
        if not active:
            return None
        api_key = self.get_api_key(project_id, active, env_fallback=True)
        if not api_key:
            return None
        model = self.get_provider_config(project_id, active).get("model") or None
        return resolve_litellm_params(active, model, api_key)
