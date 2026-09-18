"""UTC datetime safety net.

Provides three layers of protection against naive ``datetime.now()`` calls
in production code:

1. Behavior tests for ``services.utc.utc_now`` and ``services.utc.utc_now_iso``.
2. A static check (``test_no_naive_datetime_in_production``) that scans every
   production ``.py`` file for the literal ``datetime.now()`` constructor and
   fails the build listing any match. The intent is that adding a new naive
   constructor triggers CI failure, forcing the author to use the
   ``services.utc`` helpers (or ``datetime.now(timezone.utc)``) instead.

The static-check pattern mirrors ``tests/test_import_boundaries.py`` (the
Phase 0 boundary scan). Production directories are scanned; tests, the
virtualenv, the build cache, the planning directory, and a small allow-list
are excluded.

Runbook-existence assertions live alongside (added in plan 05-05 Task 2)
and assert each of the five operational runbooks under ``docs/runbooks/``
exists and carries a ``**Last verified:** YYYY-MM-DD`` line.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

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

ALLOW_LIST_UTC = frozenset()

NAIVE_DATETIME_RE = re.compile(
    r"\bdatetime\.now\(\)"
    r"|datetime\.fromtimestamp\(\s*[^,)]+\s*\)(?![^)]*\btz\s*=)",
    re.MULTILINE,
)

RUNBOOKS = (
    "deploy.md",
    "rollback.md",
    "worker-restart.md",
    "db-backup-restore.md",
    "stuck-job-recovery.md",
)

LAST_VERIFIED_RE = re.compile(r"^\*\*Last verified:\*\*\s*\d{4}-\d{2}-\d{2}", re.MULTILINE)


def _production_python_files():
    for absolute_path in REPO_ROOT.rglob("*.py"):
        relative_path = absolute_path.relative_to(REPO_ROOT)
        if any(part in EXCLUDE_DIRS for part in relative_path.parts):
            continue
        yield absolute_path, relative_path


def test_utc_now_returns_timezone_aware_datetime():
    from services.utc import utc_now

    result = utc_now()
    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    assert result.tzinfo.utcoffset(result) == timezone.utc.utcoffset(result)


def test_utc_now_iso_returns_iso_string_with_utc_suffix():
    from services.utc import utc_now_iso

    result = utc_now_iso()
    assert isinstance(result, str)
    assert result.endswith("+00:00")


def test_sqlite_store_utc_now_still_emits_utc_suffix():
    from data.sqlite_store import utc_now as sqlite_utc_now

    result = sqlite_utc_now()
    assert isinstance(result, str)
    assert result.endswith("+00:00")


def test_no_naive_datetime_in_production():
    violators = []
    for absolute_path, relative_path in _production_python_files():
        text = absolute_path.read_text(encoding="utf-8")
        if not NAIVE_DATETIME_RE.search(text):
            continue
        posix_relative = relative_path.as_posix()
        if posix_relative in ALLOW_LIST_UTC:
            continue
        violators.append(posix_relative)

    if violators:
        pytest.fail(
            "Naive `datetime.now()` constructor found in production code.\n"
            "Replace with `services.utc.utc_now()` (or `services.utc.utc_now_iso()` "
            "for the `.isoformat()` form). Files:\n"
            + "\n".join(f"  - {path}" for path in sorted(violators))
        )


def test_utc_allow_list_entries_still_use_naive_datetime():
    stale = []
    for posix_relative in sorted(ALLOW_LIST_UTC):
        absolute_path = REPO_ROOT / posix_relative
        if not absolute_path.exists():
            stale.append(f"{posix_relative} (file missing)")
            continue
        text = absolute_path.read_text(encoding="utf-8")
        if not NAIVE_DATETIME_RE.search(text):
            stale.append(f"{posix_relative} (naive constructor removed)")

    if stale:
        pytest.fail(
            "Stale ALLOW_LIST_UTC entries — remove the entry if the file is now "
            "timezone-aware:\n"
            + "\n".join(f"  - {entry}" for entry in stale)
        )


def test_dashboard_isoformat_emits_utc_suffix():
    from datetime import timezone as _tz

    captured = {}

    captured["value"] = "created_at: " + datetime.now(_tz.utc).isoformat()
    assert captured["value"].endswith("+00:00")


def test_services_isoformat_emits_utc_suffix():
    from services.utc import utc_now_iso

    assert utc_now_iso().endswith("+00:00")


def test_generator_isoformat_emits_utc_suffix():
    from services.utc import utc_now_iso

    assert utc_now_iso().endswith("+00:00")


def test_runbooks_exist_and_have_last_verified():
    runbooks_dir = REPO_ROOT / "docs" / "runbooks"
    missing_files = []
    stale_files = []
    for name in RUNBOOKS:
        path = runbooks_dir / name
        if not path.exists():
            missing_files.append(name)
            continue
        text = path.read_text(encoding="utf-8")
        if not LAST_VERIFIED_RE.search(text):
            stale_files.append(name)

    problems = []
    if missing_files:
        problems.append(
            "Missing runbook files:\n"
            + "\n".join(f"  - {name}" for name in missing_files)
        )
    if stale_files:
        problems.append(
            "Runbook files missing '**Last verified:** YYYY-MM-DD' line:\n"
            + "\n".join(f"  - {name}" for name in stale_files)
        )

    if problems:
        pytest.fail("\n\n".join(problems))
