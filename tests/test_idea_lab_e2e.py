#!/usr/bin/env python3
"""End-to-end integration tests for the full idea lab lifecycle.

Exercises the complete stack: create project → ingest material → create idea →
evaluate (approve/reject) → verify dashboard HTML renders idea elements.
Uses the same test app factory pattern as test_idea_lab_api.py.
"""

import json
import tempfile
from typing import Generator

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import TemplateNotFound
from starlette.testclient import TestClient

from dashboard.unified_dashboard import UnifiedDashboard

# ---------------------------------------------------------------------------
# Test app factories
# ---------------------------------------------------------------------------


def _create_api_app(data_dir: str):
    """Create a FastAPI app with idea lab API routes (mirrors main() setup).

    Returns (app, dashboard_instance) so tests can inspect state.
    """
    dashboard = UnifiedDashboard(data_dir=data_dir)
    app = FastAPI(title="Test Idea Lab E2E API")
    dashboard_instance = dashboard

    # ---- Source material routes ----

    @app.post("/api/ideas/materials")
    async def api_create_source_material(request: Request):
        try:
            body = await request.json()
            project_id = body.get("project_id")
            if not project_id:
                current = dashboard_instance.get_current_project()
                if current:
                    project_id = current.project_id
                else:
                    return {"success": False, "error": "project_id is required (no current project)"}
            material = dashboard_instance.idea_lab.add_source_material(
                project_id=project_id,
                url=body.get("url"),
                text_content=body.get("text_content"),
                note=body.get("note"),
                title=body.get("title"),
                tags=body.get("tags"),
            )
            return {"success": True, "material": material}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/ideas/materials")
    async def api_list_source_materials(request: Request):
        try:
            project_id = request.query_params.get("project_id")
            if not project_id:
                current = dashboard_instance.get_current_project()
                if current:
                    project_id = current.project_id
                else:
                    return {"success": False, "error": "project_id is required (no current project)"}
            items = dashboard_instance.idea_lab.list_source_material(
                project_id=project_id,
            )
            return {
                "success": True,
                "total": len(items),
                "items": [item.to_dict() for item in items],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- Content idea routes ----

    @app.post("/api/ideas/ideas")
    async def api_create_content_idea(request: Request):
        try:
            body = await request.json()
            project_id = body.get("project_id")
            if not project_id:
                current = dashboard_instance.get_current_project()
                if current:
                    project_id = current.project_id
                else:
                    return {"success": False, "error": "project_id is required (no current project)"}
            idea = dashboard_instance.idea_lab.add_content_idea(
                project_id=project_id,
                title=body.get("title", ""),
                hook_angle=body.get("hook_angle", ""),
                target_platforms=body.get("target_platforms"),
                content_pillar=body.get("content_pillar", ""),
                rationale=body.get("rationale", ""),
                suggested_format=body.get("suggested_format", ""),
                source_material_ids=body.get("source_material_ids"),
                tags=body.get("tags"),
                metadata=body.get("metadata"),
            )
            return {"success": True, "idea": idea}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/ideas/ideas")
    async def api_list_content_ideas(request: Request):
        try:
            project_id = request.query_params.get("project_id")
            if not project_id:
                current = dashboard_instance.get_current_project()
                if current:
                    project_id = current.project_id
                else:
                    return {"success": False, "error": "project_id is required (no current project)"}
            status = request.query_params.get("status")
            ideas = dashboard_instance.idea_lab.list_content_ideas(
                project_id=project_id,
                status=status,
            )
            return {
                "success": True,
                "total": len(ideas),
                "items": [i.to_dict() for i in ideas],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/api/ideas/ideas/{idea_id}/evaluate")
    async def api_evaluate_content_idea(idea_id: str, request: Request):
        try:
            body = await request.json()
            updated = dashboard_instance.idea_lab.evaluate_content_idea(
                idea_id=idea_id,
                new_status=body.get("status", ""),
                evaluation_notes=body.get("evaluation_notes"),
            )
            return {"success": True, "idea": updated}
        except ValueError as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/api/ideas/ideas/{idea_id}/approve-and-generate")
    async def api_approve_and_generate(idea_id: str, request: Request):
        """Approve a content idea and generate platform-specific content."""
        try:
            body = await request.json()
            project_id = body.get("project_id")
            if not project_id:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "project_id is required"},
                )
            result = dashboard_instance.idea_lab.approve_and_generate_content(
                idea_id=idea_id,
                project_id=project_id,
                feedback_manager=dashboard_instance.feedback_manager,
            )
            return result
        except ValueError as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/api/ideas/mining/trigger")
    async def api_mining_trigger(request: Request):
        """Run the full mining pipeline: enrich all pending, then generate ideas."""
        try:
            body = await request.json()
        except Exception:
            body = {}

        project_id = body.get("project_id")
        if not project_id:
            current = dashboard_instance.get_current_project()
            if current:
                project_id = current.project_id
            else:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "project_id is required (no current project)"},
                )

        enrichment = dashboard_instance.idea_lab.enrich_all_pending(project_id)
        ideas = dashboard_instance.idea_lab.generate_ideas_for_project(project_id)
        return {"success": True, "enrichment": enrichment, "ideas": ideas}

    return app, dashboard


