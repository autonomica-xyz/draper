"""CSRF protection middleware extracted from ``unified_dashboard.py:main()``."""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi.requests import Request
from fastapi.responses import JSONResponse


class CSRFService:
    """Token-based CSRF protection for cookie-authenticated mutation requests."""

    def __init__(self) -> None:
        self._token: str = secrets.token_hex(32)
        self.rotate_token()

    def rotate_token(self) -> str:
        self._token = secrets.token_hex(32)
        return self._token

    def current_token(self) -> str:
        return self._token

    async def validate(self, request: Request) -> Optional[JSONResponse]:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        if request.url.path in ("/login", "/logout"):
            return None
        if getattr(request.state, "auth_transport", "") == "header":
            return None
        submitted = request.headers.get("x-csrf-token", "")
        if submitted and submitted == self._token:
            return None
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            body_bytes = await request.body()

            async def receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}

            request._receive = receive
            form_data = await request.form()
            request._receive = receive
            form_csrf = form_data.get("csrf_token", "")
            if form_csrf and form_csrf == self._token:
                return None
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "CSRF token missing or invalid"},
        )

    async def __call__(self, request: Request, call_next):
        result = await self.validate(request)
        if result is not None:
            return result
        return await call_next(request)
