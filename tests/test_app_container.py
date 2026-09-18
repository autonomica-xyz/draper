"""Plan 03-01 Task 1: AppContainer + dependencies + request_models regression."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def container(project_data_dir, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
    from dashboard.app_container import AppContainer

    return AppContainer(data_dir=str(project_data_dir))


class TestAppContainerConstruction:
    def test_every_collaborator_is_wired(self, container):
        collaborators = [
            "project_manager",
            "store",
            "project_context",
            "secret_service",
            "feedback_manager",
            "analytics",
            "reasoning_tracker",
            "publishing_service",
            "content_workflow",
            "review_workflow",
            "job_queue",
            "idea_lab",
            "job_runner",
            "publishing_manager",
        ]
        for attr in collaborators:
            value = getattr(container, attr, None)
            assert value is not None, f"container.{attr} is None"

    def test_dashboard_property_returns_underlying_instance(self, container):
        from dashboard.unified_dashboard import UnifiedDashboard

        assert isinstance(container.dashboard, UnifiedDashboard)

    def test_review_workflow_is_review_workflow_service(self, container):
        from services.review_workflow_service import ReviewWorkflowService

        assert isinstance(container.review_workflow, ReviewWorkflowService)

    def test_paths_exposed(self, container):
        assert hasattr(container, "scheduled_file")
        assert hasattr(container, "posts_history_file")

    def test_generator_tolerates_missing_keys(self, container):
        assert container.generator is None


class TestDependenciesAccessors:
    def test_get_container_returns_app_state_container(self, container):
        from dashboard.dependencies import get_container

        request = MagicMock()
        request.app.state.container = container
        assert get_container(request) is container

    def test_get_review_workflow_returns_container_attribute(self, container):
        from dashboard.dependencies import get_review_workflow

        request = MagicMock()
        request.app.state.container = container
        assert get_review_workflow(request) is container.review_workflow

    def test_every_accessor_returns_expected_attribute(self, container):
        from dashboard import dependencies

        request = MagicMock()
        request.app.state.container = container
        pairs = [
            (dependencies.get_project_manager, "project_manager"),
            (dependencies.get_project_context, "project_context"),
            (dependencies.get_review_workflow, "review_workflow"),
            (dependencies.get_content_workflow, "content_workflow"),
            (dependencies.get_publishing_service, "publishing_service"),
            (dependencies.get_job_queue, "job_queue"),
            (dependencies.get_idea_lab, "idea_lab"),
            (dependencies.get_feedback_manager, "feedback_manager"),
            (dependencies.get_analytics, "analytics"),
            (dependencies.get_reasoning_tracker, "reasoning_tracker"),
            (dependencies.get_secret_service, "secret_service"),
            (dependencies.get_publishing_manager, "publishing_manager"),
            (dependencies.get_job_runner, "job_runner"),
            (dependencies.get_store, "store"),
        ]
        for getter, attr in pairs:
            assert getter(request) is getattr(container, attr), getter.__name__


class TestRequestModelsHomes:
    """Plan 03-04 Task 1: each Pydantic request model lives next to its
    consuming route group; dashboard.request_models is deleted."""

    def test_approve_content_request_defaults_publish_true(self):
        from dashboard.routes.reviews import ApproveContentRequest

        body = ApproveContentRequest()
        assert body.publish is True

    def test_approve_content_request_accepts_publish_false(self):
        from dashboard.routes.reviews import ApproveContentRequest

        body = ApproveContentRequest.model_validate({"publish": False})
        assert body.publish is False

    def test_provider_mapping_request_accepts_known_provider(self):
        from dashboard.routes.projects import ProviderMappingRequest

        body = ProviderMappingRequest.model_validate({"twitter": "typefully"})
        assert body.root == {"twitter": "typefully"}

    def test_provider_mapping_request_rejects_unknown_provider(self):
        from pydantic import ValidationError

        from dashboard.routes.projects import ProviderMappingRequest

        with pytest.raises(ValidationError):
            ProviderMappingRequest.model_validate({"twitter": "bogus"})

    def test_provider_mapping_request_normalizes_x_to_twitter(self):
        from dashboard.routes.projects import ProviderMappingRequest

        body = ProviderMappingRequest.model_validate({"x": "typefully"})
        assert body.root == {"twitter": "typefully"}

    def test_six_models_live_in_their_consuming_route_modules(self):
        from dashboard.routes.generation import GenerateContentRequest
        from dashboard.routes.projects import (
            ContentPlanRequest,
            ProviderMappingRequest,
        )
        from dashboard.routes.reviews import (
            ApproveContentRequest,
            PublishContentRequest,
            ScheduleContentRequest,
        )

        for model in (
            GenerateContentRequest,
            PublishContentRequest,
            ScheduleContentRequest,
            ApproveContentRequest,
            ContentPlanRequest,
            ProviderMappingRequest,
        ):
            assert model.__module__.startswith("dashboard.routes."), model

    def test_unified_dashboard_reexport_matches_canonical_home(self):
        from dashboard.routes.reviews import ApproveContentRequest as Canonical
        from dashboard.unified_dashboard import ApproveContentRequest as Reexported

        assert Reexported.model_fields.keys() == Canonical.model_fields.keys()
        assert Reexported().publish == Canonical().publish
