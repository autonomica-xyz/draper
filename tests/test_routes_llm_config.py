"""Quick task 260710-9qs Task 1: llm_config route regression contracts.

Mirrors the fixture/test pattern from ``tests/test_routes_integrations.py``:
AppContainer + build_app + TestClient, with LLM env keys + dashboard token
deleted and unauthenticated-local enabled.

Asserts the GET/POST/test/active routes return the documented envelopes and
that raw API keys never appear in response bodies (threat T-q-01).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient


@pytest.fixture
def container(project_data_dir: Any, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
    from dashboard.app_container import AppContainer

    return AppContainer(data_dir=str(project_data_dir))


@pytest.fixture
def app(container):
    from dashboard.app_factory import build_app

    return build_app(container)


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


EXPECTED_LLM_CONFIG_PATHS = {
    "/api/projects/{project_id}/llm-config",
    "/api/projects/{project_id}/llm-config/{provider}",
    "/api/projects/{project_id}/llm-config/{provider}/test",
    "/api/projects/{project_id}/llm-config/active",
}


class TestImportIsolation:
    def test_import_succeeds_without_dashboard_construction(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        start = time.monotonic()
        import importlib

        module = importlib.import_module("dashboard.routes.llm_config")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert hasattr(module, "router")
        assert isinstance(module.router, APIRouter)


class TestRouteRegistration:
    def test_router_registers_every_llm_config_path(self):
        from dashboard.routes import llm_config

        paths = {route.path for route in llm_config.router.routes}
        missing = EXPECTED_LLM_CONFIG_PATHS - paths
        assert not missing, f"Missing paths in llm_config.router: {sorted(missing)}"

    def test_iter_routers_yields_llm_config(self):
        from dashboard.routes import iter_routers, llm_config

        routers = list(iter_routers())
        assert llm_config.router in routers


class TestBehavioralEquivalence:
    def test_get_llm_config_returns_providers_and_active(self, container, client):
        created = container.project_manager.create_project(name="LLM Project")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.get(
            f"/api/projects/{project_id}/llm-config",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "providers" in body
        assert "active_provider" in body
        assert set(body["providers"].keys()) == {
            "zai",
            "deepseek",
            "minimax",
            "openrouter",
        }
        for name, block in body["providers"].items():
            assert "configured" in block
            assert "env_configured" in block
            assert "masked_api_key" in block
            assert "model" in block

    def test_post_save_provider_returns_success(self, container, client):
        created = container.project_manager.create_project(name="Save LLM")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/llm-config/zai",
            json={"api_key": "sk-zai-test-123456789", "model": "glm-4.7"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_post_save_unknown_provider_returns_failure(self, container, client):
        created = container.project_manager.create_project(name="Unknown LLM")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/llm-config/unknown",
            json={"api_key": "x", "model": "y"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "error" in body

    def test_post_active_sets_and_returns_success(self, container, client):
        created = container.project_manager.create_project(name="Active LLM")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/llm-config/active",
            json={"provider": "deepseek"},
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

        get_resp = client.get(
            f"/api/projects/{project_id}/llm-config",
            headers={"x-csrf-token": token},
        )
        assert get_resp.json()["active_provider"] == "deepseek"

    def test_post_test_without_key_returns_failure(self, container, client):
        created = container.project_manager.create_project(name="No LLM Key")
        project_id = created.project_id
        token = container.csrf.current_token()
        resp = client.post(
            f"/api/projects/{project_id}/llm-config/zai/test",
            headers={"x-csrf-token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "error" in body

    def test_raw_api_key_never_appears_in_get_response(self, container, client):
        created = container.project_manager.create_project(name="Mask LLM")
        project_id = created.project_id
        token = container.csrf.current_token()
        client.post(
            f"/api/projects/{project_id}/llm-config/zai",
            json={"api_key": "sk-SECRET-never-leak-9999", "model": "glm-4.7"},
            headers={"x-csrf-token": token},
        )
        get_resp = client.get(
            f"/api/projects/{project_id}/llm-config",
            headers={"x-csrf-token": token},
        )
        body_text = get_resp.text
        assert "sk-SECRET-never-leak-9999" not in body_text
        assert body_text.count("9999") <= 1


class TestSecretServiceExtensions:
    def test_env_keys_include_llm_providers(self):
        from services.secrets import ProjectSecretService

        assert ProjectSecretService.ENV_KEYS["zai"] == "ZAI_API_KEY"
        assert ProjectSecretService.ENV_KEYS["deepseek"] == "DEEPSEEK_API_KEY"
        assert ProjectSecretService.ENV_KEYS["minimax"] == "MINIMAX_API_KEY"
        assert ProjectSecretService.ENV_KEYS["openrouter"] == "OPENROUTER_API_KEY"

    def test_env_keys_still_include_existing_providers(self):
        from services.secrets import ProjectSecretService

        assert ProjectSecretService.ENV_KEYS["typefully"] == "TYPEFULLY_API_KEY"
        assert ProjectSecretService.ENV_KEYS["late"] == "LATE_API_KEY"
        assert ProjectSecretService.ENV_KEYS["nostr"] == "NOSTR_PRIVATE_KEY"

    def test_resolve_project_llm_returns_none_when_no_active(self, container):
        created = container.project_manager.create_project(name="No Active")
        assert container.secret_service.resolve_project_llm(created.project_id) is None

    def test_resolve_project_llm_returns_none_when_no_key(
        self, container, monkeypatch
    ):
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        created = container.project_manager.create_project(name="No Key")
        container.secret_service.set_active_llm_provider(
            created.project_id, "zai"
        )
        assert container.secret_service.resolve_project_llm(created.project_id) is None

    def test_resolve_project_llm_returns_params_when_configured(self, container):
        created = container.project_manager.create_project(name="Configured LLM")
        pid = created.project_id
        container.secret_service.update_provider_config(
            pid, "zai", {"api_key": "sk-test-key", "model": "glm-4.7"}
        )
        container.secret_service.set_active_llm_provider(pid, "zai")
        params = container.secret_service.resolve_project_llm(pid)
        assert params is not None
        assert params["model"] == "openai/glm-4.7"
        assert params["api_key"] == "sk-test-key"
        assert params["api_base"] == "https://api.zai.ai/v1"

    def test_resolve_project_llm_uses_env_fallback(self, container, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-fallback-key")
        created = container.project_manager.create_project(name="Env Fallback LLM")
        pid = created.project_id
        container.secret_service.set_active_llm_provider(pid, "deepseek")
        params = container.secret_service.resolve_project_llm(pid)
        assert params is not None
        assert params["api_key"] == "env-fallback-key"
        assert params["model"] == "deepseek/deepseek-chat"
