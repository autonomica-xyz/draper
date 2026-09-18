"""LLM provider configuration routes for the Settings AI sub-tab.

Mirrors the ``dashboard/routes/integrations.py`` pattern: module-level
``APIRouter()``, ``Depends(get_secret_service)`` for the secret service,
JSON envelopes, and ``masked_suffix`` for keys (threat T-q-01: raw API keys
are never echoed back in response bodies).

All four providers (z.ai, deepseek, minimax, openrouter) route through
LiteLLM; the test-connection route imports litellm lazily (same lazy-import
discipline as the typefully test route importing TypefullySyncClient).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Request

from dashboard.dependencies import get_secret_service
from services.llm_provider_config import LLM_PROVIDERS, resolve_litellm_params

router = APIRouter()


@router.get("/api/projects/{project_id}/llm-config")
async def get_llm_config(
    project_id: str,
    request: Request,
    secret_service: Any = Depends(get_secret_service),
):
    providers: dict[str, Any] = {}
    for name, entry in LLM_PROVIDERS.items():
        config = secret_service.get_provider_config(project_id, name)
        per_project_key = str(config.get("api_key") or "")
        env_key = ""
        env_var = entry.get("env_key")
        if env_var:
            env_key = os.getenv(env_var, "")
        providers[name] = {
            "configured": bool(per_project_key or env_key),
            "env_configured": bool(env_key),
            "masked_api_key": secret_service.masked_suffix(per_project_key)
            if per_project_key
            else "",
            "model": config.get("model") or entry["default_model"],
        }
    return {
        "providers": providers,
        "active_provider": secret_service.get_active_llm_provider(project_id),
    }


@router.post("/api/projects/{project_id}/llm-config/active")
async def set_active_llm_provider(
    project_id: str,
    request: Request,
    secret_service: Any = Depends(get_secret_service),
):
    data = await request.json()
    provider = data.get("provider", "")
    if provider not in LLM_PROVIDERS:
        return {"success": False, "error": "Unknown provider"}
    secret_service.set_active_llm_provider(project_id, provider)
    return {"success": True}


@router.post("/api/projects/{project_id}/llm-config/{provider}")
async def save_llm_provider_config(
    project_id: str,
    provider: str,
    request: Request,
    secret_service: Any = Depends(get_secret_service),
):
    if provider not in LLM_PROVIDERS:
        return {"success": False, "error": "Unknown provider"}
    data = await request.json()
    secret_service.update_provider_config(
        project_id,
        provider,
        data,
        allowed_keys={"api_key", "model"},
    )
    return {"success": True}


@router.post("/api/projects/{project_id}/llm-config/{provider}/test")
async def test_llm_provider_connection(
    project_id: str,
    provider: str,
    secret_service: Any = Depends(get_secret_service),
):
    if provider not in LLM_PROVIDERS:
        return {"success": False, "error": "Unknown provider"}
    api_key = secret_service.get_api_key(project_id, provider)
    if not api_key:
        return {"success": False, "error": "No API key configured"}
    config = secret_service.get_provider_config(project_id, provider)
    model = config.get("model") or None
    params = resolve_litellm_params(provider, model, api_key)
    try:
        import litellm

        litellm.completion(
            **params,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
            num_retries=1,
        )
        return {"success": True, "message": "Connected"}
    except Exception as e:
        print(f"LLM provider {provider} connection test failed for {project_id}: {e}")
        label = provider.replace("_", " ").title()
        return {"success": False, "error": f"{label} connection failed"}
