"""worker.get_data_dir must honor DRAPER_DATA_DIR like the dashboard."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _load_worker():
    """Import the repo-root worker.py (force-included into the wheel)."""
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    if "worker" in sys.modules:
        del sys.modules["worker"]
    import worker

    return importlib.reload(worker)


def test_get_data_dir_uses_draper_data_dir_env(tmp_path, monkeypatch):
    target = tmp_path / "custom-data"
    monkeypatch.setenv("DRAPER_DATA_DIR", str(target))
    worker = _load_worker()

    resolved = worker.get_data_dir()

    assert resolved == target
    assert target.is_dir()


def test_get_data_dir_falls_back_to_repo_data(tmp_path, monkeypatch):
    monkeypatch.delenv("DRAPER_DATA_DIR", raising=False)
    worker = _load_worker()
    fake_worker = tmp_path / "worker.py"
    fake_worker.write_text("# stub\n")
    monkeypatch.setattr(worker, "__file__", str(fake_worker))

    resolved = worker.get_data_dir()

    assert resolved == tmp_path / "data"
    assert resolved.is_dir()
