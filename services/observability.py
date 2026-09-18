"""Logging setup for operational visibility.

Extends the stdlib logger with two contextvars — ``request_id`` and
``job_id`` — surfaced on every ``LogRecord`` via :class:`RequestContextFilter`
so a single format string carries request and job correlation IDs without
callers having to thread them through every log call.
"""

import logging
import os
from contextvars import ContextVar, Token
from typing import Optional

from services.utc import utc_now, utc_now_iso


_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
_job_id_ctx: ContextVar[str] = ContextVar("job_id", default="-")

__all__ = [
    "DEFAULT_LOG_FORMAT",
    "RequestContextFilter",
    "configure_logging",
    "current_job_id",
    "current_request_id",
    "get_logger",
    "reset_request_id",
    "set_job_id",
    "set_request_id",
    "utc_now",
    "utc_now_iso",
]


DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "request_id=%(request_id)s job_id=%(job_id)s %(message)s"
)


def current_request_id() -> str:
    return _request_id_ctx.get()


def set_request_id(value: str) -> Token[str]:
    return _request_id_ctx.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id_ctx.reset(token)


def current_job_id() -> str:
    return _job_id_ctx.get()


def set_job_id(value: str, token: Optional[Token[str]] = None) -> Token[str]:
    if token is not None:
        _job_id_ctx.reset(token)
        return token
    return _job_id_ctx.set(value)


class RequestContextFilter(logging.Filter):
    """Attach ``request_id`` and ``job_id`` contextvars to every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        record.job_id = current_job_id()
        return True


def configure_logging(level: str | None = None) -> None:
    """Configure standard-library logging once for app processes."""
    resolved_level = (level or os.getenv("DRAPER_LOG_LEVEL") or "INFO").upper()
    handler_format = os.getenv("DRAPER_LOG_FORMAT", DEFAULT_LOG_FORMAT)
    formatter = logging.Formatter(handler_format)
    formatter_filter = RequestContextFilter()
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        handler.addFilter(formatter_filter)
        root.addHandler(handler)
    else:
        for existing in root.handlers:
            existing.setFormatter(formatter)
            if not any(
                isinstance(f, RequestContextFilter) for f in existing.filters
            ):
                existing.addFilter(formatter_filter)
    root.setLevel(getattr(logging, resolved_level, logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
