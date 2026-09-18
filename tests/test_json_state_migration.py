"""Plan 05-03 Task 1: SQLite-first analytics reader contract.

Asserts that every analytics reader (TypefullyAnalytics, AnalyticsOptimizer,
UnifiedAnalytics, dashboard.analytics_runtime) prefers the SQLite
analytics_snapshots table over the legacy JSON file. The JSON file remains
as a deprecated fallback that emits a DeprecationWarning when fired.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

from data.atomic_io import atomic_write_json
from data.sqlite_store import SQLiteStore


def _seed_metrics_file(data_dir: Path, payload: dict) -> Path:
    path = data_dir / "typefully_metrics.json"
    atomic_write_json(path, payload)
    return path


def _seed_snapshot(store: SQLiteStore, source_path: str, payload: Any) -> None:
    store.save_analytics_snapshot(source_path, payload)


class TestSQLitePrimaryRead:
    def test_typefully_analytics_prefers_sqlite_snapshot_over_file(
        self, project_data_dir: Path
    ):
        from analytics.typefully_analytics import _read_analytics

        store = SQLiteStore(data_dir=str(project_data_dir))
        file_payload = {"post_a": {"post_id": "post_a"}}
        snapshot_payload = {"post_b": {"post_id": "post_b"}}
        _seed_metrics_file(project_data_dir, file_payload)
        _seed_snapshot(store, "typefully_metrics.json", snapshot_payload)

        result = _read_analytics(
            store,
            project_data_dir / "typefully_metrics.json",
            default={},
        )

        assert result == snapshot_payload
        assert "post_b" in result
        assert "post_a" not in result

    def test_analytics_optimizer_helper_prefers_sqlite_snapshot(
        self, project_data_dir: Path
    ):
        from analytics.analytics_optimizer import _read_analytics

        store = SQLiteStore(data_dir=str(project_data_dir))
        file_payload = {"old": True}
        snapshot_payload = {"new": True}
        _seed_metrics_file(project_data_dir, file_payload)
        _seed_snapshot(store, "typefully_metrics.json", snapshot_payload)

        result = _read_analytics(
            store,
            project_data_dir / "typefully_metrics.json",
            default={},
        )

        assert result == snapshot_payload


class TestJSONFallbackWarns:
    def test_typefully_reader_emits_deprecation_warning_on_file_fallback(
        self, project_data_dir: Path
    ):
        from analytics.typefully_analytics import _read_analytics

        store = SQLiteStore(data_dir=str(project_data_dir))
        file_payload = {"post_a": {"post_id": "post_a"}}
        _seed_metrics_file(project_data_dir, file_payload)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _read_analytics(
                store,
                project_data_dir / "typefully_metrics.json",
                default={},
            )

        assert result == file_payload
        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecation_warnings, "Expected DeprecationWarning on JSON fallback"
        message = str(deprecation_warnings[0].message)
        import re

        assert re.search(r"reads from .+\.json", message), (
            f"DeprecationWarning message must match 'reads from .+\\.json': {message!r}"
        )


class TestNoDataReturnsDefault:
    def test_typefully_reader_returns_default_when_neither_source_has_data(
        self, project_data_dir: Path
    ):
        from analytics.typefully_analytics import _read_analytics

        store = SQLiteStore(data_dir=str(project_data_dir))
        sentinel = {"sentinel": True}

        result = _read_analytics(
            store,
            project_data_dir / "typefully_metrics.json",
            default=sentinel,
        )

        assert result is sentinel

    def test_optimizer_reader_returns_empty_default_when_no_data(
        self, project_data_dir: Path
    ):
        from analytics.analytics_optimizer import _read_analytics

        store = SQLiteStore(data_dir=str(project_data_dir))

        result = _read_analytics(
            store,
            project_data_dir / "content_recommendations.json",
            default={},
        )

        assert result == {}


class TestUnifiedAnalyticsWriteThrough:
    def test_unified_analytics_persists_to_snapshot_and_file(
        self, project_data_dir: Path, monkeypatch
    ):
        from analytics.unified_analytics import UnifiedAnalytics

        monkeypatch.delenv("TYPEFULLY_API_KEY", raising=False)
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")

        unified = UnifiedAnalytics(data_dir=str(project_data_dir))
        _seed_metrics_file(
            project_data_dir,
            {"post_a": {"post_id": "post_a", "metrics": {"impressions": 10}}},
        )
        unified._create_unified_view()

        snapshot = unified.store.get_analytics_snapshot("unified_analytics.json", default=None)
        assert snapshot is not None, "UnifiedAnalytics must persist to analytics_snapshots"
        assert "combined_metrics" in snapshot
        assert snapshot["combined_metrics"]["total_posts"] == 1

        unified_file = project_data_dir / "unified_analytics.json"
        assert unified_file.exists(), (
            "UnifiedAnalytics must also write JSON file for backward compat"
        )
        file_payload = json.loads(unified_file.read_text())
        assert file_payload["combined_metrics"]["total_posts"] == 1


class TestCollectAnalyticsDataStoreArg:
    def test_collect_analytics_data_accepts_store_argument_and_prefers_snapshot(
        self, project_data_dir: Path
    ):
        from dashboard.analytics_runtime import collect_analytics_data

        store = SQLiteStore(data_dir=str(project_data_dir))
        snapshot_payload = {
            "post_b": {
                "post_id": "post_b",
                "metrics": {"impressions": 100, "likes": 10, "retweets": 5},
                "calculated_metrics": {"engagement_rate": 15.0},
            }
        }
        file_payload = {
            "post_a": {
                "post_id": "post_a",
                "metrics": {"impressions": 1, "likes": 0, "retweets": 0},
                "calculated_metrics": {"engagement_rate": 0.0},
            }
        }
        _seed_metrics_file(project_data_dir, file_payload)
        _seed_snapshot(store, "typefully_metrics.json", snapshot_payload)

        result = collect_analytics_data(project_data_dir, store=store)

        typefully = result["typefully"]
        assert typefully["status"] == "ok"
        assert typefully["total_posts"] == 1
        assert typefully["total_impressions"] == 100
        assert "post_b" in {p.get("post_id") for p in typefully["top_posts"]}

    def test_collect_analytics_data_without_store_falls_back_to_file(
        self, project_data_dir: Path
    ):
        from dashboard.analytics_runtime import collect_analytics_data

        file_payload = {
            "post_a": {
                "post_id": "post_a",
                "metrics": {"impressions": 50, "likes": 5, "retweets": 2},
                "calculated_metrics": {"engagement_rate": 10.0},
            }
        }
        _seed_metrics_file(project_data_dir, file_payload)

        result = collect_analytics_data(project_data_dir, store=None)

        typefully = result["typefully"]
        assert typefully["status"] == "ok"
        assert typefully["total_posts"] == 1
        assert typefully["total_impressions"] == 50


class TestJSONFilesNotDeleted:
    def test_typefully_metrics_json_remains_after_sqlite_first_read(
        self, project_data_dir: Path
    ):
        from analytics.typefully_analytics import _read_analytics

        store = SQLiteStore(data_dir=str(project_data_dir))
        file_path = _seed_metrics_file(project_data_dir, {"post_a": {"post_id": "post_a"}})
        _seed_snapshot(store, "typefully_metrics.json", {"post_b": {"post_id": "post_b"}})

        _read_analytics(store, file_path, default={})

        assert file_path.exists(), "Migration must NOT delete JSON fallback files"


# ---------------------------------------------------------------------------
# Plan 05-03 Task 2: learning_patterns SQLite path + storage topology docs
# ---------------------------------------------------------------------------


class TestLearningPatternsSQLitePath:
    def test_pattern_extractor_round_trips_through_project_service(self, seeded_store):
        from learning.pattern_extractor import PatternExtractor

        project = make_fixture_project(seeded_store)
        project_id = project["project_id"]

        extractor = PatternExtractor(base_dir=str(seeded_store.data_dir))
        patterns_payload = {
            "patterns": {
                "hook_style_a": {
                    "pattern_type": "hook_style",
                    "pattern": "question hook",
                    "effectiveness_score": 0.9,
                    "sample_size": 1,
                    "success_examples": [],
                    "failure_examples": [],
                    "confidence": "medium",
                    "last_updated": "2026-07-06T00:00:00Z",
                }
            }
        }

        from projects.manager import ProjectManager

        pm = ProjectManager()
        pm.save_learning_patterns(project_id, patterns_payload)
        loaded = pm.get_learning_patterns(project_id)
        assert "patterns" in loaded
        assert "hook_style_a" in loaded["patterns"]

    def test_idea_lab_learning_patterns_reader_prefers_sqlite(
        self, project_data_dir: Path, fixture_project
    ):
        from services.idea_lab import IdeaLabService

        store = SQLiteStore(data_dir=str(project_data_dir))
        project_id = fixture_project["project_id"]
        sqlite_payload = {
            "patterns": {
                "p1": {
                    "pattern_type": "hook_style",
                    "pattern": "from sqlite",
                    "effectiveness_score": 0.9,
                }
            }
        }
        store.set_project_value(project_id, "learning_patterns", sqlite_payload)
        file_payload = {
            "patterns": {
                "p2": {
                    "pattern_type": "hook_style",
                    "pattern": "from file",
                    "effectiveness_score": 0.9,
                }
            }
        }
        patterns_file = (
            Path(store.data_dir) / "projects" / project_id / "learning_patterns.json"
        )
        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(patterns_file, file_payload)

        service = IdeaLabService(store)
        text = service._load_learning_patterns(project_id)

        assert "from sqlite" in text
        assert "from file" not in text

    def test_idea_lab_learning_patterns_reader_falls_back_to_file_with_warning(
        self, project_data_dir: Path, fixture_project
    ):
        from services.idea_lab import IdeaLabService
        from services.idea_lab import _PATTERNS_MISSING

        store = SQLiteStore(data_dir=str(project_data_dir))
        project_id = fixture_project["project_id"]
        file_payload = {
            "patterns": {
                "p2": {
                    "pattern_type": "hook_style",
                    "pattern": "from file",
                    "effectiveness_score": 0.9,
                }
            }
        }
        patterns_file = (
            Path(store.data_dir) / "projects" / project_id / "learning_patterns.json"
        )
        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(patterns_file, file_payload)

        service = IdeaLabService(store)
        original_get = service.store.get_project_value

        def _force_missing(pid, key, default=None):
            if key == "learning_patterns":
                return _PATTERNS_MISSING
            return original_get(pid, key, default)

        service.store.get_project_value = _force_missing

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            text = service._load_learning_patterns(project_id)

        assert "from file" in text
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "File fallback must emit DeprecationWarning"


class TestStorageTopologyDocs:
    def test_data_and_media_storage_doc_exists(self):
        path = Path(__file__).resolve().parent.parent / "docs" / "data-and-media-storage.md"
        assert path.exists(), f"Expected docs file at {path}"

    def test_doc_names_required_paths(self):
        import re

        path = Path(__file__).resolve().parent.parent / "docs" / "data-and-media-storage.md"
        text = path.read_text()
        required_patterns = [
            r"data/media",
            r"data/videos",
            r"typefully_metrics\.json",
            r"learning_patterns\.json",
            r"orchestrator_scheduled\.json",
            r"system_events",
        ]
        missing = [p for p in required_patterns if not re.search(p, text)]
        assert not missing, f"docs/data-and-media-storage.md missing patterns: {missing}"

    def test_production_md_cross_references_topology_doc(self):
        path = Path(__file__).resolve().parent.parent / "docs" / "production.md"
        text = path.read_text()
        assert "data-and-media-storage.md" in text, (
            "docs/production.md must cross-reference docs/data-and-media-storage.md"
        )


# Late import so the seeded_store fixture (defined in conftest.py) is in scope
# for the TestLearningPatternsSQLitePath class methods.
from tests.fixtures.project_factory import make_fixture_project  # noqa: E402
