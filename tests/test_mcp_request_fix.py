"""Plan 04-02 Task 2: regression contract for mcp_server.server.request_fix.

Pins the BLOCKER #1 fix: after apply_auto_fix becomes sync and returns a
job dict, ``request_fix`` MUST NOT await it (would raise TypeError) and
MUST NOT read ``fixed.raw`` (would raise AttributeError). The tool returns
the queued-job envelope ``{success, review_id, auto_fix_status: "queued",
job_id}`` exactly like the dashboard JSON route.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def isolated_mcp_state(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
    monkeypatch.setenv("DRAPER_DATA_DIR", str(tmp_path))

    from data.sqlite_store import SQLiteStore
    from feedback.manager import FeedbackManager
    from services.content_workflow import ContentWorkflowService
    from services.idea_lab import IdeaLabService
    from services.job_queue import JobQueueService
    from services.project_context import ProjectContextService
    from services.project_service import ProjectService
    from services.publishing_service import ProjectPublishingService
    from services.review_workflow_service import ReviewWorkflowService

    store = SQLiteStore(data_dir=str(tmp_path), migrate=True)
    project_manager = ProjectService(data_dir=str(tmp_path))
    project = project_manager.create_project(
        "MCP Fix Test", platforms=["twitter"]
    )
    project_manager.set_current_project(project.project_id)

    feedback_manager = FeedbackManager(data_dir=str(tmp_path))
    project_context = ProjectContextService(project_manager)
    publishing_service = ProjectPublishingService(
        project_manager, data_dir=str(tmp_path), project_context=project_context
    )
    review_workflow = ReviewWorkflowService(
        feedback_manager, project_context, publishing_service
    )
    job_queue = JobQueueService(store)
    idea_lab = IdeaLabService(store)
    content_workflow = ContentWorkflowService(
        feedback_manager, project_context, publishing_service
    )

    import mcp_server.server as mcp_module

    monkeypatch.setattr(mcp_module, "STORE", store)
    monkeypatch.setattr(mcp_module, "PROJECT_MANAGER", project_manager)
    monkeypatch.setattr(mcp_module, "FEEDBACK_MANAGER", feedback_manager)
    monkeypatch.setattr(mcp_module, "PUBLISHING_SERVICE", publishing_service)
    monkeypatch.setattr(mcp_module, "PROJECT_CONTEXT", project_context)
    monkeypatch.setattr(mcp_module, "IDEA_LAB", idea_lab)
    monkeypatch.setattr(mcp_module, "JOB_QUEUE", job_queue)
    monkeypatch.setattr(mcp_module, "WORKFLOW", content_workflow)
    monkeypatch.setattr(mcp_module, "REVIEW_WORKFLOW", review_workflow)

    return {
        "store": store,
        "project_manager": project_manager,
        "feedback_manager": feedback_manager,
        "review_workflow": review_workflow,
        "job_queue": job_queue,
        "project_id": project.project_id,
    }


class TestMcpRequestFixQueuesJob:
    """Pin BLOCKER #1: request_fix returns queued-job envelope; no TypeError."""

    @pytest.mark.asyncio
    async def test_request_fix_returns_queued_envelope(self, isolated_mcp_state):
        import mcp_server.server as mcp_module

        review_id = (
            isolated_mcp_state["feedback_manager"]
            .add_for_review(
                {
                    "platform": "twitter",
                    "content_type": "tweet",
                    "content": "Sample content for MCP fix.",
                    "project_id": isolated_mcp_state["project_id"],
                }
            )["review_id"]
        )

        result = await mcp_module.request_fix(review_id=review_id, feedback="fix it")

        assert result["success"] is True
        assert result["review_id"] == review_id
        assert result["auto_fix_status"] == "queued"
        job_id = result["job_id"]
        job = isolated_mcp_state["job_queue"].get(job_id)
        assert job is not None
        assert job["kind"] == "fix_content"
        assert job["payload"]["review_id"] == review_id
