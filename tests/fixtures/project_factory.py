"""Reusable fixture project factory for characterization and integration tests.

This module is intentionally pytest-free: it does not import the pytest
package, so it can be imported by ``conftest`` fixtures and by future Phase 1+
tests without side effects.

The factory seeds ONE canonical project into a provided ``SQLiteStore`` and
returns a dict of the expected values that assertions compare against.
"""

from __future__ import annotations

from typing import Any, Dict

from data.sqlite_store import SQLiteStore


FIXTURE_PROJECT_ID = "fixture-proj-001"
FIXTURE_SLUG = "fixture-project"
FIXTURE_NAME = "Fixture Project"


def make_fixture_project(
    store: SQLiteStore, project_id: str = FIXTURE_PROJECT_ID
) -> Dict[str, Any]:
    """Seed one canonical project into ``store`` and return expected values.

    Idempotent for the same ``project_id``: ``save_project_record`` upserts
    (``replace=True`` is the default), and each ``set_project_value`` call
    uses the project_kv primary key. Safe to call from multiple fixtures
    that share the same store.
    """
    provider_mapping = {"twitter": "typefully", "linkedin": "typefully"}

    settings = {
        "brand_voice_path": "",
        "content_plan_path": "",
        "platforms": {
            "twitter": {
                "enabled": True,
                "account_handle": "@fixture",
                "public_key": "",
            },
            "linkedin": {
                "enabled": True,
                "account_handle": "@fixture",
                "public_key": "",
            },
            "nostr": {"enabled": False, "account_handle": "", "public_key": ""},
        },
        "posting_strategy": {
            "frequency": "daily",
            "posts_per_day": 3,
            "times": ["09:00", "14:00"],
            "platforms": ["twitter", "linkedin"],
        },
        "provider_mapping": provider_mapping,
    }

    config = {
        "twitter_social_set_id": "tw-set-fixture",
        "linkedin_social_set_id": "li-set-fixture",
        "pillars": ["educational", "industry_insights"],
        "platforms": ["twitter", "linkedin"],
        "default_platform": "twitter",
        "tone": "professional",
        "posts_per_batch": 3,
        "schedule_times": ["09:00", "14:00"],
    }

    generation_schedule = {
        "frequency": "daily",
        "times": ["09:00", "14:00"],
        "posts_per_batch": 3,
    }

    brand_voice_md = (
        "# Fixture Brand Voice\n\nProfessional, technical but accessible tone.\n"
    )
    content_plan_md = "# Fixture Content Plan\n\nWeekly themes and pillars.\n"

    learning_patterns = {
        "patterns": {
            "pat-001": {
                "pattern_type": "hook_style",
                "pattern": "question-led",
                "effectiveness_score": 0.7,
                "confidence": "medium",
            }
        }
    }

    secrets = {
        "typefully": {
            "api_key": "fixture-fake-key-NOT-REAL",
            "drafts_enabled": True,
            "auto_schedule": False,
        }
    }

    store.save_project_record(
        {
            "project_id": project_id,
            "name": FIXTURE_NAME,
            "slug": FIXTURE_SLUG,
            "description": "Characterization fixture project",
            "config": config,
            "settings": settings,
            "generation_schedule": generation_schedule,
            "created_at": "2026-07-04T00:00:00+00:00",
        }
    )

    store.set_project_value(project_id, "brand_voice", brand_voice_md)
    store.set_project_value(project_id, "content_plan", content_plan_md)
    store.set_project_value(project_id, "learning_patterns", learning_patterns)
    store.set_project_value(project_id, "secrets", secrets)
    store.set_project_value(project_id, "provider_mapping", provider_mapping)
    store.set_project_value(project_id, "settings", settings)
    store.set_current_project_id(project_id)

    return {
        "project_id": project_id,
        "name": FIXTURE_NAME,
        "slug": FIXTURE_SLUG,
        "description": "Characterization fixture project",
        "brand_voice_md": brand_voice_md,
        "content_plan_md": content_plan_md,
        "learning_patterns": learning_patterns,
        "secrets": secrets,
        "provider_mapping": provider_mapping,
        "config": config,
        "settings": settings,
        "generation_schedule": generation_schedule,
    }
