"""Draper Marketing Pipeline MCP Server.

Exposes the full platform as MCP tools so AI agents can generate, review,
publish, and analyze marketing content without touching the dashboard.

Run:
    python -m mcp_server                          # stdio (default)
    python -m mcp_server --transport streamable-http --port 9000

Environment:
    DRAPER_PROJECT_ID   — default project (optional)
    ANTHROPIC_API_KEY       — for LLM content generation
    TYPEFULLY_API_KEY       — for publishing to Twitter/LinkedIn
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(Path(_PROJECT_ROOT) / ".env")

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from data.sqlite_store import SQLiteStore
from feedback.manager import FeedbackManager
from generator.llm_content_generator import LLMContentGenerator
from data.review_models import ReviewAction
from services.project_service import ProjectService
from services.access_control import (
    AccessDeniedError,
    DashboardAccessPolicy,
    Principal,
    cap_role,
    normalize_role,
    roles_from_projects,
)
from services.content_workflow import ContentWorkflowService
from services.idea_lab import IdeaLabService
from services.job_queue import JobQueueService
from services.project_context import ProjectContextService
from services.publishing_service import ProjectPublishingService
from services.review_workflow_service import (
    ReviewTransitionError,
    ReviewWorkflowService,
)

# ---------------------------------------------------------------------------
# Bootstrap service layer
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DRAPER_DATA_DIR", Path(_PROJECT_ROOT) / "data"))
STORE = SQLiteStore(data_dir=str(DATA_DIR))
PROJECT_MANAGER = ProjectService(data_dir=str(DATA_DIR))
FEEDBACK_MANAGER = FeedbackManager(data_dir=str(DATA_DIR))
PROJECT_CONTEXT = ProjectContextService(PROJECT_MANAGER)
PUBLISHING_SERVICE = ProjectPublishingService(
    PROJECT_MANAGER,
    data_dir=str(DATA_DIR),
    project_context=PROJECT_CONTEXT,
)
IDEA_LAB = IdeaLabService(STORE)
JOB_QUEUE = JobQueueService(STORE)
WORKFLOW = ContentWorkflowService(
    feedback_manager=FEEDBACK_MANAGER,
    project_context=PROJECT_CONTEXT,
    publishing_service=PUBLISHING_SERVICE,
)
REVIEW_WORKFLOW = ReviewWorkflowService(
    feedback_manager=FEEDBACK_MANAGER,
    project_context=PROJECT_CONTEXT,
    publishing_service=PUBLISHING_SERVICE,
)
MCP_ACCESS_POLICY = DashboardAccessPolicy(
    host=os.environ.get("DRAPER_MCP_HOST", "127.0.0.1"),
    token=os.environ.get("DRAPER_MCP_ADMIN_TOKEN") or None,
    require_auth=True,
)


class DraperMCPTokenVerifier:
    """Accept environment admin tokens and project-scoped MCP tokens."""

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = _authenticate_mcp_token(token)
        if not principal:
            return None
        scopes = ["mcp:admin", "mcp:project"] if principal.is_admin else ["mcp:project"]
        return AccessToken(
            token=token,
            client_id=principal.token_id,
            scopes=scopes,
            subject=principal.label,
            claims={
                "token_id": principal.token_id,
                "label": principal.label,
                "is_admin": principal.is_admin,
                "project_roles": principal.project_roles,
                "mcp_enabled": principal.mcp_enabled,
                "token_prefix": principal.token_prefix,
            },
        )


def _authenticate_mcp_token(token: str) -> Optional[Principal]:
    """Authenticate a bearer token for streamable HTTP MCP."""
    env_mcp_token = os.environ.get("DRAPER_MCP_TOKEN", "").strip()
    if env_mcp_token and os.environ.get("DRAPER_MCP_PROJECT_ID"):
        import secrets as _secrets

        if _secrets.compare_digest(token, env_mcp_token):
            project_ids = [
                item.strip()
                for item in os.environ.get("DRAPER_MCP_PROJECT_ID", "").split(",")
                if item.strip()
            ]
            role = normalize_role(os.environ.get("DRAPER_MCP_ROLE", "editor"))
            return Principal(
                token_id="env-mcp-project",
                label="Environment MCP project token",
                project_roles=roles_from_projects(project_ids, role),
                mcp_enabled=True,
                token_prefix="env-mcp",
            )

    principal = MCP_ACCESS_POLICY.authenticate(token, STORE)
    if not principal:
        return None
    if principal.is_admin:
        return principal
    if not principal.mcp_enabled:
        return None

    enabled_roles = {}
    for project_id, role in principal.project_roles.items():
        config = STORE.get_project_mcp_config(project_id)
        if config.get("enabled"):
            enabled_roles[project_id] = cap_role(role, config.get("max_role", "viewer"))
    if not enabled_roles:
        return None
    principal.project_roles = enabled_roles
    return principal


def _principal_from_access_token(token: AccessToken) -> Principal:
    claims = token.claims or {}
    return Principal(
        token_id=str(claims.get("token_id") or token.client_id),
        label=str(claims.get("label") or token.subject or "MCP caller"),
        is_admin=bool(claims.get("is_admin")),
        project_roles={
            str(project_id): normalize_role(str(role))
            for project_id, role in (claims.get("project_roles") or {}).items()
        },
        mcp_enabled=bool(claims.get("mcp_enabled")),
        token_prefix=str(claims.get("token_prefix") or ""),
    )


def _current_mcp_principal() -> Principal:
    """Return the request principal, falling back to local stdio scope."""
    token = get_access_token()
    if token:
        return _principal_from_access_token(token)

    project_ids = [
        item.strip()
        for item in os.environ.get("DRAPER_MCP_PROJECT_ID", "").split(",")
        if item.strip()
    ]
    if project_ids:
        return Principal(
            token_id="local-mcp-project",
            label="Local MCP project scope",
            project_roles=roles_from_projects(
                project_ids,
                os.environ.get("DRAPER_MCP_ROLE", "editor"),
            ),
            mcp_enabled=True,
        )
    return Principal(
        token_id="local-mcp-admin", label="Local MCP stdio", is_admin=True, mcp_enabled=True
    )


def _check_mcp_project(project_id: str, required_role: str, tool_name: str) -> None:
    principal = _current_mcp_principal()
    principal.require_project_role(project_id, required_role)
    if principal.is_admin:
        return
    config = STORE.get_project_mcp_config(project_id)
    if not config.get("enabled"):
        raise AccessDeniedError("MCP is not enabled for this project")
    allowed_tools = set(config.get("allowed_tools") or [])
    if allowed_tools and tool_name not in allowed_tools:
        raise AccessDeniedError(f"MCP tool '{tool_name}' is not enabled for this project")


def _record_project_id(record: Optional[Dict]) -> Optional[str]:
    if not record:
        return None
    return record.get("project_id") or (record.get("post_data") or {}).get("project_id")


def _check_review_access(review_id: str, required_role: str, tool_name: str) -> Dict:
    record = FEEDBACK_MANAGER._load_review_record(review_id)
    if not record:
        raise ValueError(f"Content not found: {review_id}")
    project_id = _record_project_id(record)
    if not project_id:
        raise AccessDeniedError("Content has no project_id")
    _check_mcp_project(project_id, required_role, tool_name)
    return record


def _check_source_material_access(material_id: str, required_role: str, tool_name: str):
    material = IDEA_LAB.get_source_material(material_id)
    if not material:
        raise ValueError(f"Source material not found: {material_id}")
    _check_mcp_project(material.project_id, required_role, tool_name)
    return material


def _check_content_idea_access(idea_id: str, required_role: str, tool_name: str):
    idea = IDEA_LAB.get_content_idea(idea_id)
    if not idea:
        raise ValueError(f"Content idea not found: {idea_id}")
    _check_mcp_project(idea.project_id, required_role, tool_name)
    return idea


def _check_job_access(job_id: str, required_role: str, tool_name: str) -> Dict:
    record = STORE.get_job_record(job_id)
    if not record:
        raise ValueError(f"Job not found: {job_id}")
    project_id = record.get("project_id")
    if project_id:
        _check_mcp_project(project_id, required_role, tool_name)
    elif not _current_mcp_principal().is_admin:
        raise AccessDeniedError("Project-scoped MCP callers cannot access global jobs")
    return record


def _get_project(project_id: Optional[str] = None):
    """Resolve a project, falling back to env var then current selection."""
    if not project_id:
        project_id = os.environ.get("DRAPER_PROJECT_ID")
    if project_id:
        p = PROJECT_MANAGER.get_project(project_id)
        if p:
            return p
    p = PROJECT_MANAGER.get_current_project()
    if p:
        return p
    return None


def _require_project(
    project_id: Optional[str] = None,
    required_role: str = "viewer",
    tool_name: str = "",
) -> str:
    """Return a project_id string or raise with a helpful message."""
    if not project_id and not os.environ.get("DRAPER_PROJECT_ID"):
        principal = _current_mcp_principal()
        if not principal.is_admin and len(principal.project_ids) == 1:
            project_id = principal.project_ids[0]
    p = _get_project(project_id)
    if not p:
        raise ValueError("No project selected. Pass project_id or set DRAPER_PROJECT_ID.")
    _check_mcp_project(p.project_id, required_role, tool_name)
    return p.project_id


def _safe(obj) -> Any:
    """Make objects JSON-serialisable."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return str(obj)
    return obj