def _create_html_app(data_dir: str):
    """Create a FastAPI app that serves the dashboard HTML page with ideas tab.

    Returns (app, dashboard_instance).
    """
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    dashboard = UnifiedDashboard(data_dir=data_dir)
    app = FastAPI(title="Test Idea Lab E2E HTML")
    dashboard_instance = dashboard

    templates_dir = Path(__file__).resolve().parent.parent / "dashboard" / "templates"
    jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        active_tab = request.query_params.get("tab", "pipeline")
        project_id = request.query_params.get("project")

        projects = dashboard_instance.get_projects()
        current_project = dashboard_instance.get_current_project(project_id)

        try:
            template = jinja_env.get_template("unified.html")
            html = template.render(
                request=request,
                active_tab=active_tab,
                projects=projects,
                current_project=current_project,
                content=[],
                analytics=None,
                scheduled=[],
                calendar_data={},
                strategy_content="",
                settings_data={},
            )
            return HTMLResponse(content=html)
        except TemplateNotFound:
            return HTMLResponse(content="<html><body>Template not found</body></html>", status_code=500)

    return app, dashboard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_env() -> Generator[dict, None, None]:
    """Provide a TestClient wired to the API test app."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app, dashboard = _create_api_app(tmpdir)
        client = TestClient(app, raise_server_exceptions=False)
        yield {
            "client": client,
            "dashboard": dashboard,
            "data_dir": tmpdir,
        }


@pytest.fixture
def html_env() -> Generator[dict, None, None]:
    """Provide a TestClient wired to the HTML test app with Jinja2 templates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app, dashboard = _create_html_app(tmpdir)
        client = TestClient(app, raise_server_exceptions=False)
        yield {
            "client": client,
            "dashboard": dashboard,
            "data_dir": tmpdir,
        }


# ===========================================================================
# 1. Full lifecycle test
# ===========================================================================


