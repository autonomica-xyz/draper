import stat
from pathlib import Path

import pytest
from starlette.requests import Request

from data.sqlite_store import SQLiteStore
from dashboard.middleware.auth import _request_principal
from services.access_control import AccessDeniedError, DashboardAccessPolicy, Principal
from services.idea_lab import IdeaLabService


def test_sqlite_database_file_is_owner_only(tmp_path):
    db_path = tmp_path / "marketing_pipeline.sqlite3"

    SQLiteStore(data_dir=tmp_path, db_path=db_path, migrate=False)

    mode = stat.S_IMODE(db_path.stat().st_mode)
    assert mode == 0o600


def test_project_access_token_is_hashed_and_authenticates(tmp_path):
    store = SQLiteStore(data_dir=tmp_path, migrate=False)
    store.save_project_record({"project_id": "project-a", "name": "Project A"})

    created = store.create_access_token(
        label="Project A publisher",
        project_roles={"project-a": "publisher"},
        mcp_enabled=True,
    )

    assert created["token"].startswith("draper_")
    assert "token" not in (store.get_access_token(created["token_id"]) or {})

    principal = DashboardAccessPolicy(
        host="127.0.0.1",
        token="admin-token-with-enough-length",
    ).authenticate(created["token"], store)

    assert principal is not None
    assert principal.is_admin is False
    assert principal.has_project_role("project-a", "publisher")
    assert not principal.has_project_role("project-a", "owner")


def test_scoped_principal_can_authorize_any_assigned_project():
    principal = Principal(
        token_id="tok_test",
        label="Scoped",
        project_roles={"project-a": "viewer", "project-b": "editor"},
    )

    principal.require_any_project_role("viewer")
    principal.require_any_project_role("editor")

    with pytest.raises(AccessDeniedError):
        principal.require_any_project_role("publisher")


def test_project_mcp_config_caps_scoped_token_role(tmp_path, monkeypatch):
    store = SQLiteStore(data_dir=tmp_path, migrate=False)
    store.save_project_record({"project_id": "project-a", "name": "Project A"})
    store.set_project_mcp_config(
        "project-a",
        {"enabled": True, "max_role": "viewer", "allowed_tools": ["list_content"]},
    )
    created = store.create_access_token(
        label="Project A MCP",
        project_roles={"project-a": "owner"},
        mcp_enabled=True,
    )

    import mcp_server.server as server

    monkeypatch.setattr(server, "STORE", store)

    principal = server._authenticate_mcp_token(created["token"])

    assert principal is not None
    assert principal.role_for("project-a") == "viewer"


def test_project_mcp_config_disabled_rejects_scoped_token(tmp_path, monkeypatch):
    store = SQLiteStore(data_dir=tmp_path, migrate=False)
    store.save_project_record({"project_id": "project-a", "name": "Project A"})
    created = store.create_access_token(
        label="Project A MCP",
        project_roles={"project-a": "editor"},
        mcp_enabled=True,
    )

    import mcp_server.server as server

    monkeypatch.setattr(server, "STORE", store)

    assert server._authenticate_mcp_token(created["token"]) is None


def test_idea_lab_rejects_non_http_source_urls(tmp_path):
    service = IdeaLabService(SQLiteStore(data_dir=tmp_path, migrate=False))

    with pytest.raises(ValueError, match="http or https"):
        service.add_source_material(project_id="project-a", url="javascript:alert(1)")

    with pytest.raises(ValueError, match="http or https"):
        service.add_source_material(project_id="project-a", url="data:text/html,hi")


def test_content_idea_update_cannot_reassign_project(tmp_path):
    service = IdeaLabService(SQLiteStore(data_dir=tmp_path, migrate=False))
    idea = service.add_content_idea(project_id="project-a", title="Idea")

    updated = service.update_content_idea(
        idea["idea_id"],
        **{
            "title": "New title",
            "project_id": "project-b",
        },
    )

    assert updated["title"] == "New title"
    assert updated["project_id"] == "project-a"
    assert updated["idea_id"] == idea["idea_id"]


def test_request_principal_fallback_is_fail_closed():
    """A request without an attached principal must never imply admin.

    Defense in depth for routes mounted without AuthMiddleware: the
    fallback principal holds no roles, so every require_* check denies.
    """
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    principal = _request_principal(Request(scope))

    assert principal.is_admin is False
    assert principal.project_ids == []
    with pytest.raises(AccessDeniedError):
        principal.require_project_role("any-project", "viewer")


def test_dashboard_service_unit_keeps_exposure_hardening():
    """The unit binds 0.0.0.0 (reverse proxy on a separate host), so auth
    and secure cookies must never be silently disabled while the dashboard
    is reachable from the network.
    """
    unit_path = Path(__file__).resolve().parent.parent / "draper-dashboard.service"
    content = unit_path.read_text()

    exec_lines = [line for line in content.splitlines() if line.startswith("ExecStart=")]
    assert len(exec_lines) == 1
    assert "--run-server" in exec_lines[0]

    environment = {
        line.split("=", 1)[1]
        for line in content.splitlines()
        if line.startswith("Environment=")
    }
    assert "DRAPER_REQUIRE_AUTH=1" in environment
    assert "DASHBOARD_SECURE_COOKIE=1" in environment
    # Secrets come from EnvironmentFile, never inline in the unit.
    assert any(
        line.startswith("EnvironmentFile=") for line in content.splitlines()
    )
    assert not any(
        "TOKEN=" in env for env in environment if not env.startswith("DRAPER_REQUIRE")
    )
