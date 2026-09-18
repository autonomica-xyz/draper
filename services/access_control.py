"""Dashboard access-control helpers."""

import hashlib
import ipaddress
import os
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.parse import urlsplit

COOKIE_NAME = "draper_dashboard_token"
TOKEN_ENV_VARS = ("DRAPER_DASHBOARD_TOKEN", "DASHBOARD_API_TOKEN")
MIN_TOKEN_LENGTH = 16
ROLE_ORDER = ("viewer", "editor", "publisher", "owner")
ROLE_RANK = {role: idx for idx, role in enumerate(ROLE_ORDER)}
DEFAULT_SCOPED_ROLE = "viewer"


class AccessDeniedError(PermissionError):
    """Raised when an authenticated principal lacks required project access."""


@dataclass
class Principal:
    """Authenticated dashboard/API/MCP caller."""

    token_id: str
    label: str
    is_admin: bool = False
    project_roles: Dict[str, str] = field(default_factory=dict)
    mcp_enabled: bool = False
    token_prefix: str = ""

    @property
    def is_scoped(self) -> bool:
        return not self.is_admin

    @property
    def project_ids(self) -> list[str]:
        return sorted(self.project_roles)

    def role_for(self, project_id: Optional[str]) -> Optional[str]:
        if self.is_admin:
            return "owner"
        if not project_id:
            return None
        return self.project_roles.get(project_id)

    def has_project_role(self, project_id: Optional[str], required_role: str) -> bool:
        if self.is_admin:
            return True
        role = self.role_for(project_id)
        if not role:
            return False
        return ROLE_RANK.get(role, -1) >= ROLE_RANK.get(required_role, 999)

    def has_any_project_role(self, required_role: str) -> bool:
        if self.is_admin:
            return True
        required_rank = ROLE_RANK.get(required_role, 999)
        return any(ROLE_RANK.get(role, -1) >= required_rank for role in self.project_roles.values())

    def require_project_role(self, project_id: Optional[str], required_role: str) -> None:
        if not self.has_project_role(project_id, required_role):
            raise AccessDeniedError("Forbidden")

    def require_any_project_role(self, required_role: str) -> None:
        if not self.has_any_project_role(required_role):
            raise AccessDeniedError("Forbidden")


def configured_dashboard_token() -> str:
    for env_name in TOKEN_ENV_VARS:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return ""


def normalize_host(host: Optional[str]) -> str:
    if not host:
        return "127.0.0.1"
    host = host.strip()
    if "://" in host:
        host = urlsplit(host).hostname or host
    if host.startswith("[") and "]" in host:
        return host[1 : host.index("]")]
    if ":" in host and host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def is_loopback_host(host: Optional[str]) -> bool:
    host = normalize_host(host).lower()
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def hash_access_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_role(role: str, default: str = DEFAULT_SCOPED_ROLE) -> str:
    role = (role or default).strip().lower()
    return role if role in ROLE_RANK else default


def cap_role(role: str, max_role: str) -> str:
    role = normalize_role(role)
    max_role = normalize_role(max_role)
    if ROLE_RANK[role] <= ROLE_RANK[max_role]:
        return role
    return max_role


def roles_from_projects(project_ids: Iterable[str], role: str) -> Dict[str, str]:
    normalized_role = normalize_role(role)
    return {project_id: normalized_role for project_id in project_ids if project_id}


class DashboardAccessPolicy:
    """Token policy for local dashboard/API exposure."""

    def __init__(
        self,
        host: str = None,
        token: str = None,
        *,
        require_auth: Optional[bool] = None,
        allow_unauthenticated_local: Optional[bool] = None,
    ):
        self.host = normalize_host(host)
        self.token = token if token is not None else configured_dashboard_token()
        self._require_auth = (
            os.environ.get("DRAPER_REQUIRE_AUTH", "1").strip().lower() not in {"0", "false", "no"}
            if require_auth is None
            else require_auth
        )
        self._allow_unauthenticated_local = (
            os.environ.get("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "").strip().lower()
            in {"1", "true", "yes"}
            if allow_unauthenticated_local is None
            else allow_unauthenticated_local
        )

    @property
    def auth_enabled(self) -> bool:
        if self.token:
            return True
        if self.host_is_loopback and self._allow_unauthenticated_local:
            return False
        return self._require_auth

    @property
    def host_is_loopback(self) -> bool:
        return is_loopback_host(self.host)

    def validate_startup(self) -> None:
        """Fail closed unless auth is explicitly disabled for loopback development."""
        if not self.auth_enabled:
            return
        if not self.token:
            raise RuntimeError(
                "Refusing to start dashboard without DRAPER_DASHBOARD_TOKEN or "
                "DASHBOARD_API_TOKEN. Set DRAPER_ALLOW_UNAUTHENTICATED_LOCAL=1 "
                "only for loopback-only development."
            )
        if len(self.token) < MIN_TOKEN_LENGTH:
            raise RuntimeError(
                f"Dashboard token must be at least {MIN_TOKEN_LENGTH} characters "
                "for authenticated dashboard access."
            )

    def is_valid_token(self, candidate: str) -> bool:
        if not self.token or not candidate:
            return False
        return secrets.compare_digest(candidate, self.token)

    def authenticate(self, candidate: str, store: Any = None) -> Optional[Principal]:
        """Authenticate an admin env token or a SQLite-backed scoped token."""
        if self.is_valid_token(candidate):
            return Principal(
                token_id="env-admin",
                label="Environment admin token",
                is_admin=True,
                mcp_enabled=True,
                token_prefix="env",
            )
        if not candidate or store is None:
            return None
        record = store.get_access_token_by_hash(hash_access_token(candidate))
        if not record:
            return None
        return Principal(
            token_id=record["token_id"],
            label=record.get("label", "Project token"),
            is_admin=bool(record.get("is_admin")),
            project_roles={
                project_id: normalize_role(role)
                for project_id, role in (record.get("project_roles") or {}).items()
            },
            mcp_enabled=bool(record.get("mcp_enabled")),
            token_prefix=record.get("token_prefix", ""),
        )

    def extract_token(
        self,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
    ) -> str:
        token, _source = self.extract_token_with_source(headers, cookies)
        return token

    def extract_token_with_source(
        self,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
    ) -> tuple[str, str]:
        auth_header = headers.get("authorization") or headers.get("Authorization") or ""
        if auth_header.lower().startswith("bearer "):
            return auth_header.split(" ", 1)[1].strip(), "header"

        api_key = (
            headers.get("x-api-key")
            or headers.get("X-API-Key")
            or headers.get("x-dashboard-token")
            or headers.get("X-Dashboard-Token")
        )
        if api_key:
            return api_key.strip(), "header"

        cookie = cookies.get(COOKIE_NAME, "")
        return cookie, "cookie" if cookie else ""

    @staticmethod
    def is_exempt_path(path: str) -> bool:
        return path in {"/health", "/api/health", "/login", "/logout", "/favicon.ico"} or path.startswith(
            "/static/"
        )