class TestFullLifecycle:
    """End-to-end: project → materials → idea → evaluate → verify."""

    PROJECT_ID = "e2e-lifecycle-project"

    def test_full_idea_lifecycle(self, api_env):
        """Create project, ingest materials (URL + text), create idea,
        approve it, then reject another — verifying each stage."""
        client = api_env["client"]
        dashboard = api_env["dashboard"]
        pid = self.PROJECT_ID

        # Create a project and set as current so project-scoped lookups work
        dashboard.project_manager.create_project(name="E2E Lifecycle")
        projects = dashboard.project_manager.list_projects()
        proj = projects[0]
        pid = proj.project_id
        dashboard.project_manager.set_current_project(pid)

        # Step 1: POST URL-type material
        resp = client.post("/api/ideas/materials", json={
            "project_id": pid,
            "url": "https://example.com/article-about-growth",
            "title": "Growth Article",
            "tags": ["growth", "strategy"],
        })
        assert resp.status_code == 200
        mat_url = resp.json()
        assert mat_url["success"] is True
        assert mat_url["material"]["material_type"] == "url"
        url_mat_id = mat_url["material"]["material_id"]

        # Step 2: POST text-type material
        resp = client.post("/api/ideas/materials", json={
            "project_id": pid,
            "text_content": "Long-form insights about content marketing ROI...",
            "title": "ROI Notes",
        })
        assert resp.status_code == 200
        mat_text = resp.json()
        assert mat_text["success"] is True
        assert mat_text["material"]["material_type"] == "text"
        text_mat_id = mat_text["material"]["material_id"]

        # Step 3: POST idea referencing both materials
        resp = client.post("/api/ideas/ideas", json={
            "project_id": pid,
            "title": "Content ROI Thread",
            "hook_angle": "Most marketers measure content ROI wrong",
            "target_platforms": ["twitter", "linkedin"],
            "content_pillar": "thought-leadership",
            "rationale": "Backed by two strong source materials",
            "source_material_ids": [url_mat_id, text_mat_id],
            "tags": ["roi", "metrics"],
        })
        assert resp.status_code == 200
        idea_data = resp.json()
        assert idea_data["success"] is True
        idea_id = idea_data["idea"]["idea_id"]
        assert idea_data["idea"]["status"] == "draft"
        assert idea_data["idea"]["title"] == "Content ROI Thread"

        # Step 4: GET ideas — verify it's returned
        resp = client.get("/api/ideas/ideas", params={"project_id": pid})
        assert resp.status_code == 200
        ideas_list = resp.json()
        assert ideas_list["success"] is True
        assert ideas_list["total"] == 1
        assert ideas_list["items"][0]["idea_id"] == idea_id

        # Step 5: POST evaluate — approve the idea
        resp = client.post(f"/api/ideas/ideas/{idea_id}/evaluate", json={
            "status": "approved",
            "evaluation_notes": "Strong hook, well-sourced",
        })
        assert resp.status_code == 200
        eval_data = resp.json()
        assert eval_data["success"] is True
        assert eval_data["idea"]["status"] == "approved"

        # Step 6: GET ideas — verify status=approved
        resp = client.get("/api/ideas/ideas", params={"project_id": pid, "status": "approved"})
        assert resp.status_code == 200
        approved = resp.json()
        assert approved["total"] == 1
        assert approved["items"][0]["status"] == "approved"

        # Step 7: Move approved idea back to draft, then reject
        resp = client.post(f"/api/ideas/ideas/{idea_id}/evaluate", json={
            "status": "draft",
            "evaluation_notes": "Reconsidering",
        })
        assert resp.status_code == 200
        assert resp.json()["idea"]["status"] == "draft"

        resp = client.post(f"/api/ideas/ideas/{idea_id}/evaluate", json={
            "status": "rejected",
            "evaluation_notes": "Not aligned with current campaign",
        })
        assert resp.status_code == 200
        assert resp.json()["idea"]["status"] == "rejected"

        # Step 8: GET ideas — verify status=rejected
        resp = client.get("/api/ideas/ideas", params={"project_id": pid, "status": "rejected"})
        assert resp.status_code == 200
        rejected = resp.json()
        assert rejected["total"] == 1
        assert rejected["items"][0]["status"] == "rejected"


# ===========================================================================
# 2. Project isolation
# ===========================================================================