def _require_mcp_admin() -> None:
    if not _current_mcp_principal().is_admin:
        raise AccessDeniedError("Admin MCP access required")


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = MCPServer(
    "Draper Marketing Pipeline",
    token_verifier=DraperMCPTokenVerifier(),
    auth=AuthSettings(
        issuer_url=os.environ.get("DRAPER_MCP_ISSUER_URL", "http://127.0.0.1:9000"),
        resource_server_url=os.environ.get("DRAPER_MCP_RESOURCE_URL", "http://127.0.0.1:9000/mcp"),
        required_scopes=["mcp:project"],
    ),
    instructions=(
        "You are an agent operating a marketing content pipeline. "
        "You can create and manage projects, generate social media content, "
        "review and approve it, publish to platforms (Twitter/LinkedIn via "
        "Typefully, Nostr), manage source materials and content ideas, "
        "trigger mining for new ideas, and view analytics. "
        "Most operations require a project_id — if none is given the "
        "current project is used."
    ),
)


# ===================================================================
# PROJECT TOOLS
# ===================================================================


@mcp.tool()
def list_projects() -> Dict:
    """List all marketing projects.

    Returns an array of project objects with id, name, and description.
    Use this to discover which projects exist before operating on one.
    """
    projects = PROJECT_MANAGER.list_projects()
    principal = _current_mcp_principal()
    if not principal.is_admin:
        allowed = set(principal.project_ids)
        projects = [project for project in projects if project.project_id in allowed]
    items = [
        {
            "project_id": p.project_id,
            "name": p.name,
            "slug": getattr(p, "slug", ""),
            "description": getattr(p, "description", ""),
        }
        for p in projects
    ]
    return {"count": len(items), "items": items}


