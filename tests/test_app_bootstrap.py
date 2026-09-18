"""Plan 03-04 Task 2: dashboard/unified_dashboard.py bootstrap contract.

Asserts the documented invariants of the rewritten bootstrap module:

* ARCH-04 criterion #1: ``dashboard/unified_dashboard.py`` is ≤300 lines.
* No inline FastAPI routes or middleware remain in the bootstrap module.
* ``main`` is callable and preserves the documented CLI flag surface.
* Backward-compat re-exports (``ApproveContentRequest``,
  ``_validation_error_message``, ``UnifiedDashboard``) still work.
* ``python -m dashboard.unified_dashboard --run-server`` boots a working
  app via ``build_app(AppContainer(...))`` — verified with TestClient
  rather than spawning a subprocess.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_PATH = REPO_ROOT / "dashboard" / "unified_dashboard.py"


@pytest.fixture
def container(project_data_dir: Any, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
    from dashboard.app_container import AppContainer

    return AppContainer(data_dir=str(project_data_dir))


class TestBootstrapLineCount:
    def test_unified_dashboard_is_at_most_300_lines(self):
        line_count = len(BOOTSTRAP_PATH.read_text().splitlines())
        assert line_count <= 300, f"unified_dashboard.py is {line_count} lines (target ≤300)"

    def test_no_inline_routes_or_middleware_in_bootstrap(self):
        source = BOOTSTRAP_PATH.read_text()
        for forbidden in ("@app.get(", "@app.post(", "@app.put(", "@app.delete(",
                          "@app.patch(", "@app.middleware("):
            assert forbidden not in source, f"bootstrap still contains {forbidden!r}"


class TestBootstrapImportsAndRexports:
    def test_main_is_callable(self):
        from dashboard.unified_dashboard import main

        assert callable(main)

    def test_legacy_reexports_present(self):
        from dashboard.unified_dashboard import (
            ApproveContentRequest,
            UnifiedDashboard,
            _validation_error_message,
            main,
        )

        assert ApproveContentRequest is not None
        assert UnifiedDashboard is not None
        assert callable(_validation_error_message)
        assert callable(main)

    def test_reexported_approve_content_request_matches_canonical_home(self):
        from dashboard.routes.reviews import ApproveContentRequest as Canonical
        from dashboard.unified_dashboard import ApproveContentRequest as Reexported

        assert Reexported is Canonical

    def test_reexported_validation_error_message_matches_canonical_home(self):
        from dashboard.routes._helpers import validation_error_message as canonical
        from dashboard.unified_dashboard import _validation_error_message as reexported

        assert reexported is canonical


class TestBootstrapMainArgparseSurface:
    def test_main_preserves_documented_cli_flags(self):
        from dashboard.unified_dashboard import main

        main_source = inspect.getsource(main)
        for flag in (
            "--run-server",
            "--port",
            "--host",
            "--generate",
            "--run-jobs",
            "--jobs-once",
            "--job-kind",
            "--job-sleep",
        ):
            assert flag in main_source, f"main() lost the {flag} CLI flag"

    def test_main_delegates_to_build_app(self):
        from dashboard.unified_dashboard import main

        source = inspect.getsource(main)
        assert "build_app(" in source, "main() must call build_app(container)"
        assert "AppContainer(" in source, "main() must construct an AppContainer"


class TestBootstrapEndToEnd:
    def test_build_app_with_app_container_serves_health(self, container):
        from dashboard.app_factory import build_app

        client = TestClient(build_app(container))
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "status": "ok"}

    def test_build_app_with_app_container_serves_csrf_token(self, container):
        from dashboard.app_factory import build_app

        client = TestClient(build_app(container))
        resp = client.get("/api/csrf-token")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["csrf_token"], str)
        assert body["csrf_token"]

    def test_main_invocation_pattern_is_documented(self):
        source = BOOTSTRAP_PATH.read_text()
        assert 'if __name__ == "__main__"' in source
        assert "uvicorn.run(" in source
