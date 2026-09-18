"""LLM provider registry and LiteLLM parameter resolution.

Single source of truth for the four per-project LLM providers (z.ai,
deepseek, minimax, openrouter) routed through LiteLLM. ``resolve_litellm_params``
builds the completion kwargs (model string + api_base) shared by the generator
override path and the dashboard test-connection route.

Per decision D3: default models are z.ai=glm-4.7, deepseek=deepseek-chat,
minimax=MiniMax-Text-01, openrouter=auto.
"""

from __future__ import annotations

from typing import Dict, Optional


LLM_PROVIDERS: Dict[str, Dict[str, Optional[str]]] = {
    "zai": {
        "env_key": "ZAI_API_KEY",
        "default_model": "glm-4.7",
        "litellm_prefix": "openai/",
        "api_base": "https://api.zai.ai/v1",
    },
    "deepseek": {
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "litellm_prefix": "deepseek/",
        "api_base": None,
    },
    "minimax": {
        "env_key": "MINIMAX_API_KEY",
        "default_model": "MiniMax-Text-01",
        "litellm_prefix": "minimax/",
        "api_base": None,
    },
    "openrouter": {
        "env_key": "OPENROUTER_API_KEY",
        "default_model": "auto",
        "litellm_prefix": "openrouter/",
        "api_base": None,
    },
}


def resolve_litellm_params(
    provider: str, model: Optional[str], api_key: str
) -> Dict[str, str]:
    """Build the LiteLLM completion kwargs for a provider.

    Args:
        provider: One of the keys in ``LLM_PROVIDERS``.
        model: Optional model override; falls back to the provider default.
        api_key: The API key to pass through.

    Returns:
        A dict with ``model`` (litellm_prefix + model) and ``api_key``;
        includes ``api_base`` only when the registry entry defines one.

    Raises:
        ValueError: If ``provider`` is not in ``LLM_PROVIDERS``.
    """
    entry = LLM_PROVIDERS.get(provider)
    if entry is None:
        raise ValueError(f"Unknown LLM provider: {provider}")
    resolved_model = entry["litellm_prefix"] + (model or entry["default_model"])
    params: Dict[str, str] = {"model": resolved_model, "api_key": api_key}
    if entry.get("api_base"):
        params["api_base"] = entry["api_base"]
    return params
