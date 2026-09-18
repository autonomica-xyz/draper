"""Rate-limit middleware extracted from ``unified_dashboard.py:main()``."""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from fastapi.requests import Request
from fastapi.responses import JSONResponse

from dashboard.middleware.auth import _request_principal


EXPENSIVE_ROUTE_LIMITS = {
    "/api/generate": (10, 60),
    "/generate": (5, 60),
    "/api/generate/image": (6, 60),
    "/api/generate/carousel": (6, 60),
    "/api/publish": (20, 60),
    "/api/jobs/run-next": (30, 60),
    "/api/ideas/materials/enrich-batch": (3, 300),
    "/api/ideas/generate-ideas-batch": (3, 300),
    "/api/ideas/mining/trigger": (3, 300),
}


def expensive_route_limit_for_path(path: str) -> Optional[Tuple[int, int]]:
    limit_config = EXPENSIVE_ROUTE_LIMITS.get(path)
    if limit_config:
        return limit_config
    if (
        path.endswith("/enrich")
        or path.endswith("/generate-ideas")
        or path.endswith("/approve-and-generate")
        or path.endswith("/visual")
        or path.endswith("/infographic")
        or path.endswith("/carousel")
    ):
        return (10, 60)
    if path.startswith("/schedule/") or path.endswith("/schedule") or path.endswith("/reschedule"):
        return (20, 60)
    if path.endswith("/content-plan/upload"):
        return (3, 300)
    return None


def _json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
    )


class RateLimiter:
    """Per-principal throttle for expensive mutation routes."""

    def __init__(
        self,
        limits: Optional[Dict[str, Tuple[int, int]]] = None,
        clock=time.monotonic,
    ) -> None:
        self.limits = dict(limits) if limits is not None else dict(EXPENSIVE_ROUTE_LIMITS)
        self._clock = clock
        self._buckets: Dict[Tuple[str, str], list[float]] = {}

    def _limit_for_path(self, path: str) -> Optional[Tuple[int, int]]:
        original = EXPENSIVE_ROUTE_LIMITS.get(path)
        if original:
            return original
        return expensive_route_limit_for_path(path)

    async def __call__(self, request: Request, call_next):
        if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        limit_config = self._limit_for_path(request.url.path)
        if not limit_config:
            return await call_next(request)
        max_requests, window_seconds = limit_config
        principal = _request_principal(request)
        bucket_key = (principal.token_id, request.url.path)
        now = self._clock()
        bucket = [
            timestamp
            for timestamp in self._buckets.get(bucket_key, [])
            if now - timestamp < window_seconds
        ]
        if len(bucket) >= max_requests:
            return _json_error(429, "Rate limit exceeded")
        bucket.append(now)
        self._buckets[bucket_key] = bucket
        return await call_next(request)


def client_ip(request: Request) -> str:
    """Best-effort socket peer IP for throttling.

    Deliberately ignores ``X-Forwarded-For``: it is client-controlled until a
    trusted proxy strips it, and honoring it would let an attacker rotate the
    throttle key at will. Behind a reverse proxy all callers share the proxy
    IP, which is the conservative choice for an internal dashboard.
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None
    return host or "unknown"


class LoginRateLimiter:
    """Per-client-IP failed-login throttle for ``POST /login``.

    Counts only *failed* attempts so honest users are never locked out by
    their own successful logins; a success clears the bucket. State is
    process-local, matching the ``RateLimiter`` trade-off for a single-instance
    dashboard.
    """

    def __init__(
        self,
        max_failures: int = 10,
        window_seconds: float = 300.0,
        clock=time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: Dict[str, list[float]] = {}

    def is_locked(self, request: Request) -> bool:
        """True when the client IP has exhausted its failure budget."""
        return self._failure_count(request) >= self.max_failures

    def record_failure(self, request: Request) -> None:
        """Record one failed login attempt for the client IP."""
        key = client_ip(request)
        now = self._clock()
        bucket = [
            timestamp
            for timestamp in self._failures.get(key, [])
            if now - timestamp < self.window_seconds
        ]
        bucket.append(now)
        self._failures[key] = bucket

    def reset(self, request: Request) -> None:
        """Clear the failure bucket after a successful login."""
        self._failures.pop(client_ip(request), None)

    def _failure_count(self, request: Request) -> int:
        key = client_ip(request)
        now = self._clock()
        bucket = [
            timestamp
            for timestamp in self._failures.get(key, [])
            if now - timestamp < self.window_seconds
        ]
        self._failures[key] = bucket
        return len(bucket)
