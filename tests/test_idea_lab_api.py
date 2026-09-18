#!/usr/bin/env python3
"""FastAPI TestClient tests for all idea lab routes.

Covers source material CRUD, content idea CRUD, evaluation lifecycle,
search/filter, project isolation, mining placeholder, and project fallback.
"""

import json
import tempfile
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------


def _create_test_app(data_dir: str):
    """Create a FastAPI app with idea lab routes, mirroring main() setup.

    Returns (app, dashboard_instance) so tests can inspect state.
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    from dashboard.unified_dashboard import UnifiedDashboard

    dashboard = UnifiedDashboard(data_dir=data_dir)
    app = FastAPI(title="Test Idea Lab API")
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
            material_type = request.query_params.get("type")
            limit_str = request.query_params.get("limit")
            limit = int(limit_str) if limit_str else None
            items = dashboard_instance.idea_lab.list_source_material(
                project_id=project_id,
                material_type=material_type,
                limit=limit,
            )
            return {
                "success": True,
                "total": len(items),
                "items": [item.to_dict() for item in items],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/ideas/materials/{material_id}")
    async def api_get_source_material(material_id: str):
        try:
            material = dashboard_instance.idea_lab.get_source_material(material_id)
            if material is None:
                return JSONResponse(status_code=404, content={"success": False, "error": "Not found"})
            return {"success": True, "material": material.to_dict()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.put("/api/ideas/materials/{material_id}")
    async def api_update_source_material(material_id: str, request: Request):
        try:
            body = await request.json()
        except Exception:
            return {"success": False, "error": "Invalid JSON body"}
        try:
            allowed_fields = ("title", "note", "tags", "source_attribution", "text_content", "url")
            updates = {k: v for k, v in body.items() if k in allowed_fields}
            material = dashboard_instance.idea_lab.update_source_material(
                material_id, **updates
            )
            return {"success": True, "material": material}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.delete("/api/ideas/materials/{material_id}")
    async def api_delete_source_material(material_id: str):
        try:
            deleted = dashboard_instance.idea_lab.delete_source_material(material_id)
            if not deleted:
                return JSONResponse(status_code=404, content={"success": False, "error": "Not found"})
            return {"success": True, "deleted": True}
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
            content_pillar = request.query_params.get("content_pillar")
            limit_str = request.query_params.get("limit")
            limit = int(limit_str) if limit_str else None
            ideas = dashboard_instance.idea_lab.list_content_ideas(
                project_id=project_id,
                status=status,
                content_pillar=content_pillar,
                limit=limit,
            )
            return {
                "success": True,
                "total": len(ideas),
                "items": [i.to_dict() for i in ideas],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/ideas/ideas/{idea_id}")
    async def api_get_content_idea(idea_id: str):
        try:
            idea = dashboard_instance.idea_lab.get_content_idea(idea_id)
            if idea is None:
                return JSONResponse(status_code=404, content={"success": False, "error": "Not found"})
            return {"success": True, "idea": idea.to_dict()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.put("/api/ideas/ideas/{idea_id}")
    async def api_update_content_idea(idea_id: str, request: Request):
        try:
            body = await request.json()
            updated = dashboard_instance.idea_lab.update_content_idea(
                idea_id, **body
            )
            return {"success": True, "idea": updated}
        except ValueError as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
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

    @app.delete("/api/ideas/ideas/{idea_id}")
    async def api_delete_content_idea(idea_id: str):
        try:
            deleted = dashboard_instance.idea_lab.delete_content_idea(idea_id)
            if not deleted:
                return JSONResponse(status_code=404, content={"success": False, "error": "Not found"})
            return {"success": True, "deleted": True}
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

    # ---- Enrichment routes ----

    @app.post("/api/ideas/materials/{material_id}/enrich")
    async def api_enrich_source_material(material_id: str):
        try:
            result = dashboard_instance.idea_lab.enrich_source_material(material_id)
            return {"success": True, "material": result}
        except ValueError as e:
            return JSONResponse(status_code=404, content={"success": False, "error": str(e)})
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/api/ideas/materials/enrich-batch")
    async def api_enrich_batch(request: Request):
        try:
            body = await request.json()
            project_id = body.get("project_id")
            if not project_id:
                return {"success": False, "error": "project_id is required"}
            counts = dashboard_instance.idea_lab.enrich_all_pending(project_id)
            return {"success": True, "counts": counts}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- Idea generation routes ----

    @app.post("/api/ideas/materials/{material_id}/generate-ideas")
    async def api_generate_ideas_for_material(material_id: str, request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        project_id = body.get("project_id")
        if not project_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "project_id is required in request body"},
            )
        try:
            result = dashboard_instance.idea_lab.generate_ideas_from_material(
                material_id, project_id
            )
            if result.get("error"):
                return {"success": False, "error": result["error"], "ideas": [], "count": 0}
            return {"success": True, **result}
        except ValueError as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
        except Exception as e:
            return {"success": False, "error": f"Idea generation failed: {e}"}

    @app.post("/api/ideas/generate-ideas-batch")
    async def api_generate_ideas_batch(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        project_id = body.get("project_id")
        if not project_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "project_id is required in request body"},
            )
        try:
            counts = dashboard_instance.idea_lab.generate_ideas_for_project(project_id)
            return {"success": True, "counts": counts}
        except Exception as e:
            return {"success": False, "error": f"Batch idea generation failed: {e}"}

    # ---- Mining trigger ----

    @app.post("/api/ideas/mining/trigger")
    async def api_mining_trigger(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}

        project_id = body.get("project_id")
        if not project_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "project_id is required (no current project)"},
            )

        enrichment = dashboard_instance.idea_lab.enrich_all_pending(project_id)
        ideas = dashboard_instance.idea_lab.generate_ideas_for_project(project_id)
        return {"success": True, "enrichment": enrichment, "ideas": ideas}

    return app, dashboard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_env() -> Generator[dict, None, None]:
    """Provide a TestClient wired to a temp-backed dashboard."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app, dashboard = _create_test_app(tmpdir)
        from starlette.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)
        yield {
            "client": client,
            "dashboard": dashboard,
            "data_dir": tmpdir,
        }


