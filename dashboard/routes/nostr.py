"""Nostr signing + publishing routes.

Backs the NIP-07 extension-signing flow (nos2x, Alby, ...). The primary UX
lives in the unified dashboard itself: pipeline cards carry a "Sign with
extension" button that calls these APIs from the main page. ``/nostr/sign``
remains as a standalone deep link for batch/remote signing.

* ``GET /nostr/sign`` serves the signing page. The page lists pending
  signing requests, asks the browser extension (``window.nostr``) to sign
  the prepared unsigned events, and POSTs the signed events back.
* ``POST .../signing-requests/{id}/signed`` verifies every signature
  server-side (schnorr + anti-tamper against the prepared event) before
  the request is scheduled for later publishing.

Roles: reads need ``viewer``, mutations need ``publisher``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from dashboard.dependencies import (
    get_nostr_signing,
    get_secret_service,
)
from dashboard.middleware.auth import (
    _default_project_id_for_request,
    _request_principal,
    _require_project_access,
)

from nostr import signing as nostr_signing
from services.nostr_signing_service import NostrSigningError

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

router = APIRouter()


def _raw_pinned_pubkey(secret_service: Any, project_id: Optional[str]) -> Optional[str]:
    """Project-pinned signer pubkey as configured (npub/hex) or ``None``."""
    if not project_id:
        return None
    config = secret_service.get_provider_config(project_id, "nostr")
    return str(config.get("pubkey") or os.getenv("NOSTR_PUBKEY") or "") or None


def _nostr_expected_pubkey(secret_service: Any, project_id: Optional[str]) -> Optional[str]:
    """Normalized project-pinned signer pubkey (hex) or ``None``."""
    raw = _raw_pinned_pubkey(secret_service, project_id)
    if not raw:
        return None
    try:
        return nostr_signing.expected_signer_pubkey(raw)
    except Exception:
        return None


@router.get("/nostr/sign", response_class=HTMLResponse)
async def nostr_sign_page(request: Request):
    """NIP-07 signing page; project comes from ?project= or the default."""
    project_id = request.query_params.get("project") or _default_project_id_for_request(request)
    if project_id:
        _require_project_access(request, project_id, "publisher")
    elif _request_principal(request).is_scoped:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "project_id is required"},
        )

    template = templates.get_template("nostr_sign.html")
    html = template.render(
        {
            "request": request,
            "project_id": project_id or "",
        }
    )
    return HTMLResponse(html)


@router.get("/api/projects/{project_id}/nostr/status")
async def get_nostr_status(
    project_id: str,
    request: Request,
    signing: Any = Depends(get_nostr_signing),
    secret_service: Any = Depends(get_secret_service),
):
    _require_project_access(request, project_id, "viewer")
    summary = signing.get_status_summary(project_id)
    summary["expected_pubkey"] = _nostr_expected_pubkey(secret_service, project_id) or summary.get(
        "expected_pubkey"
    )
    summary["project_id"] = project_id
    return {"success": True, **summary}


@router.get("/api/projects/{project_id}/nostr/signing-requests")
async def list_signing_requests(
    project_id: str,
    request: Request,
    status: str = "",
    review_id: str = "",
    signing: Any = Depends(get_nostr_signing),
):
    _require_project_access(request, project_id, "viewer")
    records = signing.store.list_nostr_request_records(
        project_id=project_id,
        status=status or None,
        review_id=review_id or None,
    )
    return {
        "success": True,
        "project_id": project_id,
        "requests": [_public_request(record) for record in records],
    }


@router.post("/api/projects/{project_id}/nostr/signing-requests")
async def create_signing_request(
    project_id: str,
    request: Request,
    signing: Any = Depends(get_nostr_signing),
):
    _require_project_access(request, project_id, "publisher")
    try:
        body = await request.json()
    except Exception:
        body = {}

    review_id = str(body.get("review_id") or "").strip()
    if not review_id:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "review_id is required"},
        )

    review = signing.store.get_review_record(review_id)
    if not review or review.get("project_id") != project_id:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "review not found"},
        )

    try:
        record = signing.create_request_for_review(
            review_id,
            scheduled_at=body.get("scheduled_at"),
            relays=body.get("relays"),
        )
    except NostrSigningError as exc:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": str(exc)},
        )

    return {"success": True, "request": _public_request(record)}


@router.post("/api/projects/{project_id}/nostr/signing-requests/{request_id}/signed")
async def accept_signed_events(
    project_id: str,
    request_id: str,
    request: Request,
    signing: Any = Depends(get_nostr_signing),
    secret_service: Any = Depends(get_secret_service),
):
    """Receive signed events from the NIP-07 extension and schedule them."""
    _require_project_access(request, project_id, "publisher")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "JSON body required"},
        )

    existing = signing.store.get_nostr_request_record(request_id)
    if not existing or existing.get("project_id") != project_id:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "signing request not found"},
        )

    signed_events = body.get("events")
    if not signed_events and body.get("event"):
        signed_events = [body["event"]]
    if not isinstance(signed_events, list) or not signed_events:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "signed event(s) required"},
        )

    expected_pubkey = _raw_pinned_pubkey(secret_service, project_id)

    try:
        record = signing.accept_signature(
            request_id,
            signed_events,
            expected_pubkey=expected_pubkey,
        )
    except NostrSigningError as exc:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": str(exc)},
        )

    return {"success": True, "request": _public_request(record)}


@router.post("/api/projects/{project_id}/nostr/signing-requests/{request_id}/cancel")
async def cancel_signing_request(
    project_id: str,
    request_id: str,
    request: Request,
    signing: Any = Depends(get_nostr_signing),
):
    _require_project_access(request, project_id, "publisher")
    existing = signing.store.get_nostr_request_record(request_id)
    if not existing or existing.get("project_id") != project_id:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "signing request not found"},
        )

    try:
        record = signing.cancel_request(request_id)
    except NostrSigningError as exc:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": str(exc)},
        )
    return {"success": True, "request": _public_request(record)}


@router.post("/api/projects/{project_id}/nostr/publish-due")
async def publish_due_nostr(
    project_id: str,
    request: Request,
    signing: Any = Depends(get_nostr_signing),
):
    """Manually sweep due signed events (the job queue also does this)."""
    _require_project_access(request, project_id, "publisher")
    results = signing.publish_due(project_id=project_id)
    safe_results = [
        r
        for r in results
        if (r.get("record") or {}).get("project_id") in {None, project_id}
    ]
    return {
        "success": True,
        "published": sum(1 for r in safe_results if r.get("success")),
        "results": safe_results,
    }


def _public_request(record: dict) -> dict:
    """Signing-request view safe for the dashboard (delegates to the service)."""
    from services.nostr_signing_service import public_request_view

    return public_request_view(record)
