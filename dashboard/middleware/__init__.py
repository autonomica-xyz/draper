"""Middleware package: security headers, CSRF, rate limit, auth, request ID."""

from dashboard.middleware.auth import (
    AuthMiddleware,
    _request_principal,
    infer_project_authz,
    role_by_method,
)
from dashboard.middleware.csrf import CSRFService
from dashboard.middleware.rate_limit import LoginRateLimiter, RateLimiter, client_ip
from dashboard.middleware.request_id import RequestIdMiddleware, current_request_id
from dashboard.middleware.security_headers import SecurityHeaders

__all__ = [
    "AuthMiddleware",
    "CSRFService",
    "LoginRateLimiter",
    "RateLimiter",
    "RequestIdMiddleware",
    "SecurityHeaders",
    "_request_principal",
    "client_ip",
    "current_request_id",
    "infer_project_authz",
    "role_by_method",
]
