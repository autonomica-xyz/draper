"""Project-management routes extracted from ``unified_dashboard.py:main()``.

Each route body is a verbatim copy of the corresponding inline closure with
the same mechanical substitutions applied across the plan:

* ``@app.<method>`` decorators become ``@router.<method>``.
* ``dashboard_instance.<collaborator>`` becomes ``Depends(get_<collaborator>)``
  (or ``container.<collaborator>`` via ``Depends(get_container)`` for
  one-off attributes such as ``resolve_record_project_id``).

The default brand-voice template (``DEFAULT_BRAND_VOICE_TEMPLATE`` below) is
the source-of-truth copy now that Plan 03-04 has retired the monolith.
``read_limited_utf8_upload`` is imported from ``dashboard.routes._helpers``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    model_validator,
)

from dashboard.dependencies import (
    get_container,
    get_project_manager,
    get_store,
)
from dashboard.middleware.auth import (
    _require_project_access,
    _visible_projects,
)
from dashboard.routes._helpers import (
    ALLOWED_PLATFORMS,
    ALLOWED_PROVIDERS,
    MAX_CONTENT_PLAN_CHARS,
    MAX_CONTENT_PLAN_UPLOAD_BYTES,
    read_limited_utf8_upload,
    validation_error_message,
)

router = APIRouter()


class ContentPlanRequest(BaseModel):
    """Validated markdown payload for project content plans."""

    model_config = ConfigDict(extra="ignore")

    content: str = Field(default="", max_length=MAX_CONTENT_PLAN_CHARS)


class ProviderMappingRequest(RootModel[Dict[str, str]]):
    """Validated per-platform publishing provider map."""

    @model_validator(mode="after")
    def validate_mapping(self):
        for platform, provider in self.root.items():
            platform_key = str(platform).lower().strip()
            provider_name = str(provider).lower().strip()
            if platform_key not in ALLOWED_PLATFORMS:
                raise ValueError(f"unsupported platform: {platform}")
            if provider_name not in ALLOWED_PROVIDERS:
                raise ValueError(f"unsupported provider: {provider}")
        self.root = {
            ("twitter" if str(platform).lower().strip() == "x" else str(platform).lower().strip()):
            str(provider).lower().strip()
            for platform, provider in self.root.items()
        }
        return self

DEFAULT_BRAND_VOICE_TEMPLATE = """# Brand Voice

## Core Identity

**[Project Name] = [One-line description of what you do]**

Describe your core identity and mission in 1-2 sentences.

## Tone and Personality

### Primary Voice Characteristics
- **[Trait 1]**: Description of this voice trait
- **[Trait 2]**: Description of this voice trait
- **[Trait 3]**: Description of this voice trait

### Voice Rules
- Use first person plural ("we", "our") when discussing the brand
- Use second person ("you", "your") when addressing user scenarios
- Avoid corporate jargon
- Prefer specific technical terms over vague language

### Anti-Patterns (What We Avoid)
- Vague claims without evidence
- Fear-mongering without solutions
- Over-promising
- Marketing buzzwords
- Generic motivational content

## Core Values

### 1. [Value Name]
Description of this core value and how it manifests in content.

### 2. [Value Name]
Description of this core value and how it manifests in content.

### 3. [Value Name]
Description of this core value and how it manifests in content.

## Communication Style

### Do's
- Use technical specificity
- Include concrete numbers and data
- Provide diagrams and reference architectures
- Admit tradeoffs honestly

### Don'ts
- Use vague superlatives
- Make unfounded guarantees
- Hide complexity
- Over-format with emojis

## Audience Segments

### [Segment 1]
**What they care about**: Key concerns
**How we speak to them**: Tone and approach
**Technical depth**: Level of detail

### [Segment 2]
**What they care about**: Key concerns
**How we speak to them**: Tone and approach
**Technical depth**: Level of detail

## Sample Voice Examples

### Good (Our Voice)
"Example of content that matches our voice."

### Bad (Not Our Voice)
"Example of content that does NOT match our voice."

## Platform-Specific Adaptations

### LinkedIn
- Longer-form, narrative-driven
- Professional tone with technical depth

### Twitter/X
- Dense, punchy threads
- Contrarian takes and code snippets

