"""Import-boundary tests freezing the dependency surface of the legacy project manager.

This test freezes the dependency surface of the legacy slug-based project
manager module. The allow-list captures the Phase 0 production baseline.
Phase 1 removes entries as modules migrate to the canonical project service.
Tests and the virtualenv are excluded from the scan because tests may import
either manager for comparison and the venv contains third-party modules that
are out of our control.

Expanding the allow-list silently weakens the freeze; additions require an
amendment to the canonical-shape ADR.

Phase 5 plan 05-02 extends this module with a second freeze: the services/
SQLiteStore import surface. New application services must NOT import
SQLiteStore directly; they go through data/repositories/ instead (ARCH-07,
criterion #4). Existing services are grandfathered.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOW_LIST = frozenset()

EXCLUDE_DIRS = frozenset(
    {
        ".venv",
        ".git",
        "__pycache__",
        ".planning",
        "tests",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        ".eggs",
        "build",
        "dist",
    }
)

FORBIDDEN_IMPORT_RE = re.compile(
    r"^[ \t]*(?:"
    r"from data\.project_manager import|"
    r"import data\.project_manager|"
    r"from data import project_manager"
    r")",
    re.MULTILINE,
)

ALLOW_LIST_SERVICES_STORE = frozenset(
    {
        "services/project_service.py",
        "services/idea_lab.py",
    }
)

FORBIDDEN_SERVICES_STORE_RE = re.compile(
    r"^[ \t]*(?:"
    r"from data\.sqlite_store import|"
    r"import data\.sqlite_store|"
    r"from data import sqlite_store"
    r")",
    re.MULTILINE,
)


def _production_python_files():
    """Yield (absolute_path, relative_path) tuples for production .py files.

    Walks the repository, skipping any file whose path intersects EXCLUDE_DIRS.
    """
    for absolute_path in REPO_ROOT.rglob("*.py"):
        relative_path = absolute_path.relative_to(REPO_ROOT)
        if any(part in EXCLUDE_DIRS for part in relative_path.parts):
            continue
        yield absolute_path, relative_path


def test_no_new_legacy_project_manager_imports_outside_allow_list():
    """No production file outside ALLOW_LIST may import the legacy module."""
    violators = []
    for absolute_path, relative_path in _production_python_files():
        text = absolute_path.read_text(encoding="utf-8")
        if FORBIDDEN_IMPORT_RE.search(text):
            posix_relative = relative_path.as_posix()
            if posix_relative not in ALLOW_LIST:
                violators.append(posix_relative)

    if violators:
        pytest.fail(
            "New legacy project-manager imports found outside the allow-list:\n"
            + "\n".join(f"  - {path}" for path in sorted(violators))
            + "\n\nEither migrate the module to the canonical project service "
            "(Phase 1) or, if this is a legitimate baseline addition, update "
            "ALLOW_LIST with an ADR amendment to "
            "docs/adr/0001-canonical-project-shape.md."
        )


def test_allow_list_entries_still_import_legacy_module():
    """ALLOW_LIST entries must still import the legacy module (staleness guard)."""
    stale = []
    for posix_relative in sorted(ALLOW_LIST):
        absolute_path = REPO_ROOT / posix_relative
        if not absolute_path.exists():
            stale.append(f"{posix_relative} (file missing)")
            continue
        text = absolute_path.read_text(encoding="utf-8")
        if not FORBIDDEN_IMPORT_RE.search(text):
            stale.append(f"{posix_relative} (import removed)")

    if stale:
        pytest.fail(
            "Stale allow-list entries detected — entries must still import the "
            "legacy module:\n"
            + "\n".join(f"  - {entry}" for entry in stale)
            + "\n\nIf a module was migrated away from the legacy project "
            "manager, remove it from ALLOW_LIST."
        )


def _services_python_files():
    """Yield (absolute_path, relative_path) tuples for services/*.py files."""
    services_dir = REPO_ROOT / "services"
    if not services_dir.is_dir():
        return
    for absolute_path in services_dir.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in absolute_path.relative_to(REPO_ROOT).parts):
            continue
        yield absolute_path, absolute_path.relative_to(REPO_ROOT)


def test_no_new_services_import_sqlite_store_outside_allow_list():
    """No services/*.py file outside ALLOW_LIST_SERVICES_STORE may import SQLiteStore.

    Criterion #4: new application services do not import SQLiteStore directly;
    they go through data/repositories/ instead (ARCH-07). Existing services
    are grandfathered via the allow-list.
    """
    violators = []
    for absolute_path, relative_path in _services_python_files():
        text = absolute_path.read_text(encoding="utf-8")
        if FORBIDDEN_SERVICES_STORE_RE.search(text):
            posix_relative = relative_path.as_posix()
            if posix_relative not in ALLOW_LIST_SERVICES_STORE:
                violators.append(posix_relative)

    if violators:
        pytest.fail(
            "New services/ SQLiteStore imports found outside the allow-list:\n"
            + "\n".join(f"  - {path}" for path in sorted(violators))
            + "\n\nRoute persistence through data/repositories/ instead of "
            "importing SQLiteStore directly (ARCH-07, criterion #4). If this "
            "is a legitimate baseline addition (e.g. a service that "
            "legitimately constructs the store), update "
            "ALLOW_LIST_SERVICES_STORE with an ADR amendment referencing "
            "docs/adr/0001-canonical-project-shape.md (or a new ADR)."
        )


def test_services_store_allow_list_entries_still_import():
    """ALLOW_LIST_SERVICES_STORE entries must still import SQLiteStore (staleness guard)."""
    stale = []
    for posix_relative in sorted(ALLOW_LIST_SERVICES_STORE):
        absolute_path = REPO_ROOT / posix_relative
        if not absolute_path.exists():
            stale.append(f"{posix_relative} (file missing)")
            continue
        text = absolute_path.read_text(encoding="utf-8")
        if not FORBIDDEN_SERVICES_STORE_RE.search(text):
            stale.append(f"{posix_relative} (import removed)")

    if stale:
        pytest.fail(
            "Stale ALLOW_LIST_SERVICES_STORE entries detected — entries must "
            "still import SQLiteStore:\n"
            + "\n".join(f"  - {entry}" for entry in stale)
            + "\n\nIf a service was migrated to route through repositories, "
            "remove it from ALLOW_LIST_SERVICES_STORE."
        )


def test_job_queue_service_routes_persistence_through_job_repository():
    """JobQueueService (the reference migration) routes persistence through JobRepository.

    Asserts the routing refactor from plan 05-02: every former
    self.store.<job method> call site now goes through self.job_repo.<method>,
    so the service holds a repository reference, not raw SQLiteStore job methods.
    """
    job_queue_path = REPO_ROOT / "services" / "job_queue.py"
    text = job_queue_path.read_text(encoding="utf-8")

    repo_call_count = len(re.findall(r"self\.job_repo\.", text))
    if repo_call_count < 6:
        pytest.fail(
            f"services/job_queue.py routes only {repo_call_count} call(s) "
            "through self.job_repo — expected >= 6 (one per public "
            "JobQueueService method). The reference migration requires "
            "self.job_repo call sites replacing the former self.store.<job "
            "method> call sites (ARCH-07, plan 05-02)."
        )

    forbidden_patterns = [
        r"self\.store\.[a-zA-Z_]*_job_record",
        r"self\.store\.enqueue_job",
        r"self\.store\.claim_next_job",
        r"self\.store\.cancel_job",
        r"self\.store\.get_job_stats",
        r"self\.store\.recover_stuck_jobs",
    ]
    leftover = []
    for pattern in forbidden_patterns:
        matches = re.findall(pattern, text)
        leftover.extend(matches)
    if leftover:
        pytest.fail(
            "services/job_queue.py still calls SQLiteStore job methods directly: "
            + ", ".join(sorted(set(leftover)))
            + ". Route these through self.job_repo.<method> instead (ARCH-07, "
            "plan 05-02)."
        )
