"""Auto-discovering router package.

Each submodule of ``dashboard.routes`` that exports a module-level ``router``
attribute (an instance of ``fastapi.APIRouter``) is yielded by
``iter_routers()``. Submodules whose names start with ``_`` are skipped so
helper modules (``_helpers.py``, ``_models.py``) are not mistaken for
route modules.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable

from fastapi import APIRouter


def iter_routers() -> Iterable[APIRouter]:
    """Yield each module-level ``router`` (APIRouter) under ``dashboard.routes``."""
    routers: list[APIRouter] = []
    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        if name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{name}")
        candidate = getattr(module, "router", None)
        if isinstance(candidate, APIRouter):
            routers.append(candidate)
    return routers
