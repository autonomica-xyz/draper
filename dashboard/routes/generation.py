"""Content / media generation API routes extracted from
``unified_dashboard.py:main()``.

Each route body is a verbatim copy of the corresponding inline closure with
the standard mechanical substitutions applied across the plan:

* ``@app.<method>`` decorators become ``@router.<method>``.
* ``dashboard_instance.<collaborator>`` becomes ``Depends(get_<collaborator>)``
  (or ``container.<collaborator>`` via ``Depends(get_container)`` for
  one-off accesses).

Threat T-03-03-03 (DoS via /api/generate): the ``{async: true}``
short-circuit is preserved verbatim — when ``enqueue_requested`` is true
the route enqueues a job and returns ``{success, async, job_id, job}``
WITHOUT calling ``generator.generate_batch``. The RateLimiter
``EXPENSIVE_ROUTE_LIMITS`` (Plan 03-01) guards the synchronous path.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dashboard.dependencies import (
    get_container,
    get_feedback_manager,
    get_job_queue,
)
from dashboard.middleware.auth import (
    _default_project_id_for_request,
    _require_project_access,
)
from dashboard.routes._helpers import ALLOWED_PLATFORMS, validation_error_message

router = APIRouter()


class GenerateContentRequest(BaseModel):
    """Validated body for /api/generate."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    count: int = Field(default=5, ge=1, le=25)
    platform: Optional[str] = Field(default=None, max_length=40)
    project_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    content_type: Optional[str] = Field(default=None, max_length=80)
    async_: bool = Field(default=False, alias="async")
    background: bool = False
    enqueue: bool = False
    repurpose: bool = False

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.lower().strip()
        if normalized not in ALLOWED_PLATFORMS:
            raise ValueError("unsupported platform")
        return "twitter" if normalized == "x" else normalized

    @property
    def enqueue_requested(self) -> bool:
        return self.async_ or self.background or self.enqueue


@router.post("/api/generate")
async def api_generate_content(
    request: Request,
    container: Any = Depends(get_container),
    feedback_manager: Any = Depends(get_feedback_manager),
    job_queue: Any = Depends(get_job_queue),
):
    try:
        body = GenerateContentRequest.model_validate(await request.json())
    except ValidationError as e:
        return {"success": False, "error": validation_error_message(e)}
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    count = body.count
    platform = body.platform
    platforms = [platform] if platform else None
    request_project_id = body.project_id
    if not request_project_id:
        request_project_id = _default_project_id_for_request(request)
    if not request_project_id or not container.project_manager.get_project(
        request_project_id
    ):
        return {"success": False, "error": "project_id is required"}
    _require_project_access(request, request_project_id, "editor")

    if body.enqueue_requested:
        job = job_queue.enqueue(
            "generate_content",
            project_id=request_project_id,
            payload={
                "project_id": request_project_id,
                "count": count,
                "platform": platform,
                "content_type": body.content_type,
                "channel": "API",
            },
        )
        return {
            "success": True,
            "async": True,
            "job_id": job["job_id"],
            "job": job,
        }

    try:
        generator = container.get_generator_for_project(request_project_id)
        batch_result = generator.generate_batch(
            count=count,
            platforms=platforms,
            repurpose=body.repurpose,
        )
        batch = (
            batch_result.get("posts", [])
            if isinstance(batch_result, dict)
            else batch_result
        )
    except Exception as e:
        print(f"Content generation failed: {e}")
        return {"success": False, "error": "Generation failed"}

    review_ids = []
    for post in batch:
        post["project_id"] = request_project_id
        if body.content_type:
            post["content_type"] = body.content_type
        record = feedback_manager.post_content_for_review(post, "API")
        review_ids.append(record.get("review_id"))

    return {"success": True, "count": len(batch), "review_ids": review_ids, "items": batch}


@router.post("/api/generate/image")
async def api_generate_image(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    prompt = body.get("prompt", "")
    if not prompt:
        return {"success": False, "error": "prompt is required"}
    if len(prompt) > 4000:
        return {"success": False, "error": "prompt is too long"}

    try:
        from integrations.zai_image import ZAIImageGenerator

        zai = ZAIImageGenerator()
        if zai.is_configured():
            result = await zai.generate_social_image(
                topic=prompt,
                platform=body.get("platform", "instagram"),
                style=body.get("style", "minimal"),
            )
            return result
    except Exception as e:
        print(f"Image generation failed: {e}")
        return {"success": False, "error": "Image generation failed"}

    return {
        "success": False,
        "error": "No image generation provider configured. Set ZAI_API_KEY.",
    }


@router.post("/api/generate/carousel")
async def api_generate_carousel(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    content = body.get("content", "")
    if not content:
        return {"success": False, "error": "content is required"}
    if len(content) > 12000:
        return {"success": False, "error": "content is too long"}
    try:
        num_cards = int(body.get("num_cards", 5))
    except (TypeError, ValueError):
        return {"success": False, "error": "num_cards must be an integer"}
    if num_cards < 1 or num_cards > 12:
        return {"success": False, "error": "num_cards must be between 1 and 12"}

    try:
        from integrations.gamma_api import GammaAPIClient

        gamma = GammaAPIClient()
        if gamma.is_configured():
            result = await gamma.generate_carousel(
                content=content,
                title=body.get("title", ""),
                num_cards=num_cards,
                platform=body.get("platform", "linkedin"),
            )
            return result
    except Exception as e:
        print(f"Carousel generation failed: {e}")
        return {"success": False, "error": "Carousel generation failed"}

    return {"success": False, "error": "Gamma.app not configured. Set GAMMA_APP_API_KEY."}