class TestProjectIsolation:
    """Create two projects, add materials/ideas to each, verify no cross-contamination."""

    def test_materials_isolated_between_projects(self, api_env):
        """Materials in project A are invisible when listing project B."""
        client = api_env["client"]

        # Create materials in project A
        resp_a = client.post("/api/ideas/materials", json={
            "project_id": "iso-project-alpha",
            "url": "https://alpha.example.com",
            "title": "Alpha Material",
        })
        assert resp_a.json()["success"] is True

        # Create materials in project B
        resp_b = client.post("/api/ideas/materials", json={
            "project_id": "iso-project-beta",
            "text_content": "Beta text content",
            "title": "Beta Material",
        })
        assert resp_b.json()["success"] is True

        # Verify A has 1 material, B has 1 material
        list_a = client.get("/api/ideas/materials", params={"project_id": "iso-project-alpha"}).json()
        list_b = client.get("/api/ideas/materials", params={"project_id": "iso-project-beta"}).json()

        assert list_a["total"] == 1
        assert list_a["items"][0]["title"] == "Alpha Material"

        assert list_b["total"] == 1
        assert list_b["items"][0]["title"] == "Beta Material"

    def test_ideas_isolated_between_projects(self, api_env):
        """Ideas in project A are invisible when listing project B."""
        client = api_env["client"]

        # Create idea in project A
        resp_a = client.post("/api/ideas/ideas", json={
            "project_id": "iso-idea-alpha",
            "title": "Alpha Idea",
            "hook_angle": "Alpha hook",
        })
        assert resp_a.json()["success"] is True
        alpha_id = resp_a.json()["idea"]["idea_id"]

        # Create idea in project B
        resp_b = client.post("/api/ideas/ideas", json={
            "project_id": "iso-idea-beta",
            "title": "Beta Idea",
            "hook_angle": "Beta hook",
        })
        assert resp_b.json()["success"] is True
        beta_id = resp_b.json()["idea"]["idea_id"]

        # Verify isolation
        list_a = client.get("/api/ideas/ideas", params={"project_id": "iso-idea-alpha"}).json()
        list_b = client.get("/api/ideas/ideas", params={"project_id": "iso-idea-beta"}).json()

        assert list_a["total"] == 1
        assert list_a["items"][0]["idea_id"] == alpha_id

        assert list_b["total"] == 1
        assert list_b["items"][0]["idea_id"] == beta_id

    def test_full_isolation_with_materials_and_ideas(self, api_env):
        """Create two projects with materials + ideas, verify complete isolation."""
        client = api_env["client"]

        # Project Alpha: 2 materials, 1 idea
        mat_a1 = client.post("/api/ideas/materials", json={
            "project_id": "iso-full-alpha",
            "url": "https://alpha1.com",
        }).json()
        mat_a2 = client.post("/api/ideas/materials", json={
            "project_id": "iso-full-alpha",
            "text_content": "Alpha text",
        }).json()
        client.post("/api/ideas/ideas", json={
            "project_id": "iso-full-alpha",
            "title": "Alpha Full Idea",
            "source_material_ids": [mat_a1["material"]["material_id"], mat_a2["material"]["material_id"]],
        }).json()

        # Project Beta: 1 material, 2 ideas
        mat_b = client.post("/api/ideas/materials", json={
            "project_id": "iso-full-beta",
            "url": "https://beta1.com",
        }).json()
        client.post("/api/ideas/ideas", json={
            "project_id": "iso-full-beta",
            "title": "Beta Idea 1",
        }).json()
        client.post("/api/ideas/ideas", json={
            "project_id": "iso-full-beta",
            "title": "Beta Idea 2",
            "source_material_ids": [mat_b["material"]["material_id"]],
        }).json()

        # Verify Alpha counts
        alpha_mats = client.get("/api/ideas/materials", params={"project_id": "iso-full-alpha"}).json()
        alpha_ideas = client.get("/api/ideas/ideas", params={"project_id": "iso-full-alpha"}).json()
        assert alpha_mats["total"] == 2
        assert alpha_ideas["total"] == 1

        # Verify Beta counts
        beta_mats = client.get("/api/ideas/materials", params={"project_id": "iso-full-beta"}).json()
        beta_ideas = client.get("/api/ideas/ideas", params={"project_id": "iso-full-beta"}).json()
        assert beta_mats["total"] == 1
        assert beta_ideas["total"] == 2


# ===========================================================================
# 3. Dashboard HTML rendering
# ===========================================================================


class TestDashboardHTMLRendering:
    """Verify the dashboard HTML page contains idea-related elements."""

    def test_ideas_tab_present_in_html(self, html_env):
        """GET dashboard page contains the Ideas tab button."""
        client = html_env["client"]
        resp = client.get("/?tab=ideas")
        assert resp.status_code == 200
        html = resp.text
        # Ideas tab button
        assert "switchTab('ideas')" in html
        assert ">Ideas<" in html

    def test_idea_status_filters_present(self, html_env):
        """GET dashboard ideas tab contains the status filter bar."""
        client = html_env["client"]
        resp = client.get("/?tab=ideas")
        assert resp.status_code == 200
        html = resp.text
        assert "idea-status-filters" in html

    def test_idea_form_elements_present(self, html_env):
        """GET dashboard ideas tab contains the idea form with expected inputs."""
        client = html_env["client"]
        dashboard = html_env["dashboard"]
        # Ideas content is gated on {% if current_project %} in the template
        dashboard.project_manager.create_project(name="HTML Test")
        proj = dashboard.project_manager.list_projects()[0]
        dashboard.project_manager.set_current_project(proj.project_id)

        resp = client.get(f"/?tab=ideas&project={proj.project_id}")
        assert resp.status_code == 200
        html = resp.text
        assert 'id="idea-title"' in html
        assert 'id="idea-hook"' in html
        assert 'id="idea-form"' in html

    def test_material_form_present(self, html_env):
        """GET dashboard ideas tab contains the material form."""
        client = html_env["client"]
        dashboard = html_env["dashboard"]
        dashboard.project_manager.create_project(name="HTML Test 2")
        proj = dashboard.project_manager.list_projects()[0]
        dashboard.project_manager.set_current_project(proj.project_id)

        resp = client.get(f"/?tab=ideas&project={proj.project_id}")
        assert resp.status_code == 200
        html = resp.text
        assert 'id="material-form"' in html


