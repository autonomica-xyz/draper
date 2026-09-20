"""Non-Draper projects must not receive global draper_* strategy / hooks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from generator.llm_content_generator import LLMContentGenerator


@pytest.fixture(autouse=True)
def _stub_llm_keys(monkeypatch):
    """LLMContentGenerator.__init__ requires an API key even for prompt assembly."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")


DRAPER_FILENAMES = (
    "draper_twitter_strategy.md",
    "draper_linkedin_strategy.md",
    "draper_marketing_plan_enhanced.md",
)

DRAPER_HOOK_PHRASES = (
    "Everyone says AI agents are the future",
    "AI-powered autonomous agent platform",
    "We build autonomous AI agents that run businesses",
    "CONTEXT ABOUT DRAPER",
    "I almost shut down Draper",
    "Most companies don't need AI agents yet",
    "5 patterns that separate reliable AI agents from prototypes",
)


def _fake_project(*, project_id: str, name: str, slug: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        project_id=project_id,
        name=name,
        slug=slug or project_id.split("-")[0],
        config=SimpleNamespace(brand_voice=None),
    )


@pytest.fixture
def strategies_dir(tmp_path: Path) -> Path:
    """Create distinctive draper_* strategy files in a temp strategies root."""
    for name in DRAPER_FILENAMES:
        (tmp_path / name).write_text(
            f"# {name}\n\n"
            "Draper-only strategy marker: radical_transparency for AI agents.\n"
            "Distinctive phrase: draper-strategy-bleed-canary.\n"
        )
    # Project-local content plan for Acme
    acme_dir = tmp_path / "data" / "projects" / "acme-abc123"
    acme_dir.mkdir(parents=True)
    (acme_dir / "content_plan.md").write_text(
        "# Acme Content Plan\n\nFocus on privacy infrastructure and founder narrative.\n"
    )
    (acme_dir / "brand_voice.md").write_text(
        "# Acme Brand Voice\n\nPrecise, calm, security-first.\n"
    )
    return tmp_path


class TestDraperProjectDetection:
    def test_draper_slug_matches(self, strategies_dir: Path):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="draper-deadbeef", name="Draper", slug="draper"),
        )
        assert gen._is_draper_project() is True

    def test_acme_does_not_match(self, strategies_dir: Path):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="acme-abc123", name="Acme Labs", slug="acme"),
        )
        assert gen._is_draper_project() is False

    def test_founder_does_not_match(self, strategies_dir: Path):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="founder-xyz", name="Founder", slug="founder"),
        )
        assert gen._is_draper_project() is False

    def test_explicit_flag_overrides_slug(self, strategies_dir: Path):
        project = _fake_project(project_id="custom-1", name="Custom", slug="custom")
        project.use_draper_strategy = True
        gen = LLMContentGenerator(strategies_path=str(strategies_dir), project=project)
        assert gen._is_draper_project() is True

        project2 = _fake_project(project_id="draper-1", name="Draper", slug="draper")
        project2.use_draper_strategy = False
        gen2 = LLMContentGenerator(strategies_path=str(strategies_dir), project=project2)
        assert gen2._is_draper_project() is False


class TestStrategyFileLoading:
    def test_draper_loads_global_strategy_filenames(self, strategies_dir: Path):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="draper-deadbeef", name="Draper", slug="draper"),
        )
        for name in DRAPER_FILENAMES:
            assert name in gen._loaded_strategy_filenames
        assert "draper-strategy-bleed-canary" in gen.twitter_strategy

    def test_non_draper_does_not_load_draper_filenames(self, strategies_dir: Path):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="acme-abc123", name="Acme Labs", slug="acme"),
        )
        assert gen._loaded_strategy_filenames == []
        assert gen.twitter_strategy == ""
        assert gen.linkedin_strategy == ""
        assert gen.marketing_plan == ""

    def test_no_project_does_not_load_draper_filenames(self, strategies_dir: Path):
        gen = LLMContentGenerator(strategies_path=str(strategies_dir), project=None)
        assert gen._loaded_strategy_filenames == []


