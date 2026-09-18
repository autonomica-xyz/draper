"""Quick task 260710-9qs Task 1: LLM provider registry contracts.

Asserts the shape of ``resolve_litellm_params`` and the ``LLM_PROVIDERS``
registry for all four providers (z.ai, deepseek, minimax, openrouter) per
decision D3 (default models) and D2 (per-project keys with env fallback).
"""

from __future__ import annotations

import pytest

from services.llm_provider_config import LLM_PROVIDERS, resolve_litellm_params


class TestLLMProvidersRegistry:
    def test_registry_keys_are_exactly_the_four_providers(self):
        assert set(LLM_PROVIDERS.keys()) == {"zai", "deepseek", "minimax", "openrouter"}

    def test_zai_default_model_is_glm_4_7(self):
        assert LLM_PROVIDERS["zai"]["default_model"] == "glm-4.7"

    def test_deepseek_default_model_is_deepseek_chat(self):
        assert LLM_PROVIDERS["deepseek"]["default_model"] == "deepseek-chat"

    def test_minimax_default_model_is_minimax_text_01(self):
        assert LLM_PROVIDERS["minimax"]["default_model"] == "MiniMax-Text-01"

    def test_openrouter_default_model_is_auto(self):
        assert LLM_PROVIDERS["openrouter"]["default_model"] == "auto"

    def test_zai_uses_openai_prefix_and_api_base(self):
        assert LLM_PROVIDERS["zai"]["litellm_prefix"] == "openai/"
        assert LLM_PROVIDERS["zai"]["api_base"] == "https://api.zai.ai/v1"

    def test_zai_env_key(self):
        assert LLM_PROVIDERS["zai"]["env_key"] == "ZAI_API_KEY"

    def test_deepseek_env_key_and_no_api_base(self):
        assert LLM_PROVIDERS["deepseek"]["env_key"] == "DEEPSEEK_API_KEY"
        assert LLM_PROVIDERS["deepseek"]["api_base"] is None

    def test_minimax_env_key_and_no_api_base(self):
        assert LLM_PROVIDERS["minimax"]["env_key"] == "MINIMAX_API_KEY"
        assert LLM_PROVIDERS["minimax"]["api_base"] is None

    def test_openrouter_env_key_and_no_api_base(self):
        assert LLM_PROVIDERS["openrouter"]["env_key"] == "OPENROUTER_API_KEY"
        assert LLM_PROVIDERS["openrouter"]["api_base"] is None


class TestResolveLitellmParams:
    def test_zai_with_explicit_model(self):
        params = resolve_litellm_params("zai", "glm-4.7", "key")
        assert params == {
            "model": "openai/glm-4.7",
            "api_key": "key",
            "api_base": "https://api.zai.ai/v1",
        }

    def test_deepseek_with_none_model_uses_default(self):
        params = resolve_litellm_params("deepseek", None, "key")
        assert params == {
            "model": "deepseek/deepseek-chat",
            "api_key": "key",
        }
        assert "api_base" not in params

    def test_minimax_with_explicit_model(self):
        params = resolve_litellm_params("minimax", "MiniMax-Text-01", "key")
        assert params == {
            "model": "minimax/MiniMax-Text-01",
            "api_key": "key",
        }
        assert "api_base" not in params

    def test_openrouter_with_auto_model(self):
        params = resolve_litellm_params("openrouter", "auto", "key")
        assert params == {
            "model": "openrouter/auto",
            "api_key": "key",
        }
        assert "api_base" not in params

    def test_zai_with_none_model_uses_default(self):
        params = resolve_litellm_params("zai", None, "key")
        assert params["model"] == "openai/glm-4.7"
        assert params["api_base"] == "https://api.zai.ai/v1"

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError):
            resolve_litellm_params("unknown", "model", "key")
