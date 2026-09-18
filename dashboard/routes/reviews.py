"""Review state-transition routes extracted from ``unified_dashboard.py:main()``.

Each route body is a verbatim copy of the corresponding inline closure with
two mechanical substitutions:

* ``@app.<method>`` decorators become ``@router.<method>`` with the same path.
* ``dashboard_instance.<collaborator>`` references become FastAPI
  ``Depends(get_<collaborator>)`` parameters (or ``container.<collaborator>``
  via ``Depends(get_container)`` for one-off attributes such as
  ``schedule_post`` / ``resolve_record_project_id``).

Behavior, response shapes, exception translation, redirect targets, and form
delegator patterns (the FakeRequest shim) are preserved byte-for-byte. The
authz helpers are imported from ``dashboard.middleware.auth`` -- never
duplicated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from data.review_models import ReviewAction
from dashboard.dependencies import (
    get_container,
    get_feedback_manager,
    get_idea_lab,
    get_review_workflow,
    get_store,
)
from dashboard.middleware.auth import (
    _default_project_id_for_request,
    _request_principal,
    _require_project_access,
)
from dashboard.routes._helpers import (
    ALLOWED_PROVIDERS,
    MAX_CONTENT_PLAN_CHARS,
    pipeline_redirect,
    validation_error_message,
)
from dashboard.routes.generation import GenerateContentRequest
from services.review_workflow_service import ReviewTransitionError

router = APIRouter()


class PublishContentRequest(BaseModel):
    """Validated body for /api/publish."""

    model_config = ConfigDict(extra="ignore")

    review_id: str = Field(min_length=1, max_length=200)
    provider: Optional[str] = Field(default=None, max_length=40)
    platform: Optional[str] = Field(default=None, max_length=40)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.lower().strip()
        if normalized not in ALLOWED_PROVIDERS:
            raise ValueError("unsupported provider")
        return normalized

    @field_validator("platform")
    @classmethod
    def validate_optional_platform(cls, value: Optional[str]) -> Optional[str]:
        return GenerateContentRequest.validate_platform(value)


class ScheduleContentRequest(BaseModel):
    """Validated body for /api/content/{review_id}/schedule."""

    model_config = ConfigDict(extra="ignore")

    scheduled_date: Optional[str] = Field(default=None, max_length=80)
    feedback: str = Field(default="", max_length=MAX_CONTENT_PLAN_CHARS)


class ApproveContentRequest(BaseModel):
    """Validated body for /api/content/{review_id}/approve.

    The ``publish`` flag (default true) is the surface-level pin for ARCH-03
    success criterion #3: when false, the route calls transition(APPROVE)
    only and skips transition(SCHEDULE), leaving every provider untouched.
    """

    model_config = ConfigDict(extra="ignore")

    feedback: str = Field(default="", max_length=MAX_CONTENT_PLAN_CHARS)
    scheduled_date: Optional[str] = Field(default=None, max_length=80)
    publish: bool = True
    tags: str = Field(default="", max_length=MAX_CONTENT_PLAN_CHARS)


@router.post("/approve/{review_id}")
async def approve_content(
    review_id: str,
    request: Request,
    feedback: str = Form(""),
    channel: str = Form("twitter"),
    scheduled_date: str = Form(""),
    tags: str = Form(""),
    publish: str = Form("true"),
    rw: Any = Depends(get_review_workflow),
):
    try:
        rw.transition(
            review_id,
            ReviewAction.APPROVE,
            feedback=feedback,
            explicit_tags=tags,
        )
        if publish.lower() != "false":
            rw.transition(
                review_id,
                ReviewAction.SCHEDULE,
                feedback=feedback or "Approved and scheduled",
                scheduled_date=scheduled_date or None,
                platform=channel,
            )
    except ReviewTransitionError as e:
        print(f"Warning: Approval failed: {e.code}: {e.message}")

    return pipeline_redirect(request)


@router.post("/needs-work/{review_id}")
async def request_changes(
    review_id: str,
    request: Request,
    feedback: str = Form(""),
    tags: str = Form(""),
    rw: Any = Depends(get_review_workflow),
    container: Any = Depends(get_container),
):
    try:
        rw.transition(
            review_id,
            ReviewAction.NEEDS_WORK,
            feedback=feedback,
            explicit_tags=tags,
        )
        rw.apply_auto_fix(review_id, feedback=feedback, job_queue=container.job_queue)
    except ReviewTransitionError as e:
        print(f"Warning: needs-work transition failed: {e.code}: {e.message}")
    except Exception as e:
        print(f"Warning: Auto-fix enqueue failed: {e}")

    return pipeline_redirect(request)


@router.post("/api/decline/{review_id}")
async def decline_content_api(
    review_id: str,
    request: Request,
    rw: Any = Depends(get_review_workflow),
):
    try:
        body = await request.json()
        feedback = body.get("feedback", "")
        explicit_tags = body.get("tags", "")
    except Exception:
        feedback = ""
        explicit_tags = ""

    try:
        rw.transition(
            review_id,
            ReviewAction.DECLINE,
            feedback=feedback,
            explicit_tags=explicit_tags,
        )
    except ReviewTransitionError as e:
        return {"success": False, "error": e.message, "code": e.code}

    return {"success": True, "review_id": review_id}


@router.post("/decline/{review_id}")
async def decline_content(
    review_id: str,
    request: Request,
    feedback: str = Form(""),
    rw: Any = Depends(get_review_workflow),
):
    class FakeRequest:
        async def json(self):
            return {"feedback": feedback}

    result = await decline_content_api(review_id, FakeRequest(), rw)
    if not result.get("success"):
        print(f"Warning: decline failed: {result.get('code')}: {result.get('error')}")
    return pipeline_redirect(request)


@router.post("/schedule/{review_id}")
async def schedule_content(
    review_id: str,
    request: Request,
    scheduled_date: str = Form(...),
    scheduled_time: str = Form(...),
    feedback: str = Form(""),
    container: Any = Depends(get_container),
):
    scheduled_at = f"{scheduled_date}T{scheduled_time}"

    record = container.feedback_manager._load_review_record(review_id)
    if record:
        project_id = container.resolve_record_project_id(record)
        if not project_id:
            print(f"Warning: cannot schedule {review_id}: missing project_id")
        else:
            container.project_manager.verify_project_match(
                record["post_data"].get("project_id"),
                project_id,
            )
            post_id = container.schedule_post(
                record["post_data"],
                scheduled_at,
                review_id=review_id,
            )
            job = container.job_queue.enqueue(
                "publish_scheduled_post",
                project_id=project_id,
                available_at=scheduled_at,
                payload={
                    "post_id": post_id,
                    "review_id": review_id,
                    "project_id": project_id,
                    "platform": record["post_data"].get("platform"),
                },
            )
            scheduled_record = container.store.get_scheduled_record(post_id)
            if scheduled_record:
                scheduled_record["job_id"] = job["job_id"]
                container.store.save_scheduled_record(scheduled_record)
            container.feedback_manager.process_feedback(
                review_id, "schedule", feedback
            )

    return pipeline_redirect(request)


@router.post("/regenerate/{review_id}")
async def regenerate_content(
    review_id: str,
    request: Request,
    feedback: str = Form("Please regenerate this content"),
    rw: Any = Depends(get_review_workflow),
):
    return await request_changes(review_id, request, feedback, rw)


@router.post("/reject/{review_id}")
async def reject_content(
    review_id: str,
    request: Request,
    feedback: str = Form(""),
    fm: Any = Depends(get_feedback_manager),
):
    fm.process_feedback(review_id, "reject", feedback)
    return pipeline_redirect(request)


@router.post("/scheduled/delete/{post_id}")
async def delete_scheduled(
    post_id: str,
    container: Any = Depends(get_container),
):
    container.store.delete_scheduled_record(post_id)
    for job in container.job_queue.list(status="queued", limit=500):
        if job.get("payload", {}).get("post_id") == post_id:
            container.job_queue.cancel(job["job_id"])
    return RedirectResponse(url="/scheduled", status_code=303)


@router.get("/sync-analytics")
async def sync_analytics_get():
    return JSONResponse(
        status_code=405,
        content={
            "success": False,
            "error": "Use POST /sync-analytics to enqueue analytics sync",
        },
    )


@router.post("/sync-analytics")
async def sync_analytics(
    request: Request,
    container: Any = Depends(get_container),
):
    project_id = _default_project_id_for_request(request)
    if project_id:
        _require_project_access(request, project_id, "publisher")
    elif _request_principal(request).is_scoped:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "project_id is required"},
        )
    container.job_queue.enqueue(
        "sync_analytics",
        project_id=project_id,
        payload={"project_id": project_id} if project_id else {},
    )
    return RedirectResponse(url="/analytics?sync=queued", status_code=303)


@router.get("/api/calendar/events")
async def get_calendar_events(
    request: Request,
    start: str,
    end: str,
    project: str = "",
    container: Any = Depends(get_container),
):
    project = project or _default_project_id_for_request(request)
    if project:
        _require_project_access(request, project, "viewer")
    events = []
    seen_ids = set()

    platform_colors = {
        "twitter": "#1DA1F2",
        "linkedin": "#0077B5",
        "instagram": "#E4405F",
        "facebook": "#1877F2",
        "nostr": "#9333EA",
    }

    scheduled_posts = container.store.list_scheduled_records(
        project_id=project or None
    )
    for post in scheduled_posts:
        post_data = post.get("post_data", {})
        platform = post_data.get("platform", "unknown")
        status = post.get("status", "scheduled")

        if status == "published":
            color = "#10B981"
        elif status == "draft":
            color = "#F59E0B"
        else:
            color = platform_colors.get(platform, "#667eea")

        content = post_data.get("content", "")
        title = content[:50] + "..." if len(content) > 50 else content
        post_id = post.get("post_id", "")

        events.append(
            {
                "id": post_id,
                "title": f"{platform.title()}: {title}",
                "start": post.get("scheduled_at"),
                "backgroundColor": color,
                "borderColor": color,
                "extendedProps": {
                    "platform": platform,
                    "status": status,
                    "content": content,
                    "post_id": post_id,
                    "source": "local",
                },
            }
        )
        seen_ids.add(post_id)

    # Nostr sign-now-publish-later requests: pending signatures, signed
    # future-dated events, failures, and published history.
    try:
        nostr_records = container.store.list_nostr_request_records(
            project_id=project or None
        )
    except AttributeError:
        nostr_records = []
    nostr_colors = {
        "pending_signature": "#F59E0B",
        "signed": platform_colors.get("nostr", "#9333EA"),
        "publish_failed": "#EF4444",
        "published": "#10B981",
    }
    for record in nostr_records:
        request_id = record.get("request_id", "")
        nostr_key = f"nostr_{request_id}"
        if nostr_key in seen_ids or request_id in seen_ids:
            continue
        status = record.get("status", "pending_signature")
        if status == "cancelled":
            continue  # cancelled requests do not belong on the calendar
        seen_ids.add(nostr_key)
        unsigned_events = record.get("unsigned_events") or []
        content = ""
        for event in unsigned_events:
            content += event.get("content", "") + "\n"
        content = content.strip()
        title = content[:50] + "..." if len(content) > 50 else content

        when = (
            record.get("scheduled_at")
            or record.get("published_at")
            or record.get("created_at")
        )
        label = {
            "pending_signature": "Nostr (needs signature)",
            "signed": "Nostr (signed)",
            "publish_failed": "Nostr (failed)",
            "published": "Nostr",
        }.get(status, "Nostr")

        events.append(
            {
                "id": nostr_key,
                "title": f"{label}: {title}",
                "start": when,
                "backgroundColor": nostr_colors.get(status, "#9333EA"),
                "borderColor": nostr_colors.get(status, "#9333EA"),
                "extendedProps": {
                    "platform": "nostr",
                    "status": status,
                    "content": content,
                    "post_id": record.get("event_id") or nostr_key,
                    "request_id": request_id,
                    "event_uri": record.get("event_uri"),
                    "source": "nostr",
                },
            }
        )

    try:
        api_key = container.secret_service.get_api_key(project, "typefully")
        if api_key and project:
            settings_data = container.project_manager.get_project_settings(project)
            social_set_ids = set()
            for prof in settings_data.get("social_profiles", []):
                if prof.get("enabled", False):
                    raw_account_id = str(prof.get("account_id", ""))
                    if raw_account_id.startswith("typefully_"):
                        raw_account_id = raw_account_id.split("_")[1]
                    if raw_account_id.isdigit():
                        social_set_ids.add(int(raw_account_id))

            if social_set_ids:
                from integrations.typefully import TypefullySyncClient

                with TypefullySyncClient(api_key=api_key) as client:
                    typefully_drafts = []
                    for sid in social_set_ids:
                        typefully_drafts.extend(
                            client.get_drafts_for_social_set(
                                sid, status="scheduled", limit=50
                            )
                        )
                        typefully_drafts.extend(
                            client.get_drafts_for_social_set(
                                sid, status="published", limit=50
                            )
                        )

                for draft in typefully_drafts:
                    draft_id = str(draft.get("id", ""))
                    tf_key = f"typefully_{draft_id}"
                    if tf_key in seen_ids:
                        continue
                    seen_ids.add(tf_key)

                    content = draft.get("preview", "") or draft.get("draft_title", "")
                    title = content[:50] + "..." if len(content) > 50 else content

                    scheduled_at = draft.get("scheduled_date")
                    published_at = draft.get("published_at")
                    status = draft.get("status", "")

                    if published_at:
                        event_start = published_at
                        status = "published"
                        color = "#10B981"
                    elif scheduled_at:
                        event_start = scheduled_at
                        status = "scheduled"
                    else:
                        continue

                    platforms_on = []
                    if draft.get("x_post_enabled"):
                        platforms_on.append("twitter")
                    if draft.get("linkedin_post_enabled"):
                        platforms_on.append("linkedin")
                    if draft.get("threads_post_enabled"):
                        platforms_on.append("threads")
                    if draft.get("bluesky_post_enabled"):
                        platforms_on.append("bluesky")
                    platform = platforms_on[0] if platforms_on else "twitter"

                    if status != "published":
                        color = platform_colors.get(platform, "#667eea")

                    private_url = draft.get("private_url", "")

                    events.append(
                        {
                            "id": tf_key,
                            "title": f"{platform.title()}: {title}",
                            "start": event_start,
                            "backgroundColor": color,
                            "borderColor": color,
                            "extendedProps": {
                                "platform": platform,
                                "status": status,
                                "content": content,
                                "post_id": draft_id,
                                "source": "typefully",
                                "url": private_url,
                            },
                        }
                    )
    except Exception as e:
        print(f"Calendar: could not load Typefully drafts: {e}")

    return {"success": True, "events": events}


@router.post("/api/calendar/events/{event_id}/reschedule")
async def reschedule_calendar_event(
    event_id: str,
    request: Request,
    store: Any = Depends(get_store),
):
    data = await request.json()
    new_scheduled_at = data.get("scheduled_at")

    if not new_scheduled_at:
        return {"success": False, "error": "scheduled_at is required"}

    post = store.get_scheduled_record(event_id)
    if not post:
        return {"success": False, "error": "Event not found"}
    post["scheduled_at"] = new_scheduled_at
    store.save_scheduled_record(post)

    return {"success": True}


@router.get("/api/content")
async def api_list_content(
    request: Request,
    fm: Any = Depends(get_feedback_manager),
):
    status_filter = request.query_params.get("status", "pending")
    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))
    project_id = request.query_params.get("project_id")
    if not project_id:
        project_id = _default_project_id_for_request(request)
    if project_id:
        _require_project_access(request, project_id, "viewer")

    reviews = fm._load_reviews()
    status_map = {
        "pending": "pending_review",
        "approved": "approved",
        "scheduled": "scheduled",
        "published": "published",
        "declined": "declined",
    }
    internal_status = status_map.get(status_filter, status_filter)

    filtered = [r for r in reviews.values() if r.get("status") == internal_status]
    if project_id:
        filtered = [
            r
            for r in filtered
            if r.get("project_id") == project_id
            or r.get("post_data", {}).get("project_id") == project_id
        ]

    filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    total = len(filtered)
    filtered = filtered[offset : offset + limit]

    return {
        "success": True,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": filtered,
    }


@router.post("/api/content/{review_id}/approve")
async def api_approve_content(
    review_id: str,
    request: Request,
    rw: Any = Depends(get_review_workflow),
):
    try:
        body = ApproveContentRequest.model_validate(await request.json())
    except ValidationError as e:
        return {"success": False, "error": validation_error_message(e)}
    except Exception:
        body = ApproveContentRequest()

    try:
        record = rw.transition(
            review_id,
            ReviewAction.APPROVE,
            feedback=body.feedback,
            explicit_tags=body.tags,
        )
    except ReviewTransitionError as e:
        return {"success": False, "error": e.message, "code": e.code}

    if not body.publish:
        return {
            "success": True,
            "review_id": review_id,
            "status": record.status.value,
            "scheduling": {"scheduled": False, "skipped": "publish=false"},
        }

    try:
        scheduled = rw.transition(
            review_id,
            ReviewAction.SCHEDULE,
            feedback=body.feedback or "Approved and scheduled via API",
            scheduled_date=body.scheduled_date,
        )
    except ReviewTransitionError as e:
        return {
            "success": True,
            "review_id": review_id,
            "status": record.status.value,
            "scheduling": {"scheduled": False, "error": e.message, "code": e.code},
        }

    return {
        "success": True,
        "review_id": review_id,
        "status": scheduled.status.value,
        "scheduling": {
            "scheduled": True,
            "provider": scheduled.raw.get("published_via"),
            "draft_url": scheduled.raw.get("draft_url"),
            "draft_id": scheduled.raw.get("draft_id"),
        },
    }


@router.post("/api/content/{review_id}/reject")
async def api_reject_content(
    review_id: str,
    request: Request,
    rw: Any = Depends(get_review_workflow),
):
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        rw.transition(
            review_id,
            ReviewAction.DECLINE,
            feedback=body.get("feedback", "Rejected via API"),
        )
    except ReviewTransitionError as e:
        return {"success": False, "error": e.message, "code": e.code}

    return {"success": True, "review_id": review_id, "status": "declined"}


@router.post("/api/content/{review_id}/needs-work")
async def api_needs_work_content(
    review_id: str,
    request: Request,
    rw: Any = Depends(get_review_workflow),
    container: Any = Depends(get_container),
):
    try:
        body = await request.json()
    except Exception:
        body = {}

    feedback = body.get("feedback", "")
    tags = body.get("tags", [])
    if isinstance(tags, list):
        explicit_tags = ",".join(str(t) for t in tags)
    else:
        explicit_tags = str(tags or "")

    try:
        rw.transition(
            review_id,
            ReviewAction.NEEDS_WORK,
            feedback=feedback,
            explicit_tags=explicit_tags,
        )
        job = rw.apply_auto_fix(
            review_id,
            feedback=feedback,
            job_queue=container.job_queue,
        )
    except ReviewTransitionError as e:
        return {"success": False, "error": e.message, "code": e.code}
    except Exception as e:
        print(f"Auto-fix enqueue failed for {review_id}: {e}")
        return {"success": False, "error": "Auto-fix enqueue failed"}

    return {
        "success": True,
        "review_id": review_id,
        "status": "needs_work",
        "auto_fix_status": "queued",
        "job_id": job["job_id"],
    }


@router.post("/api/content/{review_id}/schedule")
async def api_schedule_content(
    review_id: str,
    request: Request,
    container: Any = Depends(get_container),
):
    try:
        body = ScheduleContentRequest.model_validate(await request.json())
    except ValidationError as e:
        return {"success": False, "error": validation_error_message(e)}
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    result = container.content_workflow.approve_and_schedule(
        review_id=review_id,
        feedback=body.feedback,
        scheduled_date=body.scheduled_date,
    )
    return result


@router.post("/api/content/{review_id}/carousel")
async def api_generate_carousel_for_review(
    review_id: str,
    request: Request,
    idea_lab: Any = Depends(get_idea_lab),
):
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        num_cards = int(body.get("num_cards", 5))
    except (TypeError, ValueError):
        return {"success": False, "error": "num_cards must be an integer"}
    if num_cards < 1 or num_cards > 12:
        return {"success": False, "error": "num_cards must be between 1 and 12"}

    return await idea_lab.generate_carousel_for_review(
        review_id=review_id,
        num_cards=num_cards,
    )


@router.post("/api/content/{review_id}/visual")
async def api_generate_visual_prop(
    review_id: str,
    request: Request,
    container: Any = Depends(get_container),
):
    record = container.feedback_manager._load_review_record(review_id)
    if not record:
        return {"success": False, "error": f"Review {review_id} not found"}

    content = record.get("content", "")
    if not content:
        post_data = record.get("post_data", {})
        content = post_data.get("content", "")
    platform = (
        record.get("platform", "")
        or record.get("channel", "")
        or record.get("post_data", {}).get("platform", "linkedin")
    )
    title = record.get("content_type", "") or record.get("post_data", {}).get(
        "content_type", ""
    )
    title = title.replace("_", " ").title()

    if not content:
        return {"success": False, "error": "No content in review record"}

    try:
        from integrations.gamma_api import GammaAPIClient

        gamma = GammaAPIClient()
        if not gamma.is_configured():
            return {"success": False, "error": "Gamma not configured (GAMMA_APP_API_KEY)"}

        result = await gamma.generate_visual_prop(
            content=content,
            title=title,
            platform=platform,
        )
        if not result.get("success"):
            return result

        export_url = result.get("export_url", "")
        generation_id = result.get("generation_id", "")
        media_dir = str(Path("data/media"))
        images = await gamma.download_card_images(
            export_url=export_url,
            dest_dir=media_dir,
            generation_id=generation_id,
        )

        if images:
            container.review_workflow.transition(
                review_id,
                ReviewAction.ATTACH_MEDIA,
                media={
                    "visual_prop": {
                        "generation_id": generation_id,
                        "image_path": images[0],
                        "gamma_url": result.get("gamma_url", ""),
                    }
                },
            )

        return {
            "success": True,
            "image_path": images[0] if images else None,
            "gamma_url": result.get("gamma_url", ""),
            "generation_id": generation_id,
        }

    except Exception as e:
        print(f"Visual generation failed for {review_id}: {e}")
        return {"success": False, "error": "Visual generation failed"}


@router.post("/api/content/{review_id}/infographic")
async def api_generate_infographic(
    review_id: str,
    request: Request,
    container: Any = Depends(get_container),
):
    record = container.feedback_manager._load_review_record(review_id)
    if not record:
        return {"success": False, "error": f"Review {review_id} not found"}

    content = record.get("content", "")
    if not content:
        post_data = record.get("post_data", {})
        content = post_data.get("content", "")
    platform = (
        record.get("platform", "")
        or record.get("channel", "")
        or record.get("post_data", {}).get("platform", "linkedin")
    )
    title = record.get("content_type", "") or record.get("post_data", {}).get(
        "content_type", ""
    )
    title = title.replace("_", " ").title()

    if not content:
        return {"success": False, "error": "No content in review record"}

    aspect = "4x5"
    if platform in ("twitter", "x"):
        aspect = "1x1"
    elif platform in ("stories", "reels"):
        aspect = "9x16"

    try:
        from integrations.gamma_api import GammaAPIClient

        gamma = GammaAPIClient()
        if not gamma.is_configured():
            return {"success": False, "error": "Gamma not configured (GAMMA_APP_API_KEY)"}

        result = await gamma.generate_infographic(
            content=content,
            title=title or "Infographic",
            aspect_ratio=aspect,
        )
        if not result.get("success"):
            return result

        export_url = result.get("export_url", "")
        generation_id = result.get("generation_id", "")
        media_dir = str(Path("data/media"))
        images = await gamma.download_card_images(
            export_url=export_url,
            dest_dir=media_dir,
            generation_id=generation_id,
        )

        if images:
            container.review_workflow.transition(
                review_id,
                ReviewAction.ATTACH_MEDIA,
                media={
                    "infographic": {
                        "generation_id": generation_id,
                        "image_path": images[0],
                        "gamma_url": result.get("gamma_url", ""),
                    }
                },
            )

        return {
            "success": True,
            "image_path": images[0] if images else None,
            "gamma_url": result.get("gamma_url", ""),
            "generation_id": generation_id,
        }

    except Exception as e:
        print(f"Infographic generation failed for {review_id}: {e}")
        return {"success": False, "error": "Infographic generation failed"}


@router.post("/api/publish")
async def api_publish_content(
    request: Request,
    container: Any = Depends(get_container),
):
    try:
        body = PublishContentRequest.model_validate(await request.json())
    except ValidationError as e:
        return {"success": False, "error": validation_error_message(e)}
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    return container.content_workflow.publish_review(
        body.review_id,
        provider_name=body.provider,
        platform=body.platform,
    )