class TestNonDraperPromptAssembly:
    def test_twitter_prompt_excludes_draper_strategy_and_hooks(self, strategies_dir: Path, monkeypatch):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="acme-abc123", name="Acme Labs", slug="acme"),
        )
        # Avoid SQLite; content plan comes from legacy file path under strategies_dir
        monkeypatch.setattr(gen, "_get_brand_voice_context", lambda platform: "\nBRAND VOICE GUIDELINES:\nAcme\n")
        monkeypatch.setattr(gen, "_load_learning_patterns", lambda: {})

        prompt = gen._build_twitter_prompt("educational", "contrarian", "privacy")
        blob = prompt.lower()

        for name in DRAPER_FILENAMES:
            assert name not in prompt
        assert "draper-strategy-bleed-canary" not in prompt
        for phrase in DRAPER_HOOK_PHRASES:
            assert phrase.lower() not in blob
        assert "for draper" not in blob
        assert "acme" in blob or "brand voice" in blob

    def test_linkedin_prompt_excludes_draper_hooks(self, strategies_dir: Path, monkeypatch):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="acme-abc123", name="Acme Labs", slug="acme"),
        )
        monkeypatch.setattr(gen, "_get_brand_voice_context", lambda platform: "\nBRAND VOICE:\nAcme\n")
        monkeypatch.setattr(gen, "_load_learning_patterns", lambda: {})
        monkeypatch.setattr(gen, "_select_hook", lambda: "contrarian")

        prompt = gen._build_linkedin_prompt("educational", "story_post", "privacy")
        for phrase in DRAPER_HOOK_PHRASES:
            assert phrase not in prompt
        assert "for Draper" not in prompt

    def test_long_form_prompts_not_hardcoded_for_draper(self, strategies_dir: Path, monkeypatch):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="acme-abc123", name="Acme Labs", slug="acme"),
        )
        monkeypatch.setattr(gen, "_get_brand_voice_context", lambda platform: "VOICE")
        monkeypatch.setattr(gen, "_extract_strategy_context", lambda pillar, platform: "")
        monkeypatch.setattr(gen, "_get_cta_suggestions", lambda platform: ["Learn more", "Subscribe", "Reply"])

        email = gen._build_email_prompt("educational", "privacy")
        landing = gen._build_landing_page_prompt("educational", None)
        pr = gen._build_press_release_prompt("educational", "launch")
        case = gen._build_case_study_prompt("educational", "customer")

        for prompt in (email, landing, pr, case):
            assert "for Draper" not in prompt
            assert "Acme Labs" in prompt
            assert "AI-powered autonomous agent platform" not in prompt

        assert "AI agents/autonomous systems" not in landing

    def test_hook_examples_are_generic_for_non_draper(self, strategies_dir: Path):
        gen = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="acme-abc123", name="Acme Labs", slug="acme"),
        )
        examples = gen._get_hook_examples("contrarian")
        joined = " ".join(examples)
        assert "AI agents" not in joined
        assert "Everyone says AI agents are the future" not in joined

    def test_scoped_draper_generator_does_not_bleed_into_acme(self, strategies_dir: Path, monkeypatch):
        """Even if strategies were loaded for Draper, rebinding project must gate them."""
        draper = LLMContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="draper-deadbeef", name="Draper", slug="draper"),
        )
        assert draper._loaded_strategy_filenames  # loaded for draper

        from services.generator_scoping import scoped_generator_for_project

        acme = scoped_generator_for_project(
            draper,
            _fake_project(project_id="acme-abc123", name="Acme Labs", slug="acme"),
        )
        monkeypatch.setattr(acme, "_get_brand_voice_context", lambda platform: "VOICE")
        monkeypatch.setattr(acme, "_load_learning_patterns", lambda: {})

        prompt = acme._build_twitter_prompt("educational", "contrarian", "privacy")
        assert "draper-strategy-bleed-canary" not in prompt
        assert "Everyone says AI agents are the future" not in prompt
        assert "for Draper" not in prompt


class TestZaiGeneratorGating:
    def test_zai_non_draper_skips_draper_files_and_hooks(self, strategies_dir: Path, monkeypatch):
        from generator.zai_content_generator import ZAIContentGenerator

        monkeypatch.setenv("ZAI_API_KEY", "test-key-not-used")
        gen = ZAIContentGenerator(
            strategies_path=str(strategies_dir),
            project=_fake_project(project_id="acme-abc123", name="Acme Labs", slug="acme"),
        )
        assert gen._loaded_strategy_filenames == []
        monkeypatch.setattr(gen, "_load_learning_patterns", lambda: {})

        prompt = gen._build_twitter_prompt("educational", "contrarian", "privacy")
        assert "CONTEXT ABOUT DRAPER" not in prompt
        assert "We build autonomous AI agents that run businesses" not in prompt
        assert "draper-strategy-bleed-canary" not in prompt
        assert "Most companies don't need AI agents yet." not in prompt
        assert "Acme Labs" in prompt