# ===========================================================================
# Source Material API Tests
# ===========================================================================


class TestSourceMaterialAPI:
    """Tests for /api/ideas/materials/* endpoints."""

    PROJECT_ID = "test-project-api"

    def _create_material(self, client, **overrides):
        """Helper: POST a source material and return the response JSON."""
        body = {
            "project_id": self.PROJECT_ID,
            "url": "https://example.com",
            "title": "Test Material",
            **overrides,
        }
        resp = client.post("/api/ideas/materials", json=body)
        return resp.json()

    def test_create_material(self, test_env):
        client = test_env["client"]
        resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "url": "https://example.com",
            "title": "Test Material",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["material"]["material_type"] == "url"
        assert data["material"]["title"] == "Test Material"

    def test_create_material_with_url(self, test_env):
        client = test_env["client"]
        resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "url": "https://specific-url.com/article",
        })
        data = resp.json()
        assert data["success"] is True
        assert data["material"]["material_type"] == "url"
        assert data["material"]["url"] == "https://specific-url.com/article"

    def test_create_material_with_text(self, test_env):
        client = test_env["client"]
        resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "text_content": "A long-form article text body",
        })
        data = resp.json()
        assert data["success"] is True
        assert data["material"]["material_type"] == "text"

    def test_list_materials_empty(self, test_env):
        client = test_env["client"]
        resp = client.get("/api/ideas/materials", params={"project_id": self.PROJECT_ID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_materials_with_data(self, test_env):
        client = test_env["client"]
        # Create two materials
        self._create_material(client, title="Mat 1")
        self._create_material(client, title="Mat 2")
        resp = client.get("/api/ideas/materials", params={"project_id": self.PROJECT_ID})
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 2

    def test_get_material(self, test_env):
        client = test_env["client"]
        created = self._create_material(client)
        material_id = created["material"]["material_id"]
        resp = client.get(f"/api/ideas/materials/{material_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["material"]["material_id"] == material_id

    def test_get_material_not_found(self, test_env):
        client = test_env["client"]
        resp = client.get("/api/ideas/materials/nonexistent-id")
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert "Not found" in data["error"]

    def test_update_material(self, test_env):
        client = test_env["client"]
        created = self._create_material(client)
        material_id = created["material"]["material_id"]
        resp = client.put(f"/api/ideas/materials/{material_id}", json={
            "title": "Updated Title",
            "tags": ["updated", "test"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["material"]["title"] == "Updated Title"
        assert "updated" in data["material"]["tags"]

    def test_delete_material(self, test_env):
        client = test_env["client"]
        created = self._create_material(client)
        material_id = created["material"]["material_id"]
        resp = client.delete(f"/api/ideas/materials/{material_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["deleted"] is True

    def test_delete_material_not_found(self, test_env):
        client = test_env["client"]
        resp = client.delete("/api/ideas/materials/nonexistent-id")
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False

    def test_create_material_missing_fields(self, test_env):
        client = test_env["client"]
        resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            # No url, text_content, or note
        })
        data = resp.json()
        assert data["success"] is False
        assert "required" in data["error"].lower()


# ===========================================================================
# Content Idea API Tests
# ===========================================================================


class TestContentIdeaAPI:
    """Tests for /api/ideas/ideas/* endpoints."""

    PROJECT_ID = "test-project-ideas-api"

    def _create_idea(self, client, **overrides):
        """Helper: POST a content idea and return the response JSON."""
        body = {
            "project_id": self.PROJECT_ID,
            "title": "Test Idea",
            "hook_angle": "Test hook",
            "content_pillar": "growth",
            **overrides,
        }
        resp = client.post("/api/ideas/ideas", json=body)
        return resp.json()

    def test_create_idea(self, test_env):
        client = test_env["client"]
        resp = client.post("/api/ideas/ideas", json={
            "project_id": self.PROJECT_ID,
            "title": "My Great Idea",
            "hook_angle": "Counterintuitive take",
            "content_pillar": "thought-leadership",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["idea"]["title"] == "My Great Idea"
        assert data["idea"]["status"] == "draft"

    def test_list_ideas_empty(self, test_env):
        client = test_env["client"]
        resp = client.get("/api/ideas/ideas", params={"project_id": self.PROJECT_ID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_ideas_with_filters(self, test_env):
        client = test_env["client"]
        # Create ideas with different pillars
        self._create_idea(client, content_pillar="growth")
        self._create_idea(client, content_pillar="engagement")

        # Filter by pillar
        resp = client.get("/api/ideas/ideas", params={
            "project_id": self.PROJECT_ID,
            "content_pillar": "growth",
        })
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 1

        # Filter by status
        resp = client.get("/api/ideas/ideas", params={
            "project_id": self.PROJECT_ID,
            "status": "draft",
        })
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 2

    def test_get_idea(self, test_env):
        client = test_env["client"]
        created = self._create_idea(client)
        idea_id = created["idea"]["idea_id"]
        resp = client.get(f"/api/ideas/ideas/{idea_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["idea"]["idea_id"] == idea_id

    def test_get_idea_not_found(self, test_env):
        client = test_env["client"]
        resp = client.get("/api/ideas/ideas/nonexistent-id")
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert "Not found" in data["error"]

    def test_update_idea(self, test_env):
        client = test_env["client"]
        created = self._create_idea(client)
        idea_id = created["idea"]["idea_id"]
        resp = client.put(f"/api/ideas/ideas/{idea_id}", json={
            "title": "Updated Title",
            "hook_angle": "New hook",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["idea"]["title"] == "Updated Title"
        assert data["idea"]["hook_angle"] == "New hook"

    def test_update_idea_status_blocked(self, test_env):
        """PUT with status in body returns 400 (must use evaluate endpoint)."""
        client = test_env["client"]
        created = self._create_idea(client)
        idea_id = created["idea"]["idea_id"]
        resp = client.put(f"/api/ideas/ideas/{idea_id}", json={
            "status": "approved",
        })
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "evaluate" in data["error"].lower()

    def test_evaluate_idea_draft_to_approved(self, test_env):
        client = test_env["client"]
        created = self._create_idea(client)
        idea_id = created["idea"]["idea_id"]
        resp = client.post(f"/api/ideas/ideas/{idea_id}/evaluate", json={
            "status": "approved",
            "evaluation_notes": "Looks great",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["idea"]["status"] == "approved"

    def test_evaluate_idea_invalid_transition(self, test_env):
        """approved -> approved is not a valid transition, returns 400."""
        client = test_env["client"]
        created = self._create_idea(client)
        idea_id = created["idea"]["idea_id"]
        # Approve it first
        client.post(f"/api/ideas/ideas/{idea_id}/evaluate", json={"status": "approved"})
        # Try invalid transition: approved -> approved
        resp = client.post(f"/api/ideas/ideas/{idea_id}/evaluate", json={
            "status": "approved",
        })
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "Invalid" in data["error"]

    def test_delete_idea(self, test_env):
        client = test_env["client"]
        created = self._create_idea(client)
        idea_id = created["idea"]["idea_id"]
        resp = client.delete(f"/api/ideas/ideas/{idea_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["deleted"] is True
        # Verify gone
        resp2 = client.get(f"/api/ideas/ideas/{idea_id}")
        assert resp2.status_code == 404

    def test_project_isolation(self, test_env):
        """Create an idea in project A, verify invisible from project B."""
        client = test_env["client"]
        # Create in project A
        resp_a = client.post("/api/ideas/ideas", json={
            "project_id": "project-alpha",
            "title": "Alpha Idea",
        })
        assert resp_a.json()["success"] is True
        # List in project B
        resp_b = client.get("/api/ideas/ideas", params={"project_id": "project-beta"})
        data_b = resp_b.json()
        assert data_b["success"] is True
        assert data_b["total"] == 0


# ===========================================================================
# Mining Placeholder
# ===========================================================================


class TestMiningTrigger:
    """Tests for /api/ideas/mining/trigger endpoint."""

    PROJECT_ID = "mining-project"

    def test_mining_trigger_requires_project_id(self, test_env):
        """Mining trigger returns 400 when no project_id provided and no current project."""
        client = test_env["client"]
        resp = client.post("/api/ideas/mining/trigger", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False

    def test_mining_trigger_returns_enrichment_and_ideas_counts(self, test_env):
        """Mining trigger returns structured enrichment + ideas counts."""
        client = test_env["client"]
        # Create some source materials (un-enriched)
        for i in range(3):
            client.post("/api/ideas/materials", json={
                "project_id": self.PROJECT_ID,
                "url": f"https://example.com/article-{i}",
                "title": f"Test Article {i}",
            })

        resp = client.post("/api/ideas/mining/trigger", json={
            "project_id": self.PROJECT_ID,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "enrichment" in data
        assert "ideas" in data
        e = data["enrichment"]
        i = data["ideas"]
        assert e["total"] == 3
        assert "enriched" in e
        assert "partial" in e
        assert "failed" in e
        assert "skipped" in e
        assert "generated" in i
        assert "skipped" in i
        assert "errors" in i
        assert i["total_materials"] == 3


# ===========================================================================
# Project Fallback
# ===========================================================================


class TestProjectFallback:
    """Tests for project_id fallback behavior when omitted from request."""

    PROJECT_ID = "fallback-project"

    def test_material_create_uses_current_project_when_project_id_omitted(self, test_env):
        """When project_id is omitted from body, current_project_id is used."""
        client = test_env["client"]
        dashboard = test_env["dashboard"]
        # Create a project and set it as current
        dashboard.project_manager.create_project(name="Fallback Project")
        # list projects to get the ID
        projects = dashboard.project_manager.list_projects()
        proj = projects[0]
        dashboard.project_manager.set_current_project(proj.project_id)
        # get_current_project() will now return the project — no current_project_id attribute needed

        resp = client.post("/api/ideas/materials", json={
            # project_id intentionally omitted — should fall back to current project
            "url": "https://example.com/fallback-test",
            "title": "Fallback Test",
        })
        data = resp.json()
        assert data["success"] is True
        assert data["material"]["project_id"] == proj.project_id


# ===========================================================================
# Enrichment API Tests
# ===========================================================================


class TestEnrichmentAPI:
    """Tests for /api/ideas/materials/{id}/enrich and enrich-batch endpoints."""

    PROJECT_ID = "enrich-test-project"

    def _create_url_material(self, client):
        resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "url": "https://example.com/test-article",
            "title": "Test URL Material",
        })
        return resp.json()

    def test_enrich_endpoint_returns_enriched_material(self, test_env):
        """POST /api/ideas/materials/{id}/enrich enriches and returns the material."""
        import unittest.mock
        client = test_env["client"]
        created = self._create_url_material(client)
        mid = created["material"]["material_id"]

        llm_count = 0
        def mock_llm(**kwargs):
            nonlocal llm_count
            llm_count += 1
            if llm_count == 1:
                return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": '["Point A", "Point B"]'})()})()]})()
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": '["tag-a", "tag-b"]'})()})()]})()

        with unittest.mock.patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            with unittest.mock.patch("services.idea_lab.litellm.completion", side_effect=mock_llm):
                with unittest.mock.patch("services.idea_lab.httpx.Client") as MockClient:
                    cm = MockClient.return_value
                    ci = cm.__enter__.return_value
                    ci.post.return_value = type("R", (), {
                        "status_code": 200,
                        "json": lambda self: {"result": {"content": [{"type": "text", "text": "Article content"}]}},
                        "raise_for_status": lambda self: None,
                    })()
                    resp = client.post(f"/api/ideas/materials/{mid}/enrich")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["material"]["metadata_json"]["enrichment_status"] == "enriched"

    def test_enrich_endpoint_not_found(self, test_env):
        """POST /api/ideas/materials/{bad-id}/enrich returns 404."""
        client = test_env["client"]
        resp = client.post("/api/ideas/materials/nonexistent-id/enrich")
        assert resp.status_code == 404

    def test_enrich_batch_endpoint(self, test_env):
        """POST /api/ideas/materials/enrich-batch enriches all pending materials."""
        import unittest.mock
        client = test_env["client"]
        # Create 2 note materials
        client.post("/api/ideas/materials", json={"project_id": self.PROJECT_ID, "note": "Note 1"})
        client.post("/api/ideas/materials", json={"project_id": self.PROJECT_ID, "note": "Note 2"})

        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": '["tag"]'})()})()]})()):
            resp = client.post("/api/ideas/materials/enrich-batch", json={"project_id": self.PROJECT_ID})

        data = resp.json()
        assert data["success"] is True
        assert data["counts"]["total"] == 2
        assert data["counts"]["enriched"] == 2

    def test_enrich_batch_missing_project_id(self, test_env):
        """POST /api/ideas/materials/enrich-batch without project_id returns error."""
        client = test_env["client"]
        resp = client.post("/api/ideas/materials/enrich-batch", json={})
        data = resp.json()
        assert data["success"] is False
        assert "project_id" in data["error"]

    def test_get_material_shows_enrichment_state(self, test_env):
        """GET /api/ideas/materials/{id} returns full enrichment state after enrichment."""
        import unittest.mock
        client = test_env["client"]
        created = self._create_url_material(client)
        mid = created["material"]["material_id"]

        with unittest.mock.patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": '["kp1"]'})()})()]})()):
                with unittest.mock.patch("services.idea_lab.httpx.Client") as MockClient:
                    cm = MockClient.return_value
                    ci = cm.__enter__.return_value
                    ci.post.return_value = type("R", (), {
                        "status_code": 200,
                        "json": lambda self: {"result": {"content": [{"type": "text", "text": "content"}]}},
                        "raise_for_status": lambda self: None,
                    })()
                    client.post(f"/api/ideas/materials/{mid}/enrich")

        # Now GET the material and verify enrichment metadata
        resp = client.get(f"/api/ideas/materials/{mid}")
        data = resp.json()
        assert data["success"] is True
        meta = data["material"]["metadata_json"]
        assert "enrichment_status" in meta
        assert "enriched_at" in meta


# ===========================================================================
# Idea Generation API Tests
# ===========================================================================


def _fake_llm_ideas_response():
    """Return a mock litellm response with 3 content ideas as JSON."""
    ideas_json = json.dumps([
        {
            "title": "The AI Marketing Shift Nobody Saw Coming",
            "hook_angle": "Contrarian take on AI automation",
            "target_platforms": ["twitter", "linkedin"],
            "content_pillar": "thought-leadership",
            "rationale": "Timely counter-narrative to AI hype cycle",
            "suggested_format": "thread",
        },
        {
            "title": "Why Your Content Strategy Needs Radical Simplification",
            "hook_angle": "Challenge complexity assumption",
            "target_platforms": ["linkedin"],
            "content_pillar": "educational",
            "rationale": "Audience responds to simplicity messaging",
            "suggested_format": "single-post",
        },
        {
            "title": "Data-Driven Growth Without the Overwhelm",
            "hook_angle": "Practical step-by-step approach",
            "target_platforms": ["twitter"],
            "content_pillar": "growth",
            "rationale": "Actionable content performs well",
            "suggested_format": "carousel",
        },
    ])
    return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": ideas_json})()})()]})()


class TestIdeaGenerationAPI:
    """Tests for POST /api/ideas/materials/{id}/generate-ideas and /api/ideas/generate-ideas-batch."""

    PROJECT_ID = "idea-gen-project"

    def _create_enriched_material(self, client):
        """Helper: create a source material for idea generation."""
        resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "text_content": "A fascinating article about AI trends in marketing and content strategy.",
            "title": "AI Marketing Trends",
        })
        data = resp.json()
        material_id = data["material"]["material_id"]
        return material_id

    def test_generate_ideas_success(self, test_env):
        """POST generate-ideas returns created ideas for enriched material."""
        import unittest.mock

        client = test_env["client"]
        dashboard = test_env["dashboard"]

        # Create material
        mat_resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "text_content": "Great article about AI marketing trends.",
            "title": "AI Trends",
        })
        material_id = mat_resp.json()["material"]["material_id"]

        # Manually set enrichment status to "enriched"
        store = dashboard.idea_lab.store
        rec = store.get_source_material_record(material_id)
        rec["metadata_json"] = {
            "enrichment_status": "enriched",
            "key_points": ["AI is transforming marketing", "Content needs authenticity"],
            "auto_tags": ["ai", "marketing"],
        }
        store.save_source_material_record(rec)

        # Call generate-ideas with mocked LLM
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_ideas_response()):
            resp = client.post(f"/api/ideas/materials/{material_id}/generate-ideas", json={
                "project_id": self.PROJECT_ID,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 3
        assert len(data["ideas"]) == 3
        assert data["ideas"][0]["title"] == "The AI Marketing Shift Nobody Saw Coming"
        assert data["ideas"][0]["hook_angle"] == "Contrarian take on AI automation"
        assert data["ideas"][0]["target_platforms"] == ["twitter", "linkedin"]
        assert data["ideas"][0]["status"] == "draft"

    def test_generate_ideas_missing_project_id(self, test_env):
        """POST generate-ideas without project_id returns 400."""
        client = test_env["client"]
        resp = client.post("/api/ideas/materials/some-id/generate-ideas", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "project_id" in data["error"]

    def test_generate_ideas_material_not_found(self, test_env):
        """POST generate-ideas for nonexistent material returns 400 ValueError."""
        client = test_env["client"]
        resp = client.post("/api/ideas/materials/nonexistent-sm-id/generate-ideas", json={
            "project_id": self.PROJECT_ID,
        })
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "not found" in data["error"]

    def test_generate_ideas_unenriched_material(self, test_env):
        """POST generate-ideas for un-enriched material returns 400 ValueError."""
        client = test_env["client"]

        # Create material (not enriched)
        mat_resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "note": "Just a raw note",
        })
        material_id = mat_resp.json()["material"]["material_id"]

        resp = client.post(f"/api/ideas/materials/{material_id}/generate-ideas", json={
            "project_id": self.PROJECT_ID,
        })
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "not enriched" in data["error"].lower()

    def test_generate_ideas_idempotent(self, test_env):
        """Calling generate-ideas twice on same material returns existing ideas."""
        import unittest.mock

        client = test_env["client"]
        dashboard = test_env["dashboard"]

        # Create and enrich material
        mat_resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "text_content": "Content for idempotency test.",
            "title": "Idempotency Test",
        })
        material_id = mat_resp.json()["material"]["material_id"]

        store = dashboard.idea_lab.store
        rec = store.get_source_material_record(material_id)
        rec["metadata_json"] = {"enrichment_status": "enriched", "key_points": ["test point"]}
        store.save_source_material_record(rec)

        # First call
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_ideas_response()):
            resp1 = client.post(f"/api/ideas/materials/{material_id}/generate-ideas", json={
                "project_id": self.PROJECT_ID,
            })
        assert resp1.json()["success"] is True
        assert resp1.json()["count"] == 3

        # Second call should return existing ideas (skipped)
        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_ideas_response()):
            resp2 = client.post(f"/api/ideas/materials/{material_id}/generate-ideas", json={
                "project_id": self.PROJECT_ID,
            })
        data2 = resp2.json()
        assert data2["success"] is True
        assert data2.get("skipped") is True
        assert data2["count"] == 3

    def test_generate_ideas_batch(self, test_env):
        """POST generate-ideas-batch processes all enriched materials."""
        import unittest.mock

        client = test_env["client"]
        dashboard = test_env["dashboard"]
        store = dashboard.idea_lab.store

        # Create 2 enriched materials and 1 un-enriched
        for i in range(2):
            mat_resp = client.post("/api/ideas/materials", json={
                "project_id": self.PROJECT_ID,
                "text_content": f"Enriched content {i}",
                "title": f"Batch Test {i}",
            })
            mid = mat_resp.json()["material"]["material_id"]
            rec = store.get_source_material_record(mid)
            rec["metadata_json"] = {"enrichment_status": "enriched", "key_points": [f"point {i}"]}
            store.save_source_material_record(rec)

        # Un-enriched material
        client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "note": "Raw note, not enriched",
        })

        with unittest.mock.patch("services.idea_lab.litellm.completion", return_value=_fake_llm_ideas_response()):
            resp = client.post("/api/ideas/generate-ideas-batch", json={
                "project_id": self.PROJECT_ID,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        counts = data["counts"]
        assert counts["total_materials"] == 3
        assert counts["generated"] == 2
        assert counts["skipped"] == 1  # un-enriched material

    def test_generate_ideas_batch_missing_project_id(self, test_env):
        """POST generate-ideas-batch without project_id returns 400."""
        client = test_env["client"]
        resp = client.post("/api/ideas/generate-ideas-batch", json={})
        assert resp.status_code == 400
        assert "project_id" in resp.json()["error"]

    def test_generate_ideas_llm_failure(self, test_env):
        """POST generate-ideas with LLM failure returns error, not exception."""
        import unittest.mock

        client = test_env["client"]
        dashboard = test_env["dashboard"]

        mat_resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "text_content": "Content for LLM failure test.",
            "title": "LLM Fail Test",
        })
        material_id = mat_resp.json()["material"]["material_id"]

        store = dashboard.idea_lab.store
        rec = store.get_source_material_record(material_id)
        rec["metadata_json"] = {"enrichment_status": "enriched", "key_points": ["test"]}
        store.save_source_material_record(rec)

        with unittest.mock.patch("services.idea_lab.litellm.completion", side_effect=Exception("LLM timeout")):
            resp = client.post(f"/api/ideas/materials/{material_id}/generate-ideas", json={
                "project_id": self.PROJECT_ID,
            })

        data = resp.json()
        assert data["success"] is False
        assert "LLM" in data["error"] or "failed" in data["error"].lower()


# ===========================================================================
# Approve-and-Generate Bridge Tests
# ===========================================================================


class TestApproveAndGenerateAPI:
    """Tests for the idea-to-content bridge: approve_and_generate_content
    service method and POST /api/ideas/ideas/{idea_id}/approve-and-generate."""

    PROJECT_ID = "bridge-test-project"

    def _create_idea(self, client, **overrides):
        """Helper: POST a content idea and return the response JSON."""
        body = {
            "project_id": self.PROJECT_ID,
            "title": "Bridge Test Idea",
            "hook_angle": "Test hook angle",
            "content_pillar": "growth",
            **overrides,
        }
        resp = client.post("/api/ideas/ideas", json=body)
        return resp.json()

    @staticmethod
    def _mock_llm_content(idea_lab_instance):
        """Return a patcher that makes _call_llm_for_enrichment return deterministic content."""
        import unittest.mock

        call_count = {"n": 0}

        def fake_llm(prompt, max_tokens=1000):
            call_count["n"] += 1
            # Return platform-specific content based on prompt text
            if "TWITTER" in prompt:
                return "Great tweet about growth strategies! #marketing"
            elif "LINKEDIN" in prompt:
                return "LinkedIn post about growth strategies with actionable insights."
            elif "NOSTR" in prompt:
                return "Nostr note about growth strategies."
            return f"Generic content {call_count['n']}"

        return unittest.mock.patch.object(
            idea_lab_instance, "_call_llm_for_enrichment", side_effect=fake_llm
        )

    # ------------------------------------------------------------------
    # Service-level tests (via idea_lab directly)
    # ------------------------------------------------------------------

    def test_happy_path_multi_platform(self, test_env):
        """Approve + generate for twitter+linkedin creates 2 review records."""
        client = test_env["client"]
        dashboard = test_env["dashboard"]
        idea_lab = dashboard.idea_lab
        store = idea_lab.store

        # Create idea with two target platforms
        idea_data = self._create_idea(client, target_platforms=["twitter", "linkedin"])
        idea_id = idea_data["idea"]["idea_id"]

        # Wire a real FeedbackManager to the same store
        from feedback import FeedbackManager

        fm = FeedbackManager(data_dir=test_env["data_dir"])

        with self._mock_llm_content(idea_lab):
            result = idea_lab.approve_and_generate_content(
                idea_id=idea_id,
                project_id=self.PROJECT_ID,
                feedback_manager=fm,
            )

        # Result shape
        assert result["success"] is True
        assert result["idea_id"] == idea_id
        assert set(result["generated_platforms"]) == {"twitter", "linkedin"}
        assert len(result["review_ids"]) == 2
        assert result["errors"] == []

        # Idea status should be approved
        updated_idea = store.get_content_idea_record(idea_id)
        assert updated_idea["status"] == "approved"

        # Metadata should record generation
        meta = updated_idea.get("metadata_json", {})
        assert meta.get("generation_status") == "content_generated"
        assert meta.get("review_ids") == result["review_ids"]
        assert "generated_at" in meta

        # Review records should exist with correct platform/publish_channel
        for rid in result["review_ids"]:
            rec = store.get_review_record(rid)
            assert rec is not None
            assert rec["status"] == "pending_review"
            assert rec["post_data"]["idea_id"] == idea_id
            assert rec["post_data"]["project_id"] == self.PROJECT_ID
            assert rec["post_data"]["publish_channel"] in {"twitter", "linkedin"}
            assert rec["post_data"]["platform"] in {"twitter", "linkedin"}

    def test_empty_target_platforms_defaults(self, test_env):
        """Idea with no target_platforms defaults to twitter+linkedin."""
        client = test_env["client"]
        dashboard = test_env["dashboard"]
        idea_lab = dashboard.idea_lab

        # Create idea with no target_platforms
        idea_data = self._create_idea(client)
        idea_id = idea_data["idea"]["idea_id"]

        from feedback import FeedbackManager

        fm = FeedbackManager(data_dir=test_env["data_dir"])

        with self._mock_llm_content(idea_lab):
            result = idea_lab.approve_and_generate_content(
                idea_id=idea_id,
                project_id=self.PROJECT_ID,
                feedback_manager=fm,
            )

        assert result["success"] is True
        assert set(result["generated_platforms"]) == {"twitter", "linkedin"}

    def test_idea_not_found_raises_valueerror(self, test_env):
        """Non-existent idea_id raises ValueError."""
        dashboard = test_env["dashboard"]
        idea_lab = dashboard.idea_lab
        from feedback import FeedbackManager

        fm = FeedbackManager(data_dir=test_env["data_dir"])

        with pytest.raises(ValueError, match="not found"):
            idea_lab.approve_and_generate_content(
                idea_id="nonexistent-id",
                project_id=self.PROJECT_ID,
                feedback_manager=fm,
            )

    def test_llm_failure_records_error(self, test_env):
        """When LLM fails for all platforms, idea stays approved with bridge_error metadata."""
        import unittest.mock

        client = test_env["client"]
        dashboard = test_env["dashboard"]
        idea_lab = dashboard.idea_lab
        store = idea_lab.store

        idea_data = self._create_idea(client, target_platforms=["twitter"])
        idea_id = idea_data["idea"]["idea_id"]

        from feedback import FeedbackManager

        fm = FeedbackManager(data_dir=test_env["data_dir"])

        with unittest.mock.patch.object(
            idea_lab, "_call_llm_for_enrichment", side_effect=Exception("LLM timeout")
        ):
            result = idea_lab.approve_and_generate_content(
                idea_id=idea_id,
                project_id=self.PROJECT_ID,
                feedback_manager=fm,
            )

        # Bridge failed — result.success is False
        assert result["success"] is False
        assert result["generated_platforms"] == []
        assert result["review_ids"] == []
        assert len(result["errors"]) == 1

        # Idea stays approved
        updated_idea = store.get_content_idea_record(idea_id)
        assert updated_idea["status"] == "approved"

        # Metadata records the error
        meta = updated_idea.get("metadata_json", {})
        assert meta.get("generation_status") == "bridge_failed"
        assert "bridge_error" in meta
        assert "twitter" in meta["bridge_error"]
        assert "bridge_error_at" in meta

    def test_idempotent_already_generated(self, test_env):
        """Calling twice on already-generated idea succeeds without errors."""
        client = test_env["client"]
        dashboard = test_env["dashboard"]
        idea_lab = dashboard.idea_lab
        store = idea_lab.store

        idea_data = self._create_idea(client, target_platforms=["twitter"])
        idea_id = idea_data["idea"]["idea_id"]

        from feedback import FeedbackManager

        fm = FeedbackManager(data_dir=test_env["data_dir"])

        # First call — generate
        with self._mock_llm_content(idea_lab):
            result1 = idea_lab.approve_and_generate_content(
                idea_id=idea_id,
                project_id=self.PROJECT_ID,
                feedback_manager=fm,
            )

        assert result1["success"] is True

        # Verify idea now has generation_status
        idea = store.get_content_idea_record(idea_id)
        assert idea["metadata_json"]["generation_status"] == "content_generated"

        # Second call — already approved and generated, should still succeed
        # (Current implementation regenerates; this test documents that behavior)
        with self._mock_llm_content(idea_lab):
            result2 = idea_lab.approve_and_generate_content(
                idea_id=idea_id,
                project_id=self.PROJECT_ID,
                feedback_manager=fm,
            )

        # Currently regenerates (no idempotency gate). Verify it still succeeds.
        assert result2["success"] is True
        assert len(result2["review_ids"]) >= 1

    def test_source_material_key_points_in_prompt(self, test_env):
        """Key points from linked source material appear in the LLM prompt."""
        import unittest.mock

        client = test_env["client"]
        dashboard = test_env["dashboard"]
        idea_lab = dashboard.idea_lab
        store = idea_lab.store

        # Create source material with key points
        mat_resp = client.post("/api/ideas/materials", json={
            "project_id": self.PROJECT_ID,
            "text_content": "Growth strategies article",
            "title": "Growth Strategies",
        })
        material_id = mat_resp.json()["material"]["material_id"]
        rec = store.get_source_material_record(material_id)
        rec["metadata_json"] = {
            "enrichment_status": "enriched",
            "key_points": ["Test key point about growth", "Second key point"],
        }
        store.save_source_material_record(rec)

        # Create idea linked to the material
        idea_data = self._create_idea(
            client,
            target_platforms=["twitter"],
            source_material_ids=[material_id],
        )
        idea_id = idea_data["idea"]["idea_id"]

        from feedback import FeedbackManager

        fm = FeedbackManager(data_dir=test_env["data_dir"])

        # Capture the prompt sent to LLM
        captured_prompt = {}

        def capture_llm(prompt, max_tokens=1000):
            captured_prompt["text"] = prompt
            return "Generated tweet content"

        with unittest.mock.patch.object(
            idea_lab, "_call_llm_for_enrichment", side_effect=capture_llm
        ):
            idea_lab.approve_and_generate_content(
                idea_id=idea_id,
                project_id=self.PROJECT_ID,
                feedback_manager=fm,
            )

        # Key points should appear in the prompt
        assert "Test key point about growth" in captured_prompt["text"]
        assert "Second key point" in captured_prompt["text"]

    # ------------------------------------------------------------------
    # API endpoint tests
    # ------------------------------------------------------------------

    def test_api_approve_and_generate_success(self, test_env):
        """POST /api/ideas/ideas/{id}/approve-and-generate returns 200 with review_ids."""
        client = test_env["client"]
        dashboard = test_env["dashboard"]
        idea_lab = dashboard.idea_lab

        idea_data = self._create_idea(client, target_platforms=["twitter", "linkedin"])
        idea_id = idea_data["idea"]["idea_id"]

        with self._mock_llm_content(idea_lab):
            resp = client.post(
                f"/api/ideas/ideas/{idea_id}/approve-and-generate",
                json={"project_id": self.PROJECT_ID},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["idea_id"] == idea_id
        assert set(data["generated_platforms"]) == {"twitter", "linkedin"}
        assert len(data["review_ids"]) == 2
        assert data["errors"] == []

    def test_api_missing_project_id(self, test_env):
        """POST approve-and-generate without project_id returns 400."""
        client = test_env["client"]

        idea_data = self._create_idea(client)
        idea_id = idea_data["idea"]["idea_id"]

        resp = client.post(
            f"/api/ideas/ideas/{idea_id}/approve-and-generate",
            json={},
        )

        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "project_id" in data["error"]

    def test_api_idea_not_found(self, test_env):
        """POST approve-and-generate with invalid idea_id returns 400."""
        client = test_env["client"]
        resp = client.post(
            "/api/ideas/ideas/nonexistent-id/approve-and-generate",
            json={"project_id": self.PROJECT_ID},
        )

        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    def test_api_llm_failure_returns_error(self, test_env):
        """POST approve-and-generate with LLM failure returns error in response."""
        import unittest.mock

        client = test_env["client"]
        dashboard = test_env["dashboard"]
        idea_lab = dashboard.idea_lab

        idea_data = self._create_idea(client, target_platforms=["twitter"])
        idea_id = idea_data["idea"]["idea_id"]

        with unittest.mock.patch.object(
            idea_lab, "_call_llm_for_enrichment", side_effect=Exception("LLM timeout")
        ):
            resp = client.post(
                f"/api/ideas/ideas/{idea_id}/approve-and-generate",
                json={"project_id": self.PROJECT_ID},
            )

        # Should still return 200 (caught internally) with success=False
        data = resp.json()
        assert data["success"] is False
        assert len(data["errors"]) == 1
