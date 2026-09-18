"""Plan 05-04 Task 1: RequestId middleware + observability log-format contract.

Pins the five behavior spec items:

* An incoming request without ``X-Request-ID`` gets a server-generated
  32-char hex ID, echoed on the response.
* An incoming request with ``X-Request-ID`` echoes the supplied value.
* ``services.observability.current_request_id`` resolves to the active ID
  inside a request scope and to ``"-"`` outside one.
* ``DEFAULT_LOG_FORMAT`` contains the ``%(request_id)s`` placeholder and a
  ``RequestContextFilter`` attaches ``request_id`` (and ``job_id``) to every
  ``LogRecord``.
* ``dashboard.app_factory.build_app`` registers ``RequestIdMiddleware``
  as the outermost middleware so the ``request_id`` contextvar is set
  before ``AuthMiddleware`` runs — every auth log line (token validation,
  access-denied, redirect-to-login) therefore carries a ``request_id``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parent.parent
APP_FACTORY_PATH = REPO_ROOT / "dashboard" / "app_factory.py"
OBSERVABILITY_PATH = REPO_ROOT / "services" / "observability.py"


def _build_app_with_request_id_only() -> FastAPI:
    from dashboard.middleware.request_id import RequestIdMiddleware

    app = FastAPI()
    app.middleware("http")(RequestIdMiddleware())

    @app.get("/inspect")
    async def inspect(request: Request):
        return {
            "request_id": getattr(request.state, "request_id", None),
        }

    return app


class TestRequestIdGeneration:
    def test_request_without_x_request_id_header_gets_generated_hex(self):
        client = TestClient(_build_app_with_request_id_only())
        resp = client.get("/inspect")
        assert resp.status_code == 200
        rid = resp.headers.get("X-Request-ID")
        assert rid is not None
        assert re.fullmatch(r"[0-9a-f]{32}", rid) is not None, (
            f"expected 32-char hex, got {rid!r}"
        )
        body = resp.json()
        assert body["request_id"] == rid

    def test_request_with_x_request_id_header_echoes_supplied_value(self):
        client = TestClient(_build_app_with_request_id_only())
        supplied = "client-trace-id-1234"
        resp = client.get("/inspect", headers={"X-Request-ID": supplied})
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == supplied
        assert resp.json()["request_id"] == supplied

    def test_client_supplied_oversized_id_is_truncated_to_128_chars(self):
        client = TestClient(_build_app_with_request_id_only())
        oversized = "x" * 512
        resp = client.get("/inspect", headers={"X-Request-ID": oversized})
        assert resp.status_code == 200
        echoed = resp.headers["X-Request-ID"]
        assert len(echoed) <= 128
        assert echoed == "x" * 128

    def test_generated_id_is_unique_across_requests(self):
        client = TestClient(_build_app_with_request_id_only())
        first = client.get("/inspect").headers["X-Request-ID"]
        second = client.get("/inspect").headers["X-Request-ID"]
        assert first != second


class TestContextVarAccessor:
    def test_outside_request_scope_returns_dash(self):
        from services.observability import current_request_id

        assert current_request_id() == "-"

    def test_inside_request_scope_returns_active_request_id(self):
        from services.observability import current_request_id

        captured: list[str] = []

        app = FastAPI()

        @app.middleware("http")
        async def dispatch(request: Request, call_next):
            captured.append(("before", current_request_id()))
            response = await call_next(request)
            captured.append(("after", current_request_id()))
            return response

        from dashboard.middleware.request_id import RequestIdMiddleware

        app.middleware("http")(RequestIdMiddleware())

        @app.get("/probe")
        async def probe():
            captured.append(("inside", current_request_id()))
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/probe", headers={"X-Request-ID": "scope-trace"})
        assert resp.status_code == 200
        inside = next(c[1] for c in captured if c[0] == "inside")
        assert inside == "scope-trace"


class TestLogFormatContract:
    def test_default_log_format_contains_request_id_and_job_id_placeholders(self):
        from services.observability import DEFAULT_LOG_FORMAT

        assert "%(request_id)s" in DEFAULT_LOG_FORMAT
        assert "%(job_id)s" in DEFAULT_LOG_FORMAT

    def test_request_context_filter_attaches_request_id_to_record(self, caplog):
        from dashboard.middleware.request_id import RequestIdMiddleware
        from services.observability import (
            RequestContextFilter,
            current_request_id,
            get_logger,
        )

        app = FastAPI()
        app.middleware("http")(RequestIdMiddleware())

        captured_records: list[logging.LogRecord] = []

        @app.get("/log")
        async def emit_log():
            log = get_logger("plan_05_04_probe")
            log.info("probe-message")
            for record in caplog.records:
                if record.message == "probe-message":
                    captured_records.append(record)
            return {"current": current_request_id()}

        handler = logging.getLogger("plan_05_04_probe")
        test_handler = logging.StreamHandler()
        test_handler.addFilter(RequestContextFilter())
        caplog.set_level(logging.INFO, logger="plan_05_04_probe")
        for handler_inst in logging.getLogger().handlers:
            handler_inst.addFilter(RequestContextFilter())

        try:
            client = TestClient(app)
            resp = client.get("/log", headers={"X-Request-ID": "log-trace-id"})
            assert resp.status_code == 200
            assert resp.json()["current"] == "log-trace-id"
            matching = [
                r
                for r in caplog.records
                if r.message == "probe-message" and r.name == "plan_05_04_probe"
            ]
            assert matching, "caplog did not capture the probe log record"
            record = matching[0]
            assert getattr(record, "request_id", None) == "log-trace-id"
        finally:
            for handler_inst in logging.getLogger().handlers:
                if isinstance(handler_inst, logging.StreamHandler):
                    try:
                        handler_inst.removeFilter(
                            next(
                                f
                                for f in handler_inst.filters
                                if isinstance(f, RequestContextFilter)
                            )
                        )
                    except (StopIteration, ValueError):
                        pass

    def test_request_context_filter_defaults_request_and_job_to_dash(self):
        from services.observability import RequestContextFilter

        record = logging.LogRecord(
            name="probe",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=(),
            exc_info=None,
        )
        flt = RequestContextFilter()
        assert flt.filter(record) is True
        assert record.request_id == "-"
        assert record.job_id == "-"


class TestJobIdContextVarAccessor:
    def test_set_job_id_then_reset_restores_dash(self):
        from services.observability import current_job_id, set_job_id

        assert current_job_id() == "-"
        token = set_job_id("job_abc123")
        try:
            assert current_job_id() == "job_abc123"
        finally:
            set_job_id("-", token)
        assert current_job_id() == "-"


class TestAppFactoryRegistration:
    def test_app_factory_imports_and_attaches_request_id_middleware(self):
        source = APP_FACTORY_PATH.read_text()
        assert "RequestIdMiddleware" in source, (
            "dashboard/app_factory.py must construct RequestIdMiddleware"
        )
        assert "request_id_middleware" in source, (
            "dashboard/app_factory.py must attach request_id_middleware to the app"
        )

    def test_build_app_response_carries_x_request_id_header(
        self, project_data_dir: Any, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
        from dashboard.app_container import AppContainer
        from dashboard.app_factory import build_app

        container = AppContainer(data_dir=str(project_data_dir))
        app = build_app(container)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        assert re.fullmatch(r"[0-9a-f]{32}", resp.headers["X-Request-ID"]) is not None

    def test_build_app_echoes_client_supplied_x_request_id(
        self, project_data_dir: Any, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
        from dashboard.app_container import AppContainer
        from dashboard.app_factory import build_app

        container = AppContainer(data_dir=str(project_data_dir))
        app = build_app(container)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health", headers={"X-Request-ID": "client-trace-xyz"})
        assert resp.headers["X-Request-ID"] == "client-trace-xyz"
