"""Request-ID middleware: tags every request with an X-Request-ID.

Generates a 32-char hex server-side when the client did not supply one.
Client-supplied IDs are accepted (truncated to 128 chars + control
characters stripped) for log correlation only — never used for auth.
"""

from __future__ import annotations

import re
import uuid
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response


_CLIENT_ID_MAX_LEN = 128
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_client_id(raw: str) -> str:
    if not raw:
        return ""
    cleaned = _CONTROL_CHAR_RE.sub("", raw)
    return cleaned[:_CLIENT_ID_MAX_LEN]


class RequestIdMiddleware:
    """Affixes an ``X-Request-ID`` header on every request/response pair."""

    async def __call__(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        from services.observability import _request_id_ctx

        client_supplied = request.headers.get("X-Request-ID") or request.headers.get(
            "x-request-id"
        )
        sanitized = _sanitize_client_id(client_supplied) if client_supplied else ""
        request_id = sanitized if sanitized else uuid.uuid4().hex
        request.state.request_id = request_id
        token = _request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            _request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


def current_request_id() -> str:
    from services.observability import current_request_id as _impl

    return _impl()


__all__ = ["RequestIdMiddleware", "current_request_id"]
