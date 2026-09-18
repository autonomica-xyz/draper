"""Provider-integration routes extracted from ``unified_dashboard.py:main()``.

Each route body is a verbatim copy of the corresponding inline closure with
the standard mechanical substitutions: ``@app.<method>`` becomes
``@router.<method>``, and ``dashboard_instance.<collaborator>`` becomes a
Depends-injected parameter (or ``container.<collaborator>`` via
``Depends(get_container)`` for one-off accesses).

Threat T-03-02-03 (information disclosure): the test routes return only
``{success, error}`` envelopes; the saved API key is never echoed back in
the response body.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Request

from dashboard.dependencies import get_secret_service

router = APIRouter()


@router.get("/api/projects/{project_id}/integrations")
async def get_integrations(
    project_id: str,
    request: Request,
    secret_service: Any = Depends(get_secret_service),
):
    typefully_prefs = secret_service.get_provider_config(
        project_id,
        "typefully",
    )
    per_project_key = typefully_prefs.get("api_key", "")
    env_key = os.environ.get("TYPEFULLY_API_KEY", "")

    response_data = {
        "configured": bool(per_project_key or env_key),
        "env_configured": bool(env_key),
        "api_key_configured": bool(per_project_key),
        "masked_api_key": secret_service.masked_suffix(per_project_key) if per_project_key else "",
        "drafts_enabled": typefully_prefs.get("drafts_enabled", True),
        "auto_schedule": typefully_prefs.get("auto_schedule", False),
    }

    return {"typefully": response_data}


@router.post("/api/projects/{project_id}/integrations/typefully")
async def save_typefully_integration(
    project_id: str,
    request: Request,
    secret_service: Any = Depends(get_secret_service),
):
    data = await request.json()

    secret_service.update_provider_config(
        project_id,
        "typefully",
        data,
        allowed_keys={
            "api_key",
            "drafts_enabled",
            "auto_schedule",
            "default_schedule_id",
        },
    )

    return {"success": True}


@router.post("/api/projects/{project_id}/integrations/typefully/test")
async def test_typefully_connection(
    project_id: str,
    secret_service: Any = Depends(get_secret_service),
):
    api_key = secret_service.get_api_key(project_id, "typefully")
    if not api_key:
        return {"success": False, "error": "Typefully API key is not configured"}

    try:
        from integrations.typefully import TypefullySyncClient

        with TypefullySyncClient(api_key=api_key) as client:
            accounts = client.get_social_accounts()
            return {
                "success": True,
                "message": f"Connected! Found {len(accounts)} account(s)",
                "accounts": accounts,
            }
    except Exception as e:
        print(f"Typefully connection test failed for {project_id}: {e}")
        return {"success": False, "error": "Typefully connection failed"}


@router.get("/api/projects/{project_id}/integrations/late")
async def get_late_integration(
    project_id: str,
    secret_service: Any = Depends(get_secret_service),
):
    late_config = secret_service.get_provider_config(project_id, "late")
    return {
        "configured": bool(late_config.get("api_key")),
        "api_key": secret_service.masked_suffix(late_config.get("api_key", "")),
        "auto_schedule": late_config.get("auto_schedule", False),
    }


@router.post("/api/projects/{project_id}/integrations/late")
async def save_late_integration(
    project_id: str,
    request: Request,
    secret_service: Any = Depends(get_secret_service),
):
    data = await request.json()

    secret_service.update_provider_config(
        project_id,
        "late",
        data,
        allowed_keys={"api_key", "auto_schedule"},
    )

    return {"success": True}


@router.post("/api/projects/{project_id}/integrations/late/test")
async def test_late_connection(
    project_id: str,
    secret_service: Any = Depends(get_secret_service),
):
    api_key = secret_service.get_api_key(
        project_id,
        "late",
        env_fallback=False,
    )
    if not api_key:
        return {"success": False, "error": "No API key configured"}

    try:
        from integrations.late_provider import LateProvider

        provider = LateProvider(api_key=api_key)
        accounts = provider.get_accounts()

        accounts_data = [
            {
                "id": acc.account_id,
                "platform": acc.platform,
                "handle": acc.handle,
                "display_name": acc.display_name,
                "enabled": acc.enabled,
            }
            for acc in accounts
        ]

        return {
            "success": True,
            "message": f"Connected! Found {len(accounts)} account(s)",
            "accounts": accounts_data,
        }
    except Exception as e:
        print(f"Late connection test failed for {project_id}: {e}")
        return {"success": False, "error": "Late connection failed"}


@router.get("/api/projects/{project_id}/integrations/nostr")
async def get_nostr_integration(
    project_id: str,
    secret_service: Any = Depends(get_secret_service),
):
    nostr_config = secret_service.get_provider_config(project_id, "nostr")
    return {
        "configured": bool(nostr_config.get("api_key")),
        "api_key": secret_service.masked_suffix(nostr_config.get("api_key", "")),
        "pubkey": nostr_config.get("pubkey", ""),
        "signing_mode": "server_key" if nostr_config.get("api_key") else "extension",
    }


@router.post("/api/projects/{project_id}/integrations/nostr")
async def save_nostr_integration(
    project_id: str,
    request: Request,
    secret_service: Any = Depends(get_secret_service),
):
    data = await request.json()

    secret_service.update_provider_config(
        project_id,
        "nostr",
        data,
        allowed_keys={"api_key", "pubkey"},
    )

    return {"success": True}


@router.post("/api/projects/{project_id}/integrations/nostr/test")
async def test_nostr_connection(
    project_id: str,
    secret_service: Any = Depends(get_secret_service),
):
    api_key = secret_service.get_api_key(
        project_id,
        "nostr",
        env_fallback=False,
    )
    if not api_key:
        return {"success": False, "error": "No Nostr private key configured"}

    try:
        from integrations.nostr_provider import NostrProvider

        provider = NostrProvider(private_key=api_key)
        accounts = provider.get_accounts()

        accounts_data = [
            {
                "id": acc.account_id,
                "platform": acc.platform,
                "handle": acc.handle,
                "display_name": acc.display_name,
                "enabled": acc.enabled,
            }
            for acc in accounts
        ]

        return {
            "success": True,
            "message": f"Connected! Found {len(accounts)} account(s)",
            "accounts": accounts_data,
        }
    except Exception as e:
        print(f"Nostr connection test failed for {project_id}: {e}")
        return {"success": False, "error": "Nostr connection failed"}
