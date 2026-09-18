"""Shared form/redirect helpers and request-model constants for ``dashboard.routes.*``.

``validation_error_message`` is the byte-identical public name for the
``_validation_error_message`` helper that lived at
``unified_dashboard.py:232-247`` until Plan 03-04 retired that copy.
``pipeline_redirect`` returns the standard 303-redirect-to-/?tab=pipeline
response used by the review form routes.

The request-model constants (``ALLOWED_PLATFORMS``, ``ALLOWED_PROVIDERS``,
``MAX_CONTENT_PLAN_CHARS``, ``MAX_CONTENT_PLAN_UPLOAD_BYTES``) and the
``read_limited_utf8_upload`` helper live here so each route module that owns
a Pydantic request model can import them in isolation without reaching back
into the bootstrap module.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

from fastapi.requests import Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError


# Schedule-failure visibility (pending_review on publish fail)
try:
    from services.schedule_fail_visibility import apply as _apply_schedule_fail_visibility
    _apply_schedule_fail_visibility()
except Exception:
    pass



ALLOWED_PLATFORMS = {
    "twitter",
    "x",
    "linkedin",
    "nostr",
    "instagram",
    "tiktok",
    "youtube",
    "facebook",
    "threads",
    "bluesky",
    "pinterest",
    "reddit",
    "telegram",
}
ALLOWED_PROVIDERS = {"typefully", "late", "nostr"}
MAX_CONTENT_PLAN_CHARS = 12_000
MAX_CONTENT_PLAN_UPLOAD_BYTES = MAX_CONTENT_PLAN_CHARS * 4


def validation_error_message(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", []) if part != "body")
    msg = first.get("msg", "Invalid request")
    return f"{loc}: {msg}" if loc else msg


def pipeline_redirect(
    request: Optional[Request] = None,
    *,
    error_message: str = "",
) -> RedirectResponse:
    """Redirect back to the Pipeline tab, preserving the project context.

    Multi-project deploys navigate with ``?project=``; form POSTs to the
    review routes would otherwise dump the user back on the default project.
    ``error_message`` is URL-encoded into a ``schedule_error`` query param so
    failed approve+schedule attempts surface in the UI instead of vanishing.
    """
    project = ""
    if request is not None:
        project = request.query_params.get("project", "")
    url = "/?tab=pipeline"
    if error_message:
        url += f"&schedule_error={quote(error_message, safe='')}"
    if project:
        url += f"&project={project}"
    return RedirectResponse(url=url, status_code=303)


async def read_limited_utf8_upload(file_obj: Any, *, max_bytes: int) -> str:
    """Read at most max_bytes from an UploadFile-like object and decode UTF-8."""
    raw_content = await file_obj.read(max_bytes + 1)
    if len(raw_content) > max_bytes:
        raise ValueError("Uploaded content plan is too large")
    try:
        return raw_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Uploaded content plan must be UTF-8 text") from exc
