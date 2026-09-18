"""Helpers for binding content generators to a target project."""

from __future__ import annotations

from copy import copy
from typing import Any


def scoped_generator_for_project(
    generator: Any, project: Any, secret_service: Any = None
) -> Any:
    """Return a generator instance/copy with ``project`` bound when supported.

    The concrete LLM/ZAI generators read ``self.project`` while building
    prompts. Keep the dashboard's singleton unmodified so concurrent requests
    cannot leak one project's context into another generation call.

    When ``secret_service`` is provided and the generator has a ``project``
    attribute, the scoped copy's ``llm_override`` is set from
    ``secret_service.resolve_project_llm(project_id)`` (may be ``None`` —
    the valid "use env fallback" state). When ``secret_service`` is ``None``
    ``llm_override`` is left untouched (backward compat for callers that do
    not pass it).
    """
    if generator is None or project is None:
        return generator
    if not hasattr(generator, "project"):
        return generator
    scoped = copy(generator)
    scoped.project = project
    if secret_service is not None and hasattr(project, "project_id"):
        scoped.llm_override = secret_service.resolve_project_llm(project.project_id)
    return scoped