### Blog
- Educational deep-dives
- Reference architectures and tutorials
"""


@router.get("/api/projects")
async def list_projects(request: Request):
    projects = _visible_projects(request)
    return {
        "projects": [
            {
                "project_id": p.project_id,
                "name": p.name,
                "description": p.description,
                "created_at": p.created_at,
            }
            for p in projects
        ]
    }


@router.post("/api/projects")
async def create_project(request: Request, pm: Any = Depends(get_project_manager)):
    data = await request.json()
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()

    if not name:
        return {"success": False, "error": "Project name is required"}

    try:
        project = pm.create_project(name=name, description=description)
        return {
            "success": True,
            "project": {
                "project_id": project.project_id,
                "name": project.name,
                "description": project.description,
            },
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"Project creation failed: {e}")
        return {"success": False, "error": "Failed to create project"}


@router.delete("/api/projects/{project_id}")
async def delete_project(
    project_id: str,
    pm: Any = Depends(get_project_manager),
):
    try:
        success = pm.delete_project(project_id, confirm=True)
        if success:
            return {"success": True}
        else:
            return {"success": False, "error": "Project not found"}
    except Exception as e:
        print(f"Project deletion failed for {project_id}: {e}")
        return {"success": False, "error": "Failed to delete project"}


@router.get("/api/projects/{project_id}/access/tokens")
async def list_project_access_tokens(
    project_id: str,
    request: Request,
    store: Any = Depends(get_store),
):
    _require_project_access(request, project_id, "owner")
    tokens = store.list_access_tokens(project_id=project_id)
    return {
        "success": True,
        "tokens": [
            {k: v for k, v in token.items() if k != "token"}
            for token in tokens
            if not token.get("revoked_at")
        ],
    }


@router.post("/api/projects/{project_id}/access/tokens")
async def create_project_access_token(
    project_id: str,
    request: Request,
    store: Any = Depends(get_store),
):
    _require_project_access(request, project_id, "owner")
    try:
        body = await request.json()
    except Exception:
        body = {}
    from services.access_control import normalize_role

    role = normalize_role(body.get("role", "viewer"))
    token_record = store.create_access_token(
        label=(body.get("label") or f"{project_id} {role} token").strip(),
        project_roles={project_id: role},
        mcp_enabled=bool(body.get("mcp_enabled", False)),
        expires_at=body.get("expires_at"),
    )
    return {"success": True, "token": token_record}


@router.delete("/api/projects/{project_id}/access/tokens/{token_id}")
async def revoke_project_access_token(
    project_id: str,
    token_id: str,
    request: Request,
    store: Any = Depends(get_store),
):
    _require_project_access(request, project_id, "owner")
    token = store.get_access_token(token_id)
    if not token or project_id not in (token.get("project_roles") or {}):
        return JSONResponse(
            status_code=404, content={"success": False, "error": "Token not found"}
        )
    return {"success": store.revoke_access_token(token_id)}


@router.get("/api/projects/{project_id}/mcp-config")
async def get_project_mcp_config(
    project_id: str,
    request: Request,
    store: Any = Depends(get_store),
):
    _require_project_access(request, project_id, "owner")
    return {
        "success": True,
        "config": store.get_project_mcp_config(project_id),
    }


@router.post("/api/projects/{project_id}/mcp-config")
async def save_project_mcp_config(
    project_id: str,
    request: Request,
    store: Any = Depends(get_store),
):
    _require_project_access(request, project_id, "owner")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400, content={"success": False, "error": "Invalid JSON body"}
        )
    from services.access_control import ROLE_ORDER, normalize_role

    max_role = normalize_role(body.get("max_role", "viewer"))
    config = store.set_project_mcp_config(
        project_id,
        {
            "enabled": bool(body.get("enabled", False)),
            "allowed_tools": body.get("allowed_tools") or [],
            "max_role": max_role,
        },
    )
    return {"success": True, "config": config, "roles": list(ROLE_ORDER)}


@router.get("/api/projects/{project_id}/content-plan")
async def get_content_plan(
    project_id: str,
    pm: Any = Depends(get_project_manager),
):
    project_data_dir = pm.get_project_data_dir(project_id)
    content_plan_file = project_data_dir / "content_plan.md"

    content = pm.get_content_plan(project_id)
    if not content and not content_plan_file.exists():
        return {"content": "", "last_updated": None}

    last_updated = (
        datetime.fromtimestamp(content_plan_file.stat().st_mtime, tz=timezone.utc).isoformat()
        if content_plan_file.exists()
        else None
    )

    return {"content": content, "last_updated": last_updated}


@router.post("/api/projects/{project_id}/content-plan")
async def save_content_plan(
    project_id: str,
    request: Request,
    pm: Any = Depends(get_project_manager),
):
    try:
        body = ContentPlanRequest.model_validate(await request.json())
    except ValidationError as e:
        return {"success": False, "error": validation_error_message(e)}
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}
    content = body.content

    project_data_dir = pm.get_project_data_dir(project_id)
    project_data_dir.mkdir(parents=True, exist_ok=True)
    content_plan_file = project_data_dir / "content_plan.md"

    pm.save_content_plan(project_id, content)
    from data.atomic_io import atomic_write_text

    atomic_write_text(content_plan_file, content)

    return {"success": True, "last_updated": datetime.now(timezone.utc).isoformat()}


@router.get("/api/projects/{project_id}/content-plan/download")
async def download_content_plan(
    project_id: str,
    pm: Any = Depends(get_project_manager),
):
    from fastapi.responses import FileResponse, PlainTextResponse

    project_data_dir = pm.get_project_data_dir(project_id)
    content_plan_file = project_data_dir / "content_plan.md"

    if not content_plan_file.exists():
        content = pm.get_content_plan(project_id)
        if not content:
            return {"error": "No content plan found"}
        return PlainTextResponse(
            content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="{project_id}_content_plan.md"'
            },
        )

    return FileResponse(
        path=str(content_plan_file),
        filename=f"{project_id}_content_plan.md",
        media_type="text/markdown",
    )


@router.post("/api/projects/{project_id}/content-plan/upload")
async def upload_content_plan(
    project_id: str,
    request: Request,
    pm: Any = Depends(get_project_manager),
):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_CONTENT_PLAN_UPLOAD_BYTES + 4096:
                return {"success": False, "error": "Uploaded content plan is too large"}
        except ValueError:
            return {"success": False, "error": "Invalid content length"}

    form = await request.form()
    file = form.get("file")

    if not file:
        return {"success": False, "error": "No file provided"}

    try:
        content = await read_limited_utf8_upload(
            file,
            max_bytes=MAX_CONTENT_PLAN_UPLOAD_BYTES,
        )
    except ValueError as e:
        return {"success": False, "error": str(e)}
    try:
        body = ContentPlanRequest(content=content)
    except ValidationError as e:
        return {"success": False, "error": validation_error_message(e)}

    project_data_dir = pm.get_project_data_dir(project_id)
    project_data_dir.mkdir(parents=True, exist_ok=True)
    content_plan_file = project_data_dir / "content_plan.md"

    pm.save_content_plan(project_id, body.content)
    from data.atomic_io import atomic_write_text

    atomic_write_text(content_plan_file, body.content)

    return {"success": True, "last_updated": datetime.now(timezone.utc).isoformat()}


@router.get("/api/projects/{project_id}/brand-voice")
async def get_brand_voice(
    project_id: str,
    pm: Any = Depends(get_project_manager),
):
    project_data_dir = pm.get_project_data_dir(project_id)
    brand_voice_file = project_data_dir / "brand_voice.md"
    stored_content = pm.get_brand_voice(project_id)

    if not stored_content and not brand_voice_file.exists():
        return {
            "content": DEFAULT_BRAND_VOICE_TEMPLATE.strip(),
            "last_updated": None,
            "is_default": True,
        }

    content = stored_content or brand_voice_file.read_text()
    last_updated = (
        datetime.fromtimestamp(brand_voice_file.stat().st_mtime, tz=timezone.utc).isoformat()
        if brand_voice_file.exists()
        else None
    )

    return {"content": content, "last_updated": last_updated, "is_default": False}


@router.post("/api/projects/{project_id}/brand-voice")
async def save_brand_voice(
    project_id: str,
    request: Request,
    pm: Any = Depends(get_project_manager),
):
    data = await request.json()
    content = data.get("content", "")

    project_data_dir = pm.get_project_data_dir(project_id)
    project_data_dir.mkdir(parents=True, exist_ok=True)
    brand_voice_file = project_data_dir / "brand_voice.md"

    pm.save_brand_voice(project_id, content)
    from data.atomic_io import atomic_write_text

    atomic_write_text(brand_voice_file, content)

    return {"success": True, "last_updated": datetime.now(timezone.utc).isoformat()}


@router.get("/api/projects/{project_id}/social-profiles")
async def get_social_profiles(
    project_id: str,
    container: Any = Depends(get_container),
):
    project = container.project_manager.get_project(project_id)
    if not project:
        return {"error": "Project not found"}

    api_key = container.secret_service.get_api_key(project_id, "typefully")
    if not api_key:
        return {"profiles": [], "error": "Typefully API key is not configured"}

    try:
        from integrations.typefully import TypefullySyncClient

        with TypefullySyncClient(api_key=api_key) as client:
            typefully_accounts = client.get_social_accounts()
    except Exception as e:
        print(f"Error fetching Typefully accounts: {e}")
        return {"profiles": [], "error": "Failed to fetch Typefully accounts"}

    enabled_account_ids = set()
    settings_data = container.project_manager.get_project_settings(project_id)
    from data.models import ProjectSettings

    settings = ProjectSettings.from_dict(settings_data)
    enabled_account_ids = {p.account_id for p in settings.social_profiles if p.enabled}

    profiles = []
    for account in typefully_accounts:
        set_id = str(account.get("id", account.get("social_set_id", "")))
        handle = account.get("handle") or account.get("username", "")
        name = account.get("display_name") or account.get("name", "")

        for platform in ("twitter", "linkedin"):
            composite_id = f"typefully_{set_id}_{platform}"
            profiles.append(
                {
                    "account_id": composite_id,
                    "social_set_id": set_id,
                    "platform": platform,
                    "handle": handle,
                    "display_name": f"{name} ({platform.title()})",
                    "enabled": composite_id in enabled_account_ids,
                }
            )

    return {"profiles": profiles}


@router.post("/api/projects/{project_id}/social-profiles/toggle")
async def toggle_social_profile(
    project_id: str,
    request: Request,
    pm: Any = Depends(get_project_manager),
):
    data = await request.json()
    account_id = data.get("account_id")
    enabled = data.get("enabled", True)

    if not account_id:
        return {"error": "account_id required"}

    settings_data = pm.get_project_settings(project_id)

    from data.models import ProjectSettings, SocialProfile

    settings = ProjectSettings.from_dict(settings_data)

    profile_found = False
    for profile in settings.social_profiles:
        if profile.account_id == account_id:
            profile.enabled = enabled
            profile_found = True
            break

    if not profile_found and enabled:
        settings.social_profiles.append(
            SocialProfile(
                account_id=account_id,
                platform=data.get("platform", ""),
                handle=data.get("handle", ""),
                display_name=data.get("display_name", ""),
                enabled=True,
            )
        )

    pm.save_project_settings(project_id, settings.to_dict())

    return {"success": True}


@router.get("/api/projects/{project_id}/posting-strategy")
async def get_posting_strategy(
    project_id: str,
    pm: Any = Depends(get_project_manager),
):
    settings_data = pm.get_project_settings(project_id)
    if settings_data:
        from data.models import ProjectSettings

        settings = ProjectSettings.from_dict(settings_data)
        return {
            "default": settings.posting_strategy.to_dict(),
            "overrides": {k: v.to_dict() for k, v in settings.platform_overrides.items()},
        }

    from data.models import PostingStrategy

    return {"default": PostingStrategy().to_dict(), "overrides": {}}


@router.post("/api/projects/{project_id}/posting-strategy")
async def save_posting_strategy(
    project_id: str,
    request: Request,
    pm: Any = Depends(get_project_manager),
):
    data = await request.json()

    settings_data = pm.get_project_settings(project_id)

    from data.models import PostingStrategy, ProjectSettings

    settings = ProjectSettings.from_dict(settings_data)

    if "default" in data:
        settings.posting_strategy = PostingStrategy.from_dict(data["default"])

    if "overrides" in data:
        settings.platform_overrides = {
            k: PostingStrategy.from_dict(v) for k, v in data["overrides"].items()
        }

    pm.save_project_settings(project_id, settings.to_dict())

    return {"success": True}


@router.get("/api/projects/{project_id}/provider-mapping")
async def get_provider_mapping(
    project_id: str,
    pm: Any = Depends(get_project_manager),
):
    try:
        return {
            "success": True,
            "mapping": pm.get_provider_mapping(project_id),
        }
    except Exception as e:
        print(f"Provider mapping load failed for {project_id}: {e}")
        return {"success": False, "error": "Failed to load provider mapping"}


@router.post("/api/projects/{project_id}/provider-mapping")
async def save_provider_mapping(
    project_id: str,
    request: Request,
    pm: Any = Depends(get_project_manager),
):
    try:
        body = ProviderMappingRequest.model_validate(await request.json())
    except ValidationError as e:
        return {"success": False, "error": validation_error_message(e)}
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    pm.save_provider_mapping(project_id, body.root)

    return {"success": True}
