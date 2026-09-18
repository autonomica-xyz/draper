"""Shared pytest fixtures for the Draper test suite."""

from pathlib import Path

import pytest

from data.sqlite_store import SQLiteStore
from tests.fixtures.project_factory import make_fixture_project


@pytest.fixture
def project_data_dir(tmp_path: Path) -> Path:
    """Provide a clean temp data directory per test."""
    return tmp_path


@pytest.fixture
def seeded_store(project_data_dir: Path) -> SQLiteStore:
    """Construct an isolated SQLiteStore with the fixture project seeded.

    Uses the store's default ``marketing_pipeline.sqlite3`` filename inside
    ``project_data_dir`` so that ProjectManagers built later with the same
    ``data_dir`` open the SAME database file.
    """
    store = SQLiteStore(data_dir=str(project_data_dir), migrate=False)
    make_fixture_project(store)
    return store


@pytest.fixture
def fixture_project(seeded_store: SQLiteStore) -> dict:
    """Return the expected-values descriptor for the fixture project.

    Depends on ``seeded_store`` so the project is already in the DB; calling
    ``make_fixture_project`` again is idempotent and returns the descriptor.
    """
    return make_fixture_project(seeded_store)
