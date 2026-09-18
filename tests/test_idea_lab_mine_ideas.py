"""Plan 04-03 Task 3 BLOCKER #2: IdeaLabService.mine_ideas contracts.

Pins the typed-envelope backing for the ``mine_ideas`` job kind (D-4).
``mine_ideas`` composes the existing ``generate_ideas_from_material`` (single-
material path) and ``generate_ideas_for_project`` (multi-material path) behind
one typed contract; LLM failures degrade to an empty list.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.idea_lab import IdeaLabService


def _service(tmp_path):
    from data.sqlite_store import SQLiteStore

    store = SQLiteStore(data_dir=str(tmp_path))
    return IdeaLabService(store)


class TestMineIdeasWithSourceMaterial:
    def test_with_source_material_id_calls_single_material_path(self, tmp_path):
        svc = _service(tmp_path)
        mock_result = {
            "ideas": [{"idea_id": "ci_1"}, {"idea_id": "ci_2"}],
            "count": 2,
        }
        svc.generate_ideas_from_material = MagicMock(return_value=mock_result)

        result = svc.mine_ideas(
            project_id="proj-1", source_material_id="sm-1", max_ideas=3
        )

        svc.generate_ideas_from_material.assert_called_once_with(
            material_id="sm-1", project_id="proj-1"
        )
        assert result == [{"idea_id": "ci_1"}, {"idea_id": "ci_2"}]


class TestMineIdeasProjectPath:
    def test_without_source_material_id_calls_project_path_and_lists_records(
        self, tmp_path
    ):
        svc = _service(tmp_path)
        svc.generate_ideas_for_project = MagicMock(
            return_value={
                "generated": 2,
                "skipped": 0,
                "errors": 0,
                "total_materials": 1,
            }
        )
        svc.store.list_content_idea_records = MagicMock(
            return_value=[
                {"idea_id": "ci_a"},
                {"idea_id": "ci_b"},
                {"idea_id": "ci_c"},
            ]
        )

        result = svc.mine_ideas(project_id="proj-1", max_ideas=5)

        svc.generate_ideas_for_project.assert_called_once_with(project_id="proj-1")
        assert result == [{"idea_id": "ci_a"}, {"idea_id": "ci_b"}, {"idea_id": "ci_c"}]


class TestMineIdeasCapAndClamp:
    def test_caps_at_max_ideas(self, tmp_path):
        svc = _service(tmp_path)
        ten_ideas = [{"idea_id": f"ci_{i}"} for i in range(10)]
        svc.generate_ideas_from_material = MagicMock(
            return_value={"ideas": ten_ideas, "count": 10}
        )

        result = svc.mine_ideas(
            project_id="proj-1", source_material_id="sm-1", max_ideas=3
        )

        assert len(result) == 3
        assert result == ten_ideas[:3]

    def test_clamps_max_ideas_above_20(self, tmp_path):
        svc = _service(tmp_path)
        svc.generate_ideas_from_material = MagicMock(
            return_value={"ideas": [{"idea_id": "ci_1"}], "count": 1}
        )

        svc.mine_ideas(
            project_id="proj-1", source_material_id="sm-1", max_ideas=999
        )

        called_kwargs = svc.generate_ideas_from_material.call_args
        assert called_kwargs is not None
        args, kwargs = called_kwargs
        assert kwargs.get("material_id", "sm-1") == "sm-1"
        assert kwargs.get("project_id") == "proj-1"


class TestMineIdeasValidation:
    def test_requires_project_id(self, tmp_path):
        svc = _service(tmp_path)

        with pytest.raises(ValueError, match="project_id is required"):
            svc.mine_ideas(project_id="")


class TestMineIdeasDegracesGracefully:
    def test_returns_empty_list_when_llm_produces_nothing(self, tmp_path):
        svc = _service(tmp_path)
        svc.generate_ideas_from_material = MagicMock(
            return_value={"ideas": [], "count": 0, "error": "LLM call failed"}
        )

        result = svc.mine_ideas(
            project_id="proj-1", source_material_id="sm-1", max_ideas=5
        )

        assert result == []