# ===========================================================================
# 4. Error cases
# ===========================================================================


class TestErrorCases:
    """Verify error handling for missing project context and invalid operations."""

    def test_create_idea_without_project_returns_error(self, api_env):
        """Creating an idea with no project_id and no current project returns error."""
        client = api_env["client"]
        # No project set, no project_id in body
        resp = client.post("/api/ideas/ideas", json={
            "title": "Orphan Idea",
            "hook_angle": "No project",
        })
        data = resp.json()
        assert data["success"] is False
        assert "project_id" in data["error"].lower()

    def test_create_material_without_project_returns_error(self, api_env):
        """Creating material with no project_id and no current project returns error."""
        client = api_env["client"]
        resp = client.post("/api/ideas/materials", json={
            "url": "https://example.com",
        })
        data = resp.json()
        assert data["success"] is False
        assert "project_id" in data["error"].lower()

    def test_evaluate_nonexistent_idea_returns_error(self, api_env):
        """Evaluating a non-existent idea returns an error."""
        client = api_env["client"]
        resp = client.post("/api/ideas/ideas/nonexistent-id/evaluate", json={
            "status": "approved",
        })
        data = resp.json()
        assert data["success"] is False

    def test_invalid_status_transition_returns_400(self, api_env):
        """Attempting an invalid status transition returns 400."""
        client = api_env["client"]

        # Create an idea
        resp = client.post("/api/ideas/ideas", json={
            "project_id": "error-test-project",
            "title": "Transition Test Idea",
        })
        idea_id = resp.json()["idea"]["idea_id"]

        # Approve it
        client.post(f"/api/ideas/ideas/{idea_id}/evaluate", json={"status": "approved"})

        # Try invalid transition: approved → approved (no-op)
        resp = client.post(f"/api/ideas/ideas/{idea_id}/evaluate", json={
            "status": "approved",
        })
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False


# ===========================================================================
# 5. Mining trigger E2E
# ===========================================================================

# Helper: fake LLM responses for enrichment pipeline stages
_FAKE_KEY_POINTS = '["Key insight about marketing ROI", "Data-driven approach works"]'
_FAKE_AUTO_TAGS = '["marketing", "roi", "data-driven"]'
_FAKE_IDEAS_JSON = json.dumps([
    {
        "title": "Marketing ROI Thread",
        "hook_angle": "Most teams measure ROI wrong",
        "target_platforms": ["twitter"],
        "content_pillar": "thought-leadership",
        "rationale": "Backed by source data",
        "suggested_format": "thread",
    }
])


def _make_enrichment_mock():
    """Create a fake _call_llm_for_enrichment that returns enrichment-appropriate responses."""
    call_count = {"n": 0}

    def fake_llm(prompt, max_tokens=1500):
        call_count["n"] += 1
        plower = prompt.lower()
        if "generate 2 to 5 content ideas" in plower:
            return _FAKE_IDEAS_JSON
        elif "key point" in plower:
            return _FAKE_KEY_POINTS
        elif "tag" in plower:
            return _FAKE_AUTO_TAGS
        elif "TWITTER" in prompt or "LINKEDIN" in prompt or "NOSTR" in prompt:
            return "Generated platform content about marketing."
        return f"Generic LLM response {call_count['n']}"

    return fake_llm