@mcp.tool()
def get_current_project() -> Optional[Dict]:
    """Get the currently selected project.

    Returns the project that all operations default to when project_id
    is not specified. Returns null if no project is selected.
    """
    principal = _current_mcp_principal()
    if not principal.is_admin and len(principal.project_ids) == 1:
        p = PROJECT_MANAGER.get_project(principal.project_ids[0])
    else:
        p = _get_project()
    if not p:
        return None
    _check_mcp_project(p.project_id, "viewer", "get_current_project")
    return {
        "project_id": p.project_id,
        "name": p.name,
        "slug": getattr(p, "slug", ""),
        "description": getattr(p, "description", ""),
    }


@mcp.tool()
def set_current_project(project_id: str) -> Dict:
    """Set the active project for subsequent operations.

    Args:
        project_id: The project to make active (from list_projects).
    """
    _require_mcp_admin()
    p = PROJECT_MANAGER.get_project(project_id)
    if not p:
        raise ValueError(f"Project not found: {project_id}")
    PROJECT_MANAGER.set_current_project(project_id)
    return {"success": True, "project_id": project_id, "name": p.name}


@mcp.tool()
def create_project(name: str, description: str = "") -> Dict:
    """Create a new marketing project.

    Args:
        name: Human-readable project name (e.g. "Acme Corp").
        description: Optional project description.
    """
    _require_mcp_admin()
    p = PROJECT_MANAGER.create_project(name=name, description=description)
    return {"success": True, "project_id": p.project_id, "name": p.name}


@mcp.tool()
def delete_project(project_id: str) -> Dict:
    """Delete a project and all its data.

    Args:
        project_id: The project to delete.
    """
    _require_mcp_admin()
    ok = PROJECT_MANAGER.delete_project(project_id, confirm=True)
    if not ok:
        raise ValueError(f"Project not found: {project_id}")
    return {"success": True, "deleted": project_id}


# ===================================================================
# CONTENT GENERATION TOOLS
# ===================================================================


