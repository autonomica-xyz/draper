"""Idea Lab routes extracted from ``unified_dashboard.py:main()``.

Each route body is a verbatim copy of the corresponding inline closure with
the standard mechanical substitutions applied across the plan:

* ``@app.<method>`` decorators become ``@router.<method>``.
* ``dashboard_instance.<collaborator>`` becomes ``Depends(get_<collaborator>)``
  (or ``container.<collaborator>`` via ``Depends(get_container)`` for
  one-off accesses such as ``feedback_manager``).

Threat T-03-03-05: editor-role checks via
``_resource_project_id("material"|"idea", id)`` +
``_require_project_access`` are preserved verbatim so scoped tokens
cannot mutate another project's materials or ideas.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from dashboard.dependencies import (
    get_container,
    get_idea_lab,
)
from dashboard.middleware.auth import (
    _default_project_id_for_request,
    _require_project_access,
)

router = APIRouter()


@router.post("/api/ideas/materials")
async def api_create_source_material(
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    try:
        project_id = body.get("project_id")
        if not project_id:
            project_id = _default_project_id_for_request(request)
        if not project_id:
            return {"success": False, "error": "project_id is required"}
        _require_project_access(request, project_id, "editor")

        material = idea_lab.add_source_material(
            project_id=project_id,
            url=body.get("url"),
            text_content=body.get("text_content"),
            note=body.get("note"),
            title=body.get("title"),
            tags=body.get("tags"),
        )

        try:
            material_id = (
                material.get("material_id")
                if isinstance(material, dict)
                else getattr(material, "material_id", None)
            )
            if material_id:
                material = idea_lab.enrich_source_material(material_id)
        except Exception:
            pass

        return {"success": True, "material": material}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"Create source material failed: {e}")
        return {"success": False, "error": "Failed to create source material"}


@router.get("/api/ideas/materials")
async def api_list_source_materials(
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        project_id = request.query_params.get("project_id")
        if not project_id:
            project_id = _default_project_id_for_request(request)
        if not project_id:
            return {"success": False, "error": "project_id is required"}
        _require_project_access(request, project_id, "viewer")

        material_type = request.query_params.get("type")
        limit_str = request.query_params.get("limit")
        limit = int(limit_str) if limit_str else None

        items = idea_lab.list_source_material(
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
        print(f"List source materials failed: {e}")
        return {"success": False, "error": "Failed to list source materials"}


@router.get("/api/ideas/materials/{material_id}")
async def api_get_source_material(
    material_id: str,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        material = idea_lab.get_source_material(material_id)
        if material is None:
            return {"success": False, "error": "Not found"}
        return {"success": True, "material": material.to_dict()}
    except Exception as e:
        print(f"Get source material failed for {material_id}: {e}")
        return {"success": False, "error": "Failed to load source material"}


@router.put("/api/ideas/materials/{material_id}")
async def api_update_source_material(
    material_id: str,
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    try:
        allowed_fields = (
            "title",
            "note",
            "tags",
            "source_attribution",
            "text_content",
            "url",
        )
        updates = {k: v for k, v in body.items() if k in allowed_fields}
        material = idea_lab.update_source_material(
            material_id, **updates
        )
        return {"success": True, "material": material}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"Update source material failed for {material_id}: {e}")
        return {"success": False, "error": "Failed to update source material"}


@router.delete("/api/ideas/materials/{material_id}")
async def api_delete_source_material(
    material_id: str,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        deleted = idea_lab.delete_source_material(material_id)
        if not deleted:
            return {"success": False, "error": "Not found"}
        return {"success": True, "deleted": True}
    except Exception as e:
        print(f"Delete source material failed for {material_id}: {e}")
        return {"success": False, "error": "Failed to delete source material"}


@router.post("/api/ideas/materials/{material_id}/enrich")
async def api_enrich_source_material(
    material_id: str,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        enriched = idea_lab.enrich_source_material(material_id)
        return {"success": True, "material": enriched}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"Source material enrichment failed for {material_id}: {e}")
        return {"success": False, "error": "Enrichment failed"}


@router.post("/api/ideas/materials/enrich-batch")
async def api_enrich_batch(
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        body = await request.json()
    except Exception:
        body = {}

    project_id = body.get("project_id")
    if not project_id:
        project_id = _default_project_id_for_request(request)
    if not project_id:
        return {"success": False, "error": "project_id is required"}
    _require_project_access(request, project_id, "editor")

    counts = idea_lab.enrich_all_pending(project_id)
    return {"success": True, "counts": counts}


@router.post("/api/ideas/materials/{material_id}/generate-ideas")
async def api_generate_ideas_for_material(
    material_id: str,
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
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
    _require_project_access(request, project_id, "editor")

    try:
        result = idea_lab.generate_ideas_from_material(
            material_id, project_id
        )
        if result.get("error"):
            return {"success": False, "error": result["error"], "ideas": [], "count": 0}
        return {"success": True, **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    except Exception as e:
        print(f"Idea generation failed for material {material_id}: {e}")
        return {"success": False, "error": "Idea generation failed"}


@router.post("/api/ideas/generate-ideas-batch")
async def api_generate_ideas_batch(
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
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
    _require_project_access(request, project_id, "editor")

    try:
        counts = idea_lab.generate_ideas_for_project(project_id)
        return {"success": True, "counts": counts}
    except Exception as e:
        print(f"Batch idea generation failed for {project_id}: {e}")
        return {"success": False, "error": "Batch idea generation failed"}


@router.post("/api/ideas/ideas")
async def api_create_content_idea(
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        body = await request.json()
        project_id = body.get("project_id")
        if not project_id:
            project_id = _default_project_id_for_request(request)
        if not project_id:
            return {"success": False, "error": "project_id is required"}
        _require_project_access(request, project_id, "editor")
        idea = idea_lab.add_content_idea(
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
        print(f"Create content idea failed: {e}")
        return {"success": False, "error": "Failed to create content idea"}


@router.get("/api/ideas/ideas")
async def api_list_content_ideas(
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        project_id = request.query_params.get("project_id")
        if not project_id:
            project_id = _default_project_id_for_request(request)
        if not project_id:
            return {"success": False, "error": "project_id is required"}
        _require_project_access(request, project_id, "viewer")
        status = request.query_params.get("status")
        content_pillar = request.query_params.get("content_pillar")
        limit_str = request.query_params.get("limit")
        limit = int(limit_str) if limit_str else None

        ideas = idea_lab.list_content_ideas(
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
        print(f"List content ideas failed: {e}")
        return {"success": False, "error": "Failed to list content ideas"}


@router.get("/api/ideas/ideas/{idea_id}")
async def api_get_content_idea(
    idea_id: str,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        idea = idea_lab.get_content_idea(idea_id)
        if idea is None:
            return JSONResponse(
                status_code=404, content={"success": False, "error": "Not found"}
            )
        return {"success": True, "idea": idea.to_dict()}
    except Exception as e:
        print(f"Get content idea failed for {idea_id}: {e}")
        return {"success": False, "error": "Failed to load content idea"}


@router.put("/api/ideas/ideas/{idea_id}")
async def api_update_content_idea(
    idea_id: str,
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        body = await request.json()
        updated = idea_lab.update_content_idea(idea_id, **body)
        return {"success": True, "idea": updated}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    except Exception as e:
        print(f"Update content idea failed for {idea_id}: {e}")
        return {"success": False, "error": "Failed to update content idea"}


@router.post("/api/ideas/ideas/{idea_id}/evaluate")
async def api_evaluate_content_idea(
    idea_id: str,
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        body = await request.json()
        updated = idea_lab.evaluate_content_idea(
            idea_id=idea_id,
            new_status=body.get("status", ""),
            evaluation_notes=body.get("evaluation_notes"),
        )
        return {"success": True, "idea": updated}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    except Exception as e:
        print(f"Evaluate content idea failed for {idea_id}: {e}")
        return {"success": False, "error": "Failed to evaluate content idea"}


@router.post("/api/ideas/ideas/{idea_id}/approve-and-generate")
async def api_approve_and_generate(
    idea_id: str,
    request: Request,
    container: Any = Depends(get_container),
):
    try:
        body = await request.json()
        project_id = body.get("project_id")
        if not project_id:
            project_id = _default_project_id_for_request(request)
        if not project_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "project_id is required"},
            )
        _require_project_access(request, project_id, "editor")
        result = container.idea_lab.approve_and_generate_content(
            idea_id=idea_id,
            project_id=project_id,
            feedback_manager=container.feedback_manager,
        )
        return result
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    except Exception as e:
        print(f"Approve-and-generate failed for idea {idea_id}: {e}")
        return {"success": False, "error": "Failed to approve and generate idea"}


@router.delete("/api/ideas/ideas/{idea_id}")
async def api_delete_content_idea(
    idea_id: str,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        deleted = idea_lab.delete_content_idea(idea_id)
        if not deleted:
            return JSONResponse(
                status_code=404, content={"success": False, "error": "Not found"}
            )
        return {"success": True, "deleted": True}
    except Exception as e:
        print(f"Delete content idea failed for {idea_id}: {e}")
        return {"success": False, "error": "Failed to delete content idea"}


@router.post("/api/ideas/mining/trigger")
async def api_mining_trigger(
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        body = await request.json()
    except Exception:
        body = {}

    project_id = body.get("project_id")
    if not project_id:
        project_id = _default_project_id_for_request(request)
    if not project_id:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "project_id is required"},
        )
    _require_project_access(request, project_id, "editor")

    enrichment = idea_lab.enrich_all_pending(project_id)
    ideas = idea_lab.generate_ideas_for_project(project_id)
    return {"success": True, "enrichment": enrichment, "ideas": ideas}
