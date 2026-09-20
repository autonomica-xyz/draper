"""Helpers for MCP long-form generation payloads."""

from __future__ import annotations

from typing import Any


def content_from_long_form_result(result: Any) -> str:
    """Return markdown/text body from a generator result.

    Blog/email/etc generators return a dict with a ``content`` field. Callers
    that did ``str(result)`` leaked the whole dict into the review pipeline.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        raw = result.get("content") or result.get("text") or ""
        return raw if isinstance(raw, str) else str(raw)
    if result is None:
        return ""
    return str(result)