@mcp.tool()
def generate_content(
    project_id: Optional[str] = None,
    count: int = 3,
    platform: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict:
    """Generate marketing content using the configured LLM.

    Content is added to the review pipeline in 'pending_review' status.
    Use list_content to see it, then approve or decline.

    Args:
        project_id: Target project (defaults to current).
        count: Number of posts to generate (1-25, default 3).
        platform: Restrict to 'twitter' or 'linkedin'. Both if omitted.
        content_type: Optional type hint (post, thread, carousel).
    """
    pid = _require_project(project_id, "editor", "generate_content")
    count = max(1, min(25, count))
    platforms = [platform] if platform else None

    try:
        generator = LLMContentGenerator(project=PROJECT_MANAGER.get_project(pid))
        batch = generator.generate_batch(count=count, platforms=platforms)
        posts = batch.get("posts", []) if isinstance(batch, dict) else batch
    except Exception as e:
        print(f"MCP generation failed: {e}")
        return {"success": False, "error": "Generation failed"}

    review_ids = []
    for post in posts:
        post["project_id"] = pid
        if content_type:
            post["content_type"] = content_type
        record = FEEDBACK_MANAGER.post_content_for_review(post, "MCP")
        review_ids.append(record.get("review_id"))

    return {
        "success": True,
        "count": len(posts),
        "review_ids": review_ids,
    }


@mcp.tool()
def generate_long_form(
    project_id: Optional[str] = None,
    format: str = "blog",
    topic: Optional[str] = None,
) -> Dict:
    """Generate long-form marketing content (blog, email, landing page, etc).

    Args:
        project_id: Target project.
        format: One of: blog, email, landing_page, press_release, case_study.
        topic: Optional topic/focus for the content.
    """
    pid = _require_project(project_id, "editor", "generate_long_form")
    generator = LLMContentGenerator(project=PROJECT_MANAGER.get_project(pid))

    format_map = {
        "blog": generator.generate_blog_post,
        "email": generator.generate_email_newsletter,
        "landing_page": generator.generate_landing_page,
        "press_release": generator.generate_press_release,
        "case_study": generator.generate_case_study,
    }

    fn = format_map.get(format)
    if not fn:
        return {
            "success": False,
            "error": f"Unknown format '{format}'. Use: {', '.join(format_map)}",
        }

    try:
        result = fn(topic=topic) if topic else fn()
        content = result if isinstance(result, str) else str(result)
    except Exception as e:
        print(f"MCP long-form generation failed: {e}")
        return {"success": False, "error": "Generation failed"}

    post = {
        "project_id": pid,
        "platform": "long_form",
        "content_type": format,
        "content": content,
    }
    record = FEEDBACK_MANAGER.post_content_for_review(post, "MCP")

    return {
        "success": True,
        "review_id": record.get("review_id"),
        "format": format,
        "content_length": len(content),
    }


# ===================================================================
# CONTENT PIPELINE TOOLS
# ===================================================================


@mcp.tool()
def list_content(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List content items in the review pipeline.

    Args:
        project_id: Target project.
        status: Filter by status. One of: pending_review, approved,
                scheduled, needs_work, declined. Returns all if omitted.
        limit: Max items to return (default 20).
    """
    pid = _require_project(project_id, "viewer", "list_content")
    reviews = FEEDBACK_MANAGER._load_reviews()

    items = []
    for rid, rec in reviews.items():
        rec_project = rec.get("project_id") or rec.get("post_data", {}).get("project_id")
        if rec_project and rec_project != pid:
            continue
        if status and rec.get("status") != status:
            continue
        items.append(
            {
                "review_id": rid,
                "status": rec.get("status", "unknown"),
                "platform": rec.get("post_data", {}).get("platform", ""),
                "content_type": rec.get("post_data", {}).get("content_type", "post"),
                "content_preview": (rec.get("post_data", {}).get("content", "")[:200]),
                "created_at": rec.get("created_at", ""),
            }
        )
        if len(items) >= limit:
            break

    return {"count": len(items), "items": items}


@mcp.tool()
def get_content(review_id: str) -> Dict:
    """Get full details of a content item in the pipeline.

    Args:
        review_id: The review ID (ISO timestamp format).
    """
    record = _check_review_access(review_id, "viewer", "get_content")
    return record


def _resolve_approve_publish_default(record: Dict, publish: Optional[bool]) -> bool:
    """Resolve approve_content publish behavior from explicit input or project config."""
    if publish is not None:
        return publish

    project_id = _record_project_id(record)
    if not project_id:
        return True

    typefully_config = (PROJECT_MANAGER.get_project_secrets(project_id) or {}).get(
        "typefully", {}
    )
    if not isinstance(typefully_config, dict):
        return True

    return bool(typefully_config.get("auto_schedule", True))


@mcp.tool()
def approve_content(
    review_id: str,
    feedback: str = "",
    scheduled_date: Optional[str] = None,
    publish: Optional[bool] = None,
) -> Dict:
    """Approve content and optionally schedule it for publishing.

    ``publish=True`` always schedules, and ``publish=False`` always approves
    without scheduling. When ``publish`` is omitted, the tool reads the
    review's project ``typefully.auto_schedule`` setting: ``False`` resolves
    to approve-only, while ``True`` preserves historical approve-and-publish.
    Use ``publish_content`` later to push approve-only items to a provider.

    Args:
        review_id: The content to approve.
        feedback: Optional approval note.
        scheduled_date: ISO datetime for scheduling. Auto-schedules if omitted.
        publish: Explicit scheduling behavior override. If omitted, uses
            project ``typefully.auto_schedule``.
    """
    record = _check_review_access(review_id, "publisher", "approve_content")
    should_publish = _resolve_approve_publish_default(record, publish)

    try:
        approved = REVIEW_WORKFLOW.transition(
            review_id,
            ReviewAction.APPROVE,
            feedback=feedback,
        )
    except ReviewTransitionError as e:
        return {"success": False, "error": e.message, "code": e.code}

    if not should_publish:
        return {
            "success": True,
            "review_id": review_id,
            "status": approved.status.value,
            "scheduling": {"scheduled": False, "skipped": "publish=false"},
        }

    try:
        scheduled = REVIEW_WORKFLOW.transition(
            review_id,
            ReviewAction.SCHEDULE,
            feedback=feedback or "Approved and scheduled",
            scheduled_date=scheduled_date,
        )
    except ReviewTransitionError as e:
        return {
            "success": True,
            "review_id": review_id,
            "status": approved.status.value,
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


@mcp.tool()
def decline_content(
    review_id: str,
    feedback: str = "",
    tags: Optional[List[str]] = None,
) -> Dict:
    """Decline (reject) content in the pipeline.

    Args:
        review_id: The content to decline.
        feedback: Reason for declining.
        tags: Negative feedback tags (e.g. ['too_generic', 'weak_hook']).
    """
    _check_review_access(review_id, "editor", "decline_content")

    try:
        record = REVIEW_WORKFLOW.transition(
            review_id,
            ReviewAction.DECLINE,
            feedback=feedback,
            explicit_tags=",".join(tags) if tags else "",
        )
    except ReviewTransitionError as e:
        return {"success": False, "error": e.message, "code": e.code}

    return {"success": True, "review_id": review_id, "status": record.status.value}


@mcp.tool()
async def request_fix(
    review_id: str,
    feedback: str = "",
    tags: Optional[List[str]] = None,
) -> Dict:
    """Mark content as needing work and auto-fix it via LLM.

    The content is sent back through the LLM with the feedback, then
    returned to pending_review status.

    Args:
        review_id: The content to fix.
        feedback: What to fix.
        tags: Feedback tags (e.g. ['too_long', 'tone_off']).
    """
    _check_review_access(review_id, "editor", "request_fix")

    try:
        REVIEW_WORKFLOW.transition(
            review_id,
            ReviewAction.NEEDS_WORK,
            feedback=feedback,
            explicit_tags=",".join(tags) if tags else "",
        )
        job = REVIEW_WORKFLOW.apply_auto_fix(
            review_id, feedback=feedback, job_queue=JOB_QUEUE
        )
    except ReviewTransitionError as e:
        return {"success": False, "error": e.message, "code": e.code}
    except Exception as e:
        print(f"MCP auto-fix failed for {review_id}: {e}")
        return {"success": False, "error": "Auto-fix failed"}

    return {
        "success": True,
        "review_id": review_id,
        "auto_fix_status": "queued",
        "job_id": job["job_id"],
    }


# ===================================================================
# SOURCE MATERIAL TOOLS
# ===================================================================


@mcp.tool()
def add_source_material(
    project_id: Optional[str] = None,
    title: str = "",
    url: Optional[str] = None,
    text_content: Optional[str] = None,
    note: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict:
    """Add a source material to the Idea Lab.

    Source materials are inputs for idea generation — URLs, text excerpts,
    or notes. The type is auto-detected from what you provide.

    Args:
        project_id: Target project.
        title: Material title.
        url: URL to fetch content from.
        text_content: Text body to use as content.
        note: Additional notes.
        tags: Tags for categorization.
    """
    pid = _require_project(project_id, "editor", "add_source_material")
    result = IDEA_LAB.add_source_material(
        project_id=pid,
        title=title,
        url=url,
        text_content=text_content,
        note=note,
        tags=",".join(tags) if tags else None,
    )
    return _safe(result)


@mcp.tool()
def list_source_materials(
    project_id: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List source materials in the Idea Lab.

    Args:
        project_id: Target project.
        limit: Max items to return.
    """
    pid = _require_project(project_id, "viewer", "list_source_materials")
    records = IDEA_LAB.list_source_material(project_id=pid, limit=limit)
    return {"count": len(records), "items": [_safe(r) for r in records]}


@mcp.tool()
def get_source_material(material_id: str) -> Dict:
    """Get a source material by ID.

    Args:
        material_id: The material ID (sm_* format).
    """
    mat = _check_source_material_access(material_id, "viewer", "get_source_material")
    return _safe(mat)


@mcp.tool()
def enrich_source_material(material_id: str) -> Dict:
    """Enrich a source material — fetch URL content, extract key points, auto-tag.

    Args:
        material_id: The material to enrich.
    """
    _check_source_material_access(material_id, "editor", "enrich_source_material")
    return _safe(IDEA_LAB.enrich_source_material(material_id))


@mcp.tool()
def enrich_all_materials(project_id: Optional[str] = None) -> Dict:
    """Enrich all pending source materials for a project.

    Args:
        project_id: Target project.
    """
    pid = _require_project(project_id, "editor", "enrich_all_materials")
    return _safe(IDEA_LAB.enrich_all_pending(pid))


@mcp.tool()
def delete_source_material(material_id: str) -> Dict:
    """Delete a source material.

    Args:
        material_id: The material to delete.
    """
    _check_source_material_access(material_id, "editor", "delete_source_material")
    ok = IDEA_LAB.delete_source_material(material_id)
    return {"success": ok, "deleted": material_id if ok else None}


# ===================================================================
# CONTENT IDEAS TOOLS
# ===================================================================


@mcp.tool()
def generate_ideas(
    project_id: Optional[str] = None,
    material_id: Optional[str] = None,
) -> Dict:
    """Generate content ideas from source materials.

    If material_id is given, generates ideas from that specific material.
    Otherwise generates ideas from all enriched materials in the project.

    Args:
        project_id: Target project.
        material_id: Optional specific source material to use.
    """
    pid = _require_project(project_id, "editor", "generate_ideas")

    if material_id:
        material = _check_source_material_access(material_id, "editor", "generate_ideas")
        if material.project_id != pid:
            raise AccessDeniedError("Source material does not belong to the requested project")
        return _safe(IDEA_LAB.generate_ideas_from_material(material_id, pid))
    return _safe(IDEA_LAB.generate_ideas_for_project(pid))


@mcp.tool()
def add_content_idea(
    project_id: Optional[str] = None,
    title: str = "",
    hook: Optional[str] = None,
    platforms: Optional[List[str]] = None,
    content_pillar: Optional[str] = None,
    suggested_format: Optional[str] = None,
    tags: Optional[List[str]] = None,
    rationale: Optional[str] = None,
    source_material_id: Optional[str] = None,
) -> Dict:
    """Manually add a content idea.

    Args:
        project_id: Target project.
        title: Idea title.
        hook: Hook or angle for the content.
        platforms: Target platforms (e.g. ['twitter', 'linkedin']).
        content_pillar: Content pillar (e.g. 'thought-leadership').
        suggested_format: Format hint (e.g. 'thread', 'carousel').
        tags: Categorization tags.
        rationale: Why this idea is worth pursuing.
        source_material_id: Optional linked source material.
    """
    pid = _require_project(project_id, "editor", "add_content_idea")
    result = IDEA_LAB.add_content_idea(
        project_id=pid,
        title=title,
        hook_angle=hook or "",
        target_platforms=platforms,
        content_pillar=content_pillar or "",
        rationale=rationale or "",
        suggested_format=suggested_format or "",
        source_material_ids=[source_material_id] if source_material_id else None,
        tags=",".join(tags) if tags else None,
    )
    return _safe(result)


@mcp.tool()
def list_content_ideas(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List content ideas in the Idea Lab.

    Args:
        project_id: Target project.
        status: Filter by status (draft, approved, rejected).
        limit: Max items to return.
    """
    pid = _require_project(project_id, "viewer", "list_content_ideas")
    records = IDEA_LAB.list_content_ideas(project_id=pid, status=status, limit=limit)
    return {"count": len(records), "items": [_safe(r) for r in records]}


@mcp.tool()
def get_content_idea(idea_id: str) -> Dict:
    """Get a content idea by ID.

    Args:
        idea_id: The idea ID (ci_* format).
    """
    idea = _check_content_idea_access(idea_id, "viewer", "get_content_idea")
    return _safe(idea)


@mcp.tool()
def evaluate_idea(
    idea_id: str,
    status: str,
    feedback: Optional[str] = None,
) -> Dict:
    """Evaluate a content idea — approve or reject it.

    Args:
        idea_id: The idea to evaluate.
        status: New status — 'approved' or 'rejected'.
        feedback: Optional evaluation feedback.
    """
    _check_content_idea_access(idea_id, "editor", "evaluate_idea")
    return _safe(IDEA_LAB.evaluate_content_idea(idea_id, status, feedback))


@mcp.tool()
def approve_and_generate_from_idea(
    idea_id: str,
    project_id: Optional[str] = None,
    target_platforms: Optional[List[str]] = None,
) -> Dict:
    """Approve an idea and auto-generate content from it.

    The idea is marked approved, then content is generated for each
    target platform and added to the review pipeline.

    Args:
        idea_id: The idea to approve and generate from.
        project_id: Target project.
        target_platforms: Platforms to generate for (default: idea's platforms).
    """
    pid = _require_project(project_id, "editor", "approve_and_generate_from_idea")
    idea = _check_content_idea_access(idea_id, "editor", "approve_and_generate_from_idea")
    if idea.project_id != pid:
        raise AccessDeniedError("Content idea does not belong to the requested project")
    platforms = ",".join(target_platforms) if target_platforms else None
    result = IDEA_LAB.approve_and_generate_content(
        idea_id=idea_id,
        project_id=pid,
        target_platforms=platforms,
    )
    return _safe(result)


@mcp.tool()
def delete_content_idea(idea_id: str) -> Dict:
    """Delete a content idea.

    Args:
        idea_id: The idea to delete.
    """
    _check_content_idea_access(idea_id, "editor", "delete_content_idea")
    ok = IDEA_LAB.delete_content_idea(idea_id)
    return {"success": ok, "deleted": idea_id if ok else None}


# ===================================================================
# MINING TOOLS
# ===================================================================


@mcp.tool()
def run_mining(project_id: Optional[str] = None) -> Dict:
    """Run the full mining pipeline: enrich all materials, then generate ideas.

    This is the one-shot 'make ideas from my materials' operation.

    Args:
        project_id: Target project.
    """
    pid = _require_project(project_id, "editor", "run_mining")

    enrich_result = IDEA_LAB.enrich_all_pending(pid)
    ideas_result = IDEA_LAB.generate_ideas_for_project(pid)

    return {
        "success": True,
        "enrichment": {
            "enriched": enrich_result.get("enriched", 0),
            "skipped": enrich_result.get("skipped", 0),
            "errors": enrich_result.get("errors", 0),
        },
        "ideas": {
            "generated": ideas_result.get("generated", 0),
            "skipped": ideas_result.get("skipped", 0),
            "errors": ideas_result.get("errors", 0),
        },
    }


# ===================================================================
# PUBLISHING TOOLS
# ===================================================================


@mcp.tool()
def publish_content(
    review_id: str,
    platform: Optional[str] = None,
    scheduled_at: Optional[str] = None,
) -> Dict:
    """Publish content directly to a platform.

    Schedules the item to the configured provider (Typefully/Late/Nostr).
    If the record is still in ``pending_review``, this chains APPROVE then
    SCHEDULE so MCP clients can move freshly generated content from
    pending to scheduled in one call (the pre-migration one-shot
    behavior). If the record is already ``approved``, only SCHEDULE runs.
    Records in any other status (e.g. declined, scheduled) raise
    INVALID_TRANSITION.

    Args:
        review_id: The content to publish.
        platform: Override platform ('twitter', 'linkedin', 'nostr').
        scheduled_at: ISO datetime for scheduling. Publishes now if omitted.
    """
    record = _check_review_access(review_id, "publisher", "publish_content")

    fallback = platform or record.get("post_data", {}).get("platform", "twitter")

    try:
        if record.get("status") == "pending_review":
            REVIEW_WORKFLOW.transition(review_id, ReviewAction.APPROVE)
        scheduled = REVIEW_WORKFLOW.transition(
            review_id,
            ReviewAction.SCHEDULE,
            scheduled_date=scheduled_at,
            platform=fallback,
        )
    except ReviewTransitionError as e:
        return {
            "success": False,
            "error": e.message,
            "code": e.code,
            "provider": None,
        }

    return {
        "success": True,
        "provider": scheduled.raw.get("published_via"),
        "draft_id": scheduled.raw.get("draft_id"),
        "url": scheduled.raw.get("draft_url"),
        "error": None,
    }


@mcp.tool()
def list_scheduled_posts(
    project_id: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List scheduled/published posts.

    Args:
        project_id: Target project.
        limit: Max items to return.
    """
    pid = _require_project(project_id, "viewer", "list_scheduled_posts")
    records = STORE.list_scheduled_records(project_id=pid)[:limit]
    return {"count": len(records), "items": [_safe(r) for r in records]}


# ===================================================================
# ANALYTICS TOOLS
# ===================================================================


@mcp.tool()
def get_analytics(project_id: Optional[str] = None) -> Dict:
    """Get analytics overview for a project.

    Returns content counts by status, platform breakdown, and
    recent performance data.

    Args:
        project_id: Target project.
    """
    pid = _require_project(project_id, "viewer", "get_analytics")
    reviews = FEEDBACK_MANAGER._load_reviews()
    stats = FEEDBACK_MANAGER.get_stats()

    platform_breakdown = {}
    status_counts = {
        "pending_review": 0,
        "approved": 0,
        "scheduled": 0,
        "needs_work": 0,
        "declined": 0,
    }

    project_items = 0
    for rid, rec in reviews.items():
        rec_pid = rec.get("project_id") or rec.get("post_data", {}).get("project_id")
        if rec_pid and rec_pid != pid:
            continue
        project_items += 1
        st = rec.get("status", "pending_review")
        status_counts[st] = status_counts.get(st, 0) + 1
        plat = rec.get("post_data", {}).get("platform", "unknown")
        if plat not in platform_breakdown:
            platform_breakdown[plat] = 0
        platform_breakdown[plat] += 1

    result = {
        "project_id": pid,
        "total_content": project_items,
        "by_status": status_counts,
        "by_platform": platform_breakdown,
    }
    if _current_mcp_principal().is_admin:
        result["global_stats"] = stats
    return result


@mcp.tool()
def sync_analytics(project_id: Optional[str] = None) -> Dict:
    """Sync analytics data from Typefully and other providers.

    Triggers a background sync of engagement metrics.
    """
    pid = _require_project(project_id, "publisher", "sync_analytics")
    job = JOB_QUEUE.enqueue(
        "sync_analytics",
        project_id=pid,
        payload={"project_id": pid},
    )
    return {"success": True, "queued": True, "job_id": job["job_id"]}


# ===================================================================
# JOB QUEUE TOOLS
# ===================================================================


@mcp.tool()
def list_jobs(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List background jobs.

    Args:
        status: Filter by status (pending, running, completed, failed, cancelled).
        limit: Max items to return.
    """
    principal = _current_mcp_principal()
    if project_id:
        _check_mcp_project(project_id, "viewer", "list_jobs")
        records = STORE.list_job_records(project_id=project_id, status=status, limit=limit)
    elif principal.is_admin:
        records = STORE.list_job_records(status=status, limit=limit)
    elif len(principal.project_ids) == 1:
        pid = principal.project_ids[0]
        _check_mcp_project(pid, "viewer", "list_jobs")
        records = STORE.list_job_records(project_id=pid, status=status, limit=limit)
    else:
        raise AccessDeniedError("Pass project_id when this token has multiple project roles")
    return {"count": len(records), "items": [_safe(r) for r in records]}


@mcp.tool()
def get_job_status(job_id: str) -> Dict:
    """Get the status of a background job.

    Args:
        job_id: The job ID to check.
    """
    record = _check_job_access(job_id, "viewer", "get_job_status")
    return _safe(record)


@mcp.tool()
def cancel_job(job_id: str) -> Dict:
    """Cancel a pending or running job.

    Args:
        job_id: The job to cancel.
    """
    _check_job_access(job_id, "publisher", "cancel_job")
    record = STORE.cancel_job(job_id)
    if not record:
        raise ValueError(f"Cannot cancel job: {job_id}")
    return {"success": True, "job_id": job_id}


# ===================================================================
# PROJECT CONFIGURATION TOOLS
# ===================================================================


@mcp.tool()
def get_content_plan(project_id: Optional[str] = None) -> Dict:
    """Get the content plan for a project.

    Returns the markdown content plan with weekly themes, pillars,
    and content types.

    Args:
        project_id: Target project.
    """
    pid = _require_project(project_id, "viewer", "get_content_plan")
    content = PROJECT_MANAGER.get_content_plan(pid)
    return {"project_id": pid, "content_plan": content or None}


@mcp.tool()
def update_content_plan(
    project_id: Optional[str] = None,
    content: str = "",
) -> Dict:
    """Update the content plan for a project.

    Args:
        project_id: Target project.
        content: Full markdown content plan.
    """
    pid = _require_project(project_id, "editor", "update_content_plan")
    PROJECT_MANAGER.save_content_plan(pid, content)
    plan_path = DATA_DIR / "projects" / pid / "content_plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(content)
    return {"success": True, "project_id": pid}


@mcp.tool()
def get_brand_voice(project_id: Optional[str] = None) -> Dict:
    """Get the brand voice guidelines for a project.

    Args:
        project_id: Target project.
    """
    pid = _require_project(project_id, "viewer", "get_brand_voice")
    voice_path = DATA_DIR / "projects" / pid / "brand_voice.md"
    if voice_path.exists():
        return {"project_id": pid, "brand_voice": voice_path.read_text()}
    return {"project_id": pid, "brand_voice": None}


@mcp.tool()
def update_brand_voice(
    project_id: Optional[str] = None,
    content: str = "",
) -> Dict:
    """Update the brand voice guidelines.

    Args:
        project_id: Target project.
        content: Brand voice markdown content.
    """
    pid = _require_project(project_id, "editor", "update_brand_voice")
    voice_path = DATA_DIR / "projects" / pid / "brand_voice.md"
    voice_path.parent.mkdir(parents=True, exist_ok=True)
    voice_path.write_text(content)
    return {"success": True, "project_id": pid}


@mcp.tool()
def get_project_settings(project_id: Optional[str] = None) -> Dict:
    """Get project settings including integrations and posting strategy.

    Args:
        project_id: Target project.
    """
    pid = _require_project(project_id, "owner", "get_project_settings")
    settings = PROJECT_MANAGER.get_project_settings(pid)
    return {"project_id": pid, "settings": settings}


# ===================================================================
# HEALTH / STATUS
# ===================================================================


@mcp.tool()
def get_system_status() -> Dict:
    """Get system health and configuration status.

    Returns service availability, project count, and pipeline summary.
    """
    principal = _current_mcp_principal()
    projects = PROJECT_MANAGER.list_projects()
    current = _get_project()
    if not principal.is_admin:
        allowed = set(principal.project_ids)
        projects = [project for project in projects if project.project_id in allowed]
        if len(principal.project_ids) == 1:
            current = PROJECT_MANAGER.get_project(principal.project_ids[0])
            reviews = STORE.list_review_records(project_id=principal.project_ids[0])
            stats = {
                "total": len(reviews),
                "pending": sum(1 for r in reviews if r.get("status") == "pending_review"),
                "approved": sum(1 for r in reviews if r.get("status") == "approved"),
                "scheduled": sum(1 for r in reviews if r.get("status") == "scheduled"),
                "rejected": sum(1 for r in reviews if r.get("status") in {"declined", "rejected"}),
            }
            job_stats = {
                "total": len(
                    STORE.list_job_records(project_id=principal.project_ids[0], limit=1000)
                )
            }
        else:
            stats = {"total": None}
            job_stats = {"total": None}
    else:
        stats = FEEDBACK_MANAGER.get_stats()
        job_stats = STORE.get_job_stats()

    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_typefully = bool(os.environ.get("TYPEFULLY_API_KEY"))

    return {
        "status": "ok",
        "project_count": len(projects),
        "current_project": current.project_id if current else None,
        "pipeline": stats,
        "job_queue": job_stats,
        "llm_available": has_anthropic or has_openai,
        "publishing_available": has_typefully,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args():
    parser = argparse.ArgumentParser(description="Draper MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="Port for streamable-http transport (default: 9000)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for streamable-http transport (default: 127.0.0.1)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    if args.transport == "streamable-http":
        has_env_token = bool(
            os.environ.get("DRAPER_MCP_TOKEN")
            or os.environ.get("DRAPER_MCP_ADMIN_TOKEN")
            or os.environ.get("DRAPER_DASHBOARD_TOKEN")
            or os.environ.get("DASHBOARD_API_TOKEN")
        )
        has_stored_mcp_token = any(
            token.get("mcp_enabled") and not token.get("revoked_at")
            for token in STORE.list_access_tokens()
        )
        if not has_env_token and not has_stored_mcp_token:
            raise RuntimeError(
                "Refusing to start streamable-http MCP without a bearer token. "
                "Set DRAPER_MCP_TOKEN with DRAPER_MCP_PROJECT_ID, set "
                "DRAPER_MCP_ADMIN_TOKEN, or create a project token with mcp_enabled."
            )
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