class TestMiningTriggerPipeline:
    """E2E: create un-enriched materials → mining trigger → verify enrichment + ideas."""

    PROJECT_ID = "mining-e2e-project"

    def _setup_project(self, api_env):
        """Create a project and set as current; return project_id."""
        dashboard = api_env["dashboard"]
        dashboard.project_manager.create_project(name="Mining E2E")
        proj = dashboard.project_manager.list_projects()[0]
        dashboard.project_manager.set_current_project(proj.project_id)
        return proj.project_id

    def test_mining_trigger_enriches_and_generates_ideas(self, api_env):
        """Mining trigger enriches text materials and generates ideas via LLM."""
        import unittest.mock

        client = api_env["client"]
        pid = self._setup_project(api_env)

        # Create text-type material (not yet enriched)
        resp = client.post("/api/ideas/materials", json={
            "project_id": pid,
            "text_content": "Long-form insights about content marketing ROI and data-driven strategies...",
            "title": "ROI Notes",
        })
        assert resp.json()["success"] is True
        mat_id = resp.json()["material"]["material_id"]

        # Verify material is not enriched
        materials = client.get("/api/ideas/materials", params={"project_id": pid}).json()
        assert materials["total"] == 1
        meta = materials["items"][0].get("metadata_json", {})
        assert meta.get("enrichment_status", "") != "enriched"

        # Run mining trigger with mocked LLM
        idea_lab = api_env["dashboard"].idea_lab
        with unittest.mock.patch.object(
            idea_lab, "_call_llm_for_enrichment", side_effect=_make_enrichment_mock()
        ):
            resp = client.post("/api/ideas/mining/trigger", json={"project_id": pid})

        data = resp.json()
        assert data["success"] is True

        # Enrichment: 1 material processed
        enrichment = data["enrichment"]
        assert enrichment["total"] == 1
        assert enrichment["enriched"] == 1
        assert enrichment["failed"] == 0
        assert enrichment["skipped"] == 0

        # Ideas: at least 1 generated
        ideas = data["ideas"]
        assert ideas["total_materials"] == 1
        assert ideas["generated"] >= 1

        # Verify material is now enriched
        materials = client.get("/api/ideas/materials", params={"project_id": pid}).json()
        assert materials["items"][0]["metadata_json"]["enrichment_status"] == "enriched"

        # Verify idea exists
        ideas_list = client.get("/api/ideas/ideas", params={"project_id": pid}).json()
        assert ideas_list["total"] >= 1

    def test_mining_trigger_no_project_id_returns_error(self, api_env):
        """Mining trigger without project_id and no current project returns 400."""
        client = api_env["client"]
        resp = client.post("/api/ideas/mining/trigger", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "project_id" in data["error"].lower()

    def test_mining_trigger_empty_project_returns_zeros(self, api_env):
        """Mining trigger on a project with no materials returns zero counts."""
        client = api_env["client"]
        pid = self._setup_project(api_env)

        resp = client.post("/api/ideas/mining/trigger", json={"project_id": pid})
        data = resp.json()
        assert data["success"] is True
        assert data["enrichment"]["total"] == 0
        assert data["ideas"]["total_materials"] == 0


class TestMiningTriggerIdempotency:
    """Second mining trigger call should skip already-enriched materials."""

    PROJECT_ID = "mining-idem-project"

    def test_second_call_skips_already_processed(self, api_env):
        """Running mining trigger twice skips already-enriched materials and existing ideas."""
        import unittest.mock

        client = api_env["client"]
        dashboard = api_env["dashboard"]
        dashboard.project_manager.create_project(name="Mining Idempotency")
        proj = dashboard.project_manager.list_projects()[0]
        pid = proj.project_id
        dashboard.project_manager.set_current_project(pid)

        # Create a text material
        client.post("/api/ideas/materials", json={
            "project_id": pid,
            "text_content": "Content about growth marketing strategies.",
            "title": "Growth Strategies",
        })

        idea_lab = dashboard.idea_lab
        mock_fn = _make_enrichment_mock()

        # First call
        with unittest.mock.patch.object(
            idea_lab, "_call_llm_for_enrichment", side_effect=mock_fn
        ):
            resp1 = client.post("/api/ideas/mining/trigger", json={"project_id": pid})

        data1 = resp1.json()
        assert data1["success"] is True
        assert data1["enrichment"]["enriched"] == 1
        assert data1["ideas"]["generated"] >= 1

        # Second call — should skip enriched materials and existing ideas
        with unittest.mock.patch.object(
            idea_lab, "_call_llm_for_enrichment", side_effect=mock_fn
        ):
            resp2 = client.post("/api/ideas/mining/trigger", json={"project_id": pid})

        data2 = resp2.json()
        assert data2["success"] is True
        # Material is already enriched, so it should be skipped
        assert data2["enrichment"]["skipped"] == 1
        assert data2["enrichment"]["enriched"] == 0
        assert data2["enrichment"]["total"] == 1


class TestApproveAndGeneratePipeline:
    """E2E: create idea → approve-and-generate → verify review records."""

    PROJECT_ID = "approve-gen-e2e-project"

    def _setup_project_with_idea(self, api_env, target_platforms=None):
        """Create project + material + idea. Return (pid, idea_id)."""
        dashboard = api_env["dashboard"]
        dashboard.project_manager.create_project(name="ApproveGen E2E")
        proj = dashboard.project_manager.list_projects()[0]
        pid = proj.project_id
        dashboard.project_manager.set_current_project(pid)

        body = {
            "project_id": pid,
            "title": "Marketing ROI Thread",
            "hook_angle": "Most teams measure ROI wrong",
            "target_platforms": target_platforms or ["twitter"],
            "content_pillar": "thought-leadership",
            "rationale": "Data-backed insights",
        }
        resp = api_env["client"].post("/api/ideas/ideas", json=body)
        assert resp.json()["success"] is True
        idea_id = resp.json()["idea"]["idea_id"]
        return pid, idea_id

    def test_full_pipeline_approve_and_generate(self, api_env):
        """Create idea → approve-and-generate → review records exist with correct metadata."""
        import unittest.mock

        client = api_env["client"]
        pid, idea_id = self._setup_project_with_idea(
            api_env, target_platforms=["twitter", "linkedin"]
        )
        dashboard = api_env["dashboard"]
        idea_lab = dashboard.idea_lab

        call_count = {"n": 0}

        def fake_llm(prompt, max_tokens=1000):
            call_count["n"] += 1
            if "TWITTER" in prompt:
                return "Tweet about marketing ROI! #growth"
            elif "LINKEDIN" in prompt:
                return "LinkedIn post about data-driven marketing ROI."
            return f"Generic content {call_count['n']}"

        with unittest.mock.patch.object(
            idea_lab, "_call_llm_for_enrichment", side_effect=fake_llm
        ):
            resp = client.post(
                f"/api/ideas/ideas/{idea_id}/approve-and-generate",
                json={"project_id": pid},
            )

        data = resp.json()
        assert data["success"] is True
        assert data["idea_id"] == idea_id
        assert set(data["generated_platforms"]) == {"twitter", "linkedin"}
        assert len(data["review_ids"]) == 2
        assert data["errors"] == []

        # Verify review records exist in the store with correct metadata
        store = idea_lab.store
        for rid in data["review_ids"]:
            rec = store.get_review_record(rid)
            assert rec is not None
            assert rec["status"] == "pending_review"
            assert rec["post_data"]["idea_id"] == idea_id
            assert rec["post_data"]["project_id"] == pid
            assert rec["post_data"]["platform"] in {"twitter", "linkedin"}

        # Verify idea is now approved
        idea = store.get_content_idea_record(idea_id)
        assert idea["status"] == "approved"
        assert idea["metadata_json"]["generation_status"] == "content_generated"

    def test_approve_and_generate_no_project_id_returns_400(self, api_env):
        """approve-and-generate without project_id returns 400."""
        client = api_env["client"]
        resp = client.post("/api/ideas/ideas/nonexistent-id/approve-and-generate", json={})
        assert resp.status_code == 400
        assert resp.json()["success"] is False

    def test_approve_and_generate_nonexistent_idea_returns_error(self, api_env):
        """approve-and-generate with non-existent idea returns error."""
        client = api_env["client"]
        resp = client.post(
            "/api/ideas/ideas/nonexistent-xyz/approve-and-generate",
            json={"project_id": "any-project"},
        )
        data = resp.json()
        assert data["success"] is False

    def test_approve_and_generate_llm_failure(self, api_env):
        """When LLM fails, bridge returns errors but idea stays approved."""
        import unittest.mock

        client = api_env["client"]
        pid, idea_id = self._setup_project_with_idea(api_env, target_platforms=["twitter"])
        idea_lab = api_env["dashboard"].idea_lab

        with unittest.mock.patch.object(
            idea_lab, "_call_llm_for_enrichment", side_effect=Exception("LLM timeout")
        ):
            resp = client.post(
                f"/api/ideas/ideas/{idea_id}/approve-and-generate",
                json={"project_id": pid},
            )

        data = resp.json()
        assert data["success"] is False
        assert data["generated_platforms"] == []
        assert len(data["errors"]) == 1

        # Idea should still be approved with error metadata
        store = idea_lab.store
        idea = store.get_content_idea_record(idea_id)
        assert idea["status"] == "approved"
        assert idea["metadata_json"]["generation_status"] == "bridge_failed"
