"""Quick task 260710-9qs Task 2: generator LLM override wiring contracts.

Asserts:
1. ``scoped_generator_for_project`` sets ``llm_override`` from the secret
   service when provided; leaves it unset/None when not (backward compat).
2. ``_call_llm`` uses the override branch (model + api_key + api_base, no
   fallbacks) when ``llm_override`` is set; uses the env path otherwise.
"""

from __future__ import annotations

from services.generator_scoping import scoped_generator_for_project


class _FakeProject:
    def __init__(self, project_id="fake-proj"):
        self.project_id = project_id


class _FakeGenerator:
    def __init__(self):
        self.project = None
        self.llm_override = None


class _StubSecretService:
    def __init__(self, resolved=None):
        self._resolved = resolved
        self.called_with = None

    def resolve_project_llm(self, project_id):
        self.called_with = project_id
        return self._resolved


class TestScopedGeneratorOverride:
    def test_sets_override_from_secret_service(self):
        gen = _FakeGenerator()
        project = _FakeProject("p1")
        params = {"model": "openai/glm-4.7", "api_key": "key", "api_base": "https://api.zai.ai/v1"}
        stub = _StubSecretService(resolved=params)
        scoped = scoped_generator_for_project(gen, project, secret_service=stub)
        assert scoped.llm_override == params
        assert stub.called_with == "p1"

    def test_override_is_none_when_secret_service_returns_none(self):
        gen = _FakeGenerator()
        project = _FakeProject("p2")
        stub = _StubSecretService(resolved=None)
        scoped = scoped_generator_for_project(gen, project, secret_service=stub)
        assert scoped.llm_override is None

    def test_no_secret_service_leaves_override_untouched(self):
        gen = _FakeGenerator()
        gen.llm_override = None
        project = _FakeProject("p3")
        scoped = scoped_generator_for_project(gen, project)
        assert scoped.llm_override is None
        assert scoped.project.project_id == "p3"

    def test_none_generator_returns_none(self):
        assert scoped_generator_for_project(None, _FakeProject(), secret_service=_StubSecretService()) is None

    def test_none_project_returns_generator(self):
        gen = _FakeGenerator()
        assert scoped_generator_for_project(gen, None, secret_service=_StubSecretService()) is gen


class TestCallLlmOverride:
    def test_override_branch_calls_completion_with_override_params(self, monkeypatch):
        import generator.llm_content_generator as mod

        captured = {}

        class _FakeResponse:
            class _Choice:
                class _Message:
                    content = "generated text"
                message = _Message()

            choices = [_Choice()]

            def model_dump(self):
                return {}

        def fake_completion(**kwargs):
            captured.update(kwargs)
            return _FakeResponse()

        monkeypatch.setattr(mod, "completion", fake_completion)

        gen = mod.LLMContentGenerator.__new__(mod.LLMContentGenerator)
        gen.llm_override = {
            "model": "openai/glm-4.7",
            "api_key": "sk-override",
            "api_base": "https://api.zai.ai/v1",
        }
        gen.total_tokens_used = 0
        gen.total_cost = 0.0
        gen.api_call_count = 0
        gen.project = None
        monkeypatch.setattr(gen, "_track_llm_cost", lambda resp: None)
        monkeypatch.setattr(gen, "_track_llm_error", lambda err: None)

        result = gen._call_llm("test prompt")
        assert result == "generated text"
        assert captured["model"] == "openai/glm-4.7"
        assert captured["api_key"] == "sk-override"
        assert captured["api_base"] == "https://api.zai.ai/v1"
        assert "fallbacks" not in captured

    def test_override_without_api_base_omits_it(self, monkeypatch):
        import generator.llm_content_generator as mod

        captured = {}

        class _FakeResponse:
            class _Choice:
                class _Message:
                    content = "deepseek text"
                message = _Message()

            choices = [_Choice()]

            def model_dump(self):
                return {}

        def fake_completion(**kwargs):
            captured.update(kwargs)
            return _FakeResponse()

        monkeypatch.setattr(mod, "completion", fake_completion)

        gen = mod.LLMContentGenerator.__new__(mod.LLMContentGenerator)
        gen.llm_override = {
            "model": "deepseek/deepseek-chat",
            "api_key": "sk-ds",
        }
        gen.total_tokens_used = 0
        gen.total_cost = 0.0
        gen.api_call_count = 0
        gen.project = None
        monkeypatch.setattr(gen, "_track_llm_cost", lambda resp: None)
        monkeypatch.setattr(gen, "_track_llm_error", lambda err: None)

        result = gen._call_llm("test prompt")
        assert result == "deepseek text"
        assert captured["model"] == "deepseek/deepseek-chat"
        assert "api_base" not in captured
        assert "fallbacks" not in captured

    def test_no_override_uses_env_model(self, monkeypatch):
        import generator.llm_content_generator as mod

        captured = {}

        class _FakeResponse:
            class _Choice:
                class _Message:
                    content = "env text"
                message = _Message()

            choices = [_Choice()]

            def model_dump(self):
                return {}

        def fake_completion(**kwargs):
            captured.update(kwargs)
            return _FakeResponse()

        monkeypatch.setattr(mod, "completion", fake_completion)
        monkeypatch.setenv("LLM_MODEL", "claude-3-5-sonnet-20241022")

        gen = mod.LLMContentGenerator.__new__(mod.LLMContentGenerator)
        gen.llm_override = None
        gen.total_tokens_used = 0
        gen.total_cost = 0.0
        gen.api_call_count = 0
        gen.project = None
        monkeypatch.setattr(gen, "_track_llm_cost", lambda resp: None)
        monkeypatch.setattr(gen, "_track_llm_error", lambda err: None)

        result = gen._call_llm("test prompt")
        assert result == "env text"
        assert captured["model"] == "claude-3-5-sonnet-20241022"
        assert captured.get("fallbacks") == ["gpt-4o", "gemini-2.0-flash-exp"]
